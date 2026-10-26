"""The Analyst: the agent that writes a key moment's narrative. It turns a `MomentCase` into a
`Draft`.

It sees the moment's facts (ids, how to write each, what it counts and over which window), the
two clubs and lineups, the trigger events and, on a retry, what became of each earlier attempt.
It writes a caption and its claims as structured output and computes nothing: the Guard checks
every number against the engine. A call that brings no draft (timeout, rate limit, transport
error, a failed facts tool, refusal, a reply that is no `Draft`) becomes a failed `Attempt` with
a `CallFailure`, so the workflow can retry or fall back to a stats-only cue. A call no retry can
mend (credentials, a 4xx that is not transient) raises `FatalCallError` instead and stops the
run.

With a facts tool (an MCP tool of `matchlens mcp` that offers `facts_at` only) the prompt names
the moment and the Analyst reads its facts itself, at most one tool call and two model requests
per attempt; the Guard still looks every cited fact up in the engine.

The prompt states the Guard's rules and forbids what its known limits would let through
(PROGRESS.md, Follow-ups), as well as the phrasings it falsely rejects. The real client comes only
from `foundry_client` (Entra ID: the managed identity in Azure, the CLI login locally; no API
keys); the test suite makes that factory raise.
"""

import asyncio
import json
import os
import time

import anthropic
from agent_framework import (
    Agent,
    AgentResponse,
    ChatContext,
    ChatMiddleware,
    SupportsChatGetResponse,
    ToolTypes,
)
from agent_framework.exceptions import ChatClientException, ToolException
from agent_framework_anthropic import AnthropicFoundryClient
from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import ClientAuthenticationError
from azure.core.pipeline.transport import AsyncioRequestsTransport
from azure.identity.aio import (
    AzureCliCredential,
    ManagedIdentityCredential,
    get_bearer_token_provider,
)

from matchlens.explain.guard import MAX_CLAIMS, MAX_TEXT, ordinal
from matchlens.explain.state import (
    MAX_ATTEMPTS,
    Attempt,
    CallError,
    CallFailure,
    Draft,
    MomentCase,
)
from matchlens.facts import WINDOW_MS
from matchlens.league import load_league
from matchlens.match import Match

FOUNDRY_RESOURCE_ENV = "MATCHLENS_FOUNDRY_RESOURCE"
DEPLOYMENT_ENV = "MATCHLENS_ANALYST_DEPLOYMENT"
DEFAULT_DEPLOYMENT = "claude-haiku-5-5"  # development; measured runs and the demo use Sonnet
TOKEN_SCOPE = "https://ai.azure.com/.default"  # Entra scope of Claude on Foundry
IDENTITY_ENDPOINT_ENV = "IDENTITY_ENDPOINT"  # set by Azure Container Apps for a managed identity
REQUEST_TIMEOUT_S = 120.0  # one HTTP request; calls took 3.4–7.7 s on 21 Oct (Metrics), SDK: 10 min
# No SDK retries (owner, 23 Oct): a timed-out request may be billed, and a retry would be a
# request the budget never sees; a 429, a 5xx or a timeout is a failed attempt instead.
MAX_RETRIES = 0
CALL_TIMEOUT_S = 300.0  # a whole attempt: two requests with the facts tool
MAX_TOKENS = 4000  # thinking included; the smoke test's replies were 236 and 296 tokens
EFFORT = "low"
_MAX_DETAIL = 300  # characters of an error message kept in a CallFailure
RETRIED_STATUSES = frozenset({408, 409, 429})  # transient 4xx, not fatal; any other 4xx is ours
FACTS_TOOL = "facts_at"  # the one MCP tool the Analyst may call
MAX_REQUESTS = 2  # model requests of an attempt with the facts tool: the call, then the answer

_IDS = {"type": "array", "items": {"type": "string"}}
DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "fact_ids": _IDS,
                    "event_ids": _IDS,
                    "frame_ids": _IDS,
                },
                "required": ["text", "fact_ids", "event_ids", "frame_ids"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["text", "claims"],
    "additionalProperties": False,
}

_LAST = WINDOW_MS // 60_000
ANALYST_ROLE = """\
You are the Analyst of a live broadcast overlay for a fictional football match. For one key \
moment you write a caption of one to three short sentences in English and list the claims it is \
made of. A deterministic Guard checks the draft against the stats engine and rejects it on any \
breach of the rules below."""

# the rules every agent that writes for the screen follows: the Guard checks each of them
RULES = f"""\
Numbers
- Never compute, estimate or round. Every number you write is copied from the "write as" column \
of a fact, and the claim that contains it cites that fact.
- A number says only what its fact counts: a count of goals is never a count of shots, a team's \
figure is never the other team's. Write a score only as the score fact shows it, home team first.
- A fact of the window "last {_LAST} minutes" needs the words "last {_LAST} minutes" in its claim. \
A shirt number needs "No." right before it. A unit in "write as" stays right after its number, \
copied as written and never spelled out ("15.1 s", not "15.1 seconds").
- Digits only. Never write a number or a count in words: no "one", "two", "twice", "once", \
"nil", "brace", "hat-trick", "double", "a couple of", "half of" (a reading's phrase such as \
"pull one back" is the exception: copy it as it is). Write no ordinal words at all: \
no "first", "second", "third" (not "first half", "his second", "second-half"). Never use \
words that imply a count: "a goal ahead", "the only goal", "again", "another", "both", "a \
further", "added", "a minute later", "half an hour in", "half the", "back four", "front three", \
"third man", "quadruple", "yet to score", "clean sheet".
- Never put the score into words of your own: no "lead", "ahead", "in front", "behind", \
"trail", "level", "all square", "equaliser", "opener", "winner", "comeback", \
"reply", "restore", "goalless", "deadlock", "draw", "drawing", "winning", "losing", "beat", \
"unbeaten", "win", "won", "lose", "lost", "loss", "defeat", "victory", "tie", "the points", \
"advantage", "opens the scoring", "hit back", "tie", "tied", "cancel out", and no "up", \
"down", "to" or a club right after a score. Write the score, or a reading's phrase (Readings).
- Never compare, rank or judge numbers in words of your own, for the goals or any other fact: \
no "more", "fewer", "less", "most", "majority", "better", "worse", "dominate", "in control", \
"outshoot", "up from", "down from", "rise", "drop", "high", "low", "chaotic", "calm", "busy", \
"quiet", "only", "just", "despite", "against the run of play", "on the front foot". Comparing \
is computing: write the cited numbers or a reading's phrase instead.
- The Guard cannot read these forms, so never use them: "after 13 minutes", "79 percent", "the \
2nd half", formations like 4-4-2, "11 v 11", "one-on-one". Leave out a number rather than \
rephrase it.

Readings
- A fact whose name ends in _reading is the stats engine's judgement of another fact: what a \
goal does to the score, who is in the lead, who is on top, how open the play is, who has more \
of the ball. Its "write as" is a phrase such as "take the lead", "on top" or "more of the \
ball". These phrases are the only words that may judge the score or the play: copy one word \
for word into a claim that cites that reading, never in another form ("equalises", "took \
the lead", "pulls one back").
- A reading of the last 5 minutes (its id has last5-) goes into a claim that says "last 5 \
minutes"; any other reading into a claim that does not. Two windows, two claims.
- Name the club the reading is about right before its phrase in the claim, with no other club \
or player name in between: "Vellbridge Town take the lead", "Quarrendale Rovers are pinned \
back in the last 5 minutes". A reading without a team (the flow of play) needs no club.
- Say why the moment matters: where the moment has readings, use one or two of them (what the \
goal does to the score, who is on top) next to the numbers rather than repeating the event.

Claims
- A claim is a whole clause of the caption, copied character for character (the same dashes, \
quotes and spaces), so it appears word for word in the text. Every number of the caption lies \
inside a claim.
- Each claim cites the fact ids whose numbers it uses and at least one event id of the trigger \
events. Cite only ids listed in the moment. frame_ids stay empty.
- A claim about what a fact measures (possession, passes, pressing, momentum, chaos, the score, \
the minute) cites that fact and states its number.
- At most {MAX_CLAIMS} claims and {MAX_TEXT} characters.

Names
- Use only the club and player names of the moment, written as given. No other proper names, no \
titles such as Mr, no real people or clubs. Words that are no names are lower case unless they \
start a sentence. No colon as punctuation (a clock such as 67:23 is fine).

Content
- Describe only what the trigger events and the facts say. Add no detail they do not give: no \
header, volley, penalty, free kick, corner, cross, assist, distance, foot or body part.
- Place the moment in time only with the clock or minute fact: no "early", "late", "before \
half-time", "after the break", "the closing minutes".

Retries
- If earlier attempts are listed, each failed for the reasons given; a reason tagged [claim i] \
is about claim i of that attempt. Write a new draft that fixes every reason; when a number \
cannot be backed, leave it out.

Reply with the JSON object only."""

INSTRUCTIONS = f"{ANALYST_ROLE}\n\n{RULES}"

_WINDOWS = {
    "at": "at this moment",
    "to": "so far in the match",
    "last5": f"last {_LAST} minutes",
    "league": "fixed",
}


def moment_prompt(case: MomentCase, match: Match, *, tool: bool = False) -> str:
    """What the Analyst reads about `case`: clubs, lineups, triggers, facts, earlier attempts.
    Names come from the league, everything else from the case; nothing is computed here. With
    `tool` the facts are not listed: the prompt says how to read them with `facts_at` and how to
    write them, and names each club and player with the id the facts use."""
    scene = Scene(case, match, tool=tool)
    lines = [f"Moment {case.moment_id} at clock {case.display_clock}.", *scene.lines()]
    if tool:
        lines += _tool_lines(case)
    else:
        lines.append("Facts (fact_id | write as | what it counts | window):")
        lines += scene.fact_lines(case.facts)
    if case.attempts:
        lines.append("Earlier attempts, all rejected:")
    lines += attempt_lines(case.attempts)
    return "\n".join(lines)


class Scene:
    """The match around a moment, as every prompt names it: clubs, lineups, the trigger events
    and who a fact is about. Names come from the league; nothing is computed."""

    def __init__(self, case: MomentCase, match: Match, *, tool: bool = False) -> None:
        meta = match.meta
        if case.match_id != meta.match_id:
            raise ValueError(f"moment {case.moment_id!r} is not of match {meta.match_id}")
        self.case, self.meta, self.tool = case, meta, tool
        self.clubs = {c.id: c for c in load_league().clubs if c.id in (meta.home, meta.away)}
        self.players = {p.id: p.name for c in self.clubs.values() for p in c.players}
        self.events = {e.event_id: e for e in match.events}

    def who(self, team: str | None, player: str | None) -> str:
        if player:
            return self.players.get(player, player)
        return self.clubs[team].name if team in self.clubs else "the match"

    def named(self, name: str, id_: str) -> str:
        return f"{name} ({id_})" if self.tool else name

    def lines(self) -> list[str]:
        """Clubs, lineups and the trigger events."""
        meta, players = self.meta, self.players
        home, away = self.clubs[meta.home], self.clubs[meta.away]
        lines = [f"Home: {self.named(home.name, home.id)}. Away: {self.named(away.name, away.id)}."]
        for side, ids in (("Home", meta.home_lineup), ("Away", meta.away_lineup)):
            names = ", ".join(self.named(players.get(p, p), p) for p in ids)
            lines.append(f"{side} lineup: {names}.")
        lines.append("Trigger events (cite at least one in every claim):")
        for event_id in self.case.trigger_ids:
            e = self.events[event_id]
            outcome = f", {e.outcome.value.replace('_', ' ')}" if e.outcome else ""
            lines.append(f"- {event_id}: {e.type.value} by {self.who(e.team, e.player)}{outcome}")
        return lines

    def fact_lines(self, facts) -> list[str]:
        """One line a fact: fact_id | write as | what it counts | window."""
        lines = []
        for f in facts:
            name = str(f.get("name", "")).replace("_", " ")
            lines.append(
                f"- {f['fact_id']} | {write_as(f)} | {name} of "
                f"{self.who(f.get('team'), f.get('player'))} | {window(f['fact_id'])}"
            )
        return lines


def attempt_lines(attempts) -> list[str]:
    """Earlier attempts as a retry reads them: each draft, its claims and the Guard's reasons."""
    lines = []
    for a in attempts:
        if a.draft is None:
            lines.append(f"- Attempt {a.n}: no draft, {a.error.code.value}: {a.error.detail}")
            continue
        lines.append(f"- Attempt {a.n}: {json.dumps(a.draft.text, ensure_ascii=False)}")
        lines += draft_lines(a.draft)
        for r in a.verdict.reasons if a.verdict else ():
            tag = "" if r.claim is None else f"[claim {r.claim}] "
            lines.append(f"  - {tag}{r.code.value}: {r.detail}")
    return lines


def draft_lines(draft: Draft) -> list[str]:
    """A draft's claims, each with what it cites."""
    lines = []
    for i, c in enumerate(draft.claims):
        cites = f"facts {', '.join(c.fact_ids) or '-'}; events {', '.join(c.event_ids) or '-'}"
        lines.append(f"  claim {i}: {json.dumps(c.text, ensure_ascii=False)} ({cites})")
    return lines


def _tool_lines(case: MomentCase) -> list[str]:
    return [
        f'Facts: call the tool {FACTS_TOOL} once, with match_id "{case.match_id}", period '
        f"{case.period} and clock_ms {case.end_ms}, and cite only fact ids it returns.",
        "Write as: a fact's display, then its unit unless the display holds it (15.1 s); a "
        "shirt_number as No. and its display (No. 19); the minute as its display (68').",
        "Window: a fact id's third part tells it: at- at this moment, to- so far in the match, "
        f'last5- the last {_LAST} minutes (write "last {_LAST} minutes"), league fixed.',
        "What it counts: the fact's name, of its player, else its team, else the match; team "
        "and player are the ids given above. A fact named ..._reading judges another: write "
        "its display, a phrase, as it is, right after its club's name.",
    ]


def write_as(fact: dict) -> str:
    """How the prompt tells the Analyst to write a fact: forms the Guard reads as that fact
    (`No. 19`, `68' or 68th minute`, `12.7 km`)."""
    display, unit = fact["display"], fact.get("unit")
    if fact.get("name") == "shirt_number":
        return f"No. {display}"
    if fact.get("name") == "minute" and (minute := display.rstrip("'")).isdigit():
        return f"{display} or {ordinal(int(minute))} minute"
    return f"{display} {unit}" if unit and unit not in display else display


def window(fact_id: str) -> str:
    """The window a fact covers, from the scope part of its id."""
    parts = fact_id.split("/")
    scope = parts[2].split("-")[0] if len(parts) == 4 else ""
    return _WINDOWS.get(scope, scope or "match")


class FatalCallError(Exception):
    """A call no retry can mend: the credentials (401, 403, an expired `az login`) or the request
    itself (400, an unknown deployment). The run stops, rather than ending every remaining moment
    as a stats-only cue."""


class _Requests(ChatMiddleware):
    """Counts the model requests the agent sends, the tool loop's included, and the tokens of
    each that came back: a request answered before a later one failed is billed too."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.count = self.tokens_in = self.tokens_out = 0

    async def process(self, context: ChatContext, call_next) -> None:
        self.count += 1
        await call_next()
        usage = getattr(context.result, "usage_details", None) or {}
        self.tokens_in += int(usage.get("input_token_count") or 0)
        self.tokens_out += int(usage.get("output_token_count") or 0)


class Analyst:
    """Writes one `Attempt` per call of `attempt`, over any AF chat client (Foundry or fake).
    With `facts_tool` the Analyst reads the moment's facts through it; the client's tool loop is
    then capped at one call and `MAX_REQUESTS` model requests per attempt."""

    def __init__(
        self,
        client: SupportsChatGetResponse,
        match: Match,
        *,
        timeout_s: float = CALL_TIMEOUT_S,
        facts_tool: ToolTypes | None = None,
    ) -> None:
        self.match = match
        self.model = getattr(client, "model", None) or type(client).__name__  # what is called
        self.timeout_s = timeout_s
        self.tool = facts_tool is not None
        self.max_requests = MAX_REQUESTS if self.tool else 1
        if self.tool:
            client.function_invocation_configuration.update(
                max_iterations=MAX_REQUESTS, max_function_calls=1
            )
        self._requests = _Requests()
        self.agent = agent(
            client,
            INSTRUCTIONS,
            "analyst",
            tools=[facts_tool] if self.tool else None,
            middleware=[self._requests],
        )

    async def attempt(self, case: MomentCase) -> Attempt:
        """The next attempt on `case`: a draft, or the reason the call brought none. A case that
        takes no further attempt is refused before the (billed) call: ValueError."""
        if case.is_recap:
            raise ValueError("the recap is the Recap Writer's to draft")
        if not case.is_open or len(case.attempts) >= MAX_ATTEMPTS:
            raise ValueError(f"moment {case.moment_id!r} takes no further attempt")
        if case.attempts and case.attempts[-1].verdict is None:
            raise ValueError(f"moment {case.moment_id!r}: the last attempt is not judged yet")
        prompt = moment_prompt(case, self.match, tool=self.tool)
        return await ask(self.agent, self._requests, prompt, len(case.attempts) + 1, self.timeout_s)


def agent(client: SupportsChatGetResponse, instructions: str, name: str, **kwargs) -> Agent:
    """An AF agent that answers with a `Draft` (structured output), as every writer does."""
    return Agent(
        client,
        instructions,
        name=name,
        default_options={
            "max_tokens": MAX_TOKENS,
            "response_format": DRAFT_SCHEMA,
            "output_config": {"effort": EFFORT},
        },
        **kwargs,
    )


async def ask(
    writer: Agent, requests: "_Requests", prompt: str, n: int, timeout_s: float
) -> Attempt:
    """Attempt `n`: one run of `writer` on `prompt`, a draft or the reason the call brought none.
    `requests` (the agent's middleware) counts its model requests and tokens; a `FatalCallError`
    stops the run."""
    requests.reset()
    start = time.perf_counter()
    reply = None
    try:
        async with asyncio.timeout(timeout_s):
            reply = await writer.run(prompt)
    except TimeoutError:
        result = CallFailure(CallError.TIMEOUT, f"no reply within {timeout_s:g} s")
    except ChatClientException as e:
        if (cause := fatal_cause(e)) is not None:
            raise FatalCallError(_short(f"{type(cause).__name__}: {cause}")) from e
        result = call_failure(e)
    except ToolException as e:  # the facts tool failed: its server is gone or too slow
        result = CallFailure(CallError.TRANSPORT, _short(f"the facts tool failed: {e}"))
    else:
        result = read_reply(reply)
    draft = result if isinstance(result, Draft) else None
    model = getattr(writer.client, "model", None) or type(writer.client).__name__
    return Attempt(
        n,
        model,
        draft,
        error=None if draft is not None else result,
        tokens_in=requests.tokens_in,
        tokens_out=requests.tokens_out,
        latency_ms=round((time.perf_counter() - start) * 1000),
        requests=requests.count,
    )


def read_reply(reply: AgentResponse) -> Draft | CallFailure:
    """The draft of a reply, or why it is none: the facts tool failed, a refusal, a cut-off or a
    reply that is no `Draft` (bad JSON, wrong shape). The draft is the last message's text: the
    tool loop's earlier messages (a word before the tool call) are no part of it."""
    for message in reply.messages:
        for c in message.contents:
            if c.type == "function_result" and c.exception is not None:
                detail = f"the facts tool failed: {c.result or c.exception}"
                return CallFailure(CallError.TRANSPORT, _short(detail))
    if reply.finish_reason == "content_filter":  # AF's name for Anthropic's `refusal`
        return CallFailure(CallError.REFUSAL, "the model declined to answer")
    if reply.finish_reason == "length":
        return CallFailure(CallError.INVALID_REPLY, f"the reply was cut off at {MAX_TOKENS} tokens")
    try:
        return Draft.from_dict(json.loads(reply.messages[-1].text if reply.messages else ""))
    except ValueError as e:  # json.JSONDecodeError is one; every check of Draft raises it
        return CallFailure(CallError.INVALID_REPLY, _short(f"no Draft: {e}"))


def call_failure(error: ChatClientException) -> CallFailure:
    """Which `CallError` a failed call is. AF wraps every SDK error in a `ChatClientException`
    (a 429 as an invalid request), so the SDK's own error is read from the `__cause__` chain."""
    cause: BaseException | None = error
    while cause is not None and not isinstance(cause, anthropic.APIError):
        cause = cause.__cause__
    shown = _short(f"{type(cause or error).__name__}: {cause or error}")
    if isinstance(cause, anthropic.APITimeoutError):
        return CallFailure(CallError.TIMEOUT, shown)
    if isinstance(cause, anthropic.RateLimitError):  # the SDK raises it for every 429
        return CallFailure(CallError.RATE_LIMITED, shown)
    return CallFailure(CallError.TRANSPORT, shown)


def fatal_cause(error: ChatClientException) -> BaseException | None:
    """The error in the `__cause__` chain that makes a failed call fatal, or None: an Entra
    token that could not be fetched, or a 4xx answer that is not transient."""
    cause: BaseException | None = error
    while cause is not None:
        if isinstance(cause, ClientAuthenticationError):
            return cause
        if isinstance(cause, anthropic.APIStatusError):
            status = cause.status_code
            return cause if 400 <= status < 500 and status not in RETRIED_STATUSES else None
        cause = cause.__cause__
    return None


def _short(text: str) -> str:
    return text if len(text) <= _MAX_DETAIL else text[: _MAX_DETAIL - 1] + "…"


def foundry_credential() -> AsyncTokenCredential:
    """The app's managed identity where the platform gives it one (Azure Container Apps sets
    `IDENTITY_ENDPOINT`), else the Azure CLI login. Not `DefaultAzureCredential`: its async
    managed identity builds an aiohttp transport (not installed; azure-core's requests transport
    serves instead), and off Azure it asks IMDS first, which cost 24 s before a run's first token
    on the devbox (its metadata service answers 404, retried with backoff)."""
    if os.environ.get(IDENTITY_ENDPOINT_ENV, "").strip():
        return ManagedIdentityCredential(transport=AsyncioRequestsTransport())
    return AzureCliCredential()


def foundry_client(deployment: str | None = None) -> AnthropicFoundryClient:
    """The real Analyst client: Claude on Foundry with an Entra token from `foundry_credential`
    (fetched without blocking the event loop). The resource comes from
    `MATCHLENS_FOUNDRY_RESOURCE`, the deployment from the argument, else
    `MATCHLENS_ANALYST_DEPLOYMENT`, else Haiku. The SDK client is built here because AF's
    constructor sets neither its request timeout nor its retries. Building it makes no call."""
    resource = os.environ.get(FOUNDRY_RESOURCE_ENV, "").strip()
    if not resource:
        raise RuntimeError(f"{FOUNDRY_RESOURCE_ENV} is not set: name the Foundry resource")
    model = deployment or os.environ.get(DEPLOYMENT_ENV, "").strip() or DEFAULT_DEPLOYMENT
    sdk = anthropic.AsyncAnthropicFoundry(
        resource=resource,
        azure_ad_token_provider=get_bearer_token_provider(foundry_credential(), TOKEN_SCOPE),
        timeout=REQUEST_TIMEOUT_S,
        max_retries=MAX_RETRIES,
    )
    return AnthropicFoundryClient(model=model, anthropic_client=sdk)
