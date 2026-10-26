"""A chat client that replays scripted replies: CI and `--fake` runs never reach a model."""

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from agent_framework import (
    BaseChatClient,
    ChatMiddlewareLayer,
    ChatResponse,
    Content,
    FunctionInvocationLayer,
    Message,
)

from matchlens.explain.state import RECAP_ID

Reply = str | ChatResponse | Exception

# lines of `analyst.moment_prompt`, `persona.persona_prompt` and `recap.recap_prompt`
_MOMENT = re.compile(r"^Moment (\S+) at clock ", re.MULTILINE)
_RECAP = re.compile(r"^Recap of match \S+ at clock ", re.MULTILINE)
_PERSONA = re.compile(r"^Persona (\S+) for moment (\S+) at clock ", re.MULTILINE)
_CAPTION = re.compile(r"^Caption JSON: (.+)$", re.MULTILINE)
_TRANSLATION = re.compile(
    r"^Translation into (\S+) of (\S+) for moment (\S+) at clock ", re.MULTILINE
)
_SOURCE = re.compile(r"^Source JSON: (.+)$", re.MULTILINE)
SCORE_SK = ("The score is ", "Skóre je ")  # how the fake Translator renders `echo`'s draft
_EARLIER = re.compile(r"^- Attempt \d+: ", re.MULTILINE)
_TRIGGER = re.compile(r"^- ([a-z0-9]+-e[0-9]{5}): ", re.MULTILINE)
_SCORE = re.compile(r"^- ([^ |]+/score/(?:to-[^ |]+|match/all)) \| ([^|]+?) \| ", re.MULTILINE)
_CALL = re.compile(
    r'^Facts: call the tool (\S+) once, with match_id "([^"]+)", period ([0-9]+) and clock_ms '
    r"([0-9]+),",
    re.MULTILINE,
)
TOOL_RESULT = "[tool result] "  # how a request's text shows a tool's result


class ScriptExhausted(AssertionError):
    """More requests than scripted replies: a broken test, never a failed attempt."""


class FakeChatClient(FunctionInvocationLayer, ChatMiddlewareLayer, BaseChatClient):
    """Answers each request with the next scripted reply: a text, a whole `ChatResponse` (sent as
    it is, e.g. with a finish reason) or an exception, which is raised. The script is a list
    answered in call order, or a function of the request's text (`by_moment`, `echo`).

    It has the function-invocation and chat-middleware layers of the real Foundry client, so tools
    and middleware an agent passes down run as they would there (telemetry is left out).

    `requests` keeps the messages and options of every call, so tests can check what an agent
    sent. Token counts are characters (request text in, reply out), deterministic but no tokens.
    """

    OTEL_PROVIDER_NAME = "matchlens.fake"
    model = "fake"  # what an attempt records as its model

    def __init__(self, replies: Iterable[Reply] | Callable[[str], Reply]) -> None:
        super().__init__()
        self._script = replies if callable(replies) else None
        self._replies = [] if callable(replies) else list(replies)
        self.requests: list[tuple[list[Message], dict[str, Any]]] = []

    async def _inner_get_response(
        self,
        *,
        messages: Sequence[Message],
        stream: bool,
        options: Mapping[str, Any],
        **kwargs: Any,
    ) -> ChatResponse:
        if stream:
            raise NotImplementedError("FakeChatClient does not stream")
        options = await self._validate_options(options)
        self.requests.append((list(messages), dict(options)))
        if self._script is not None:
            reply = self._script(_text(messages))
        elif self._replies:
            reply = self._replies.pop(0)
        else:
            raise ScriptExhausted(f"no scripted reply left for request {len(self.requests)}")
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, ChatResponse):
            return reply
        sent = sum(len(m.text or "") for m in messages) + len(options.get("instructions") or "")
        return ChatResponse(
            messages=[Message(role="assistant", contents=[reply])],
            response_id=f"fake-{len(self.requests)}",
            model="fake",
            usage_details={"input_token_count": sent, "output_token_count": len(reply)},
        )


def by_moment(
    script: Mapping[str, Sequence[Reply | Callable[[str], Reply]]],
) -> Callable[[str], Reply]:
    """Replies keyed by moment id (a recap's is `RECAP_ID`), a rendition's by
    `<moment id>/<persona>` and a translation's by `<moment id>/<persona>/<lang>`: the n-th attempt
    on a moment (or a rendition, a translation) gets its n-th reply, whatever order the workflow
    calls in; a reply may be a function of the prompt (`echo`). The prompt names the moment (and
    persona, language) and lists its earlier attempts."""

    def reply(prompt: str) -> Reply:
        if (translation := _TRANSLATION.search(prompt)) is not None:
            lang, persona, moment_id = translation.groups()
            key = f"{moment_id}/{persona}/{lang}"
        elif (persona := _PERSONA.search(prompt)) is not None:
            key = f"{persona.group(2)}/{persona.group(1)}"
        elif (moment := _MOMENT.search(prompt)) is not None:
            key = moment.group(1)
        elif _RECAP.search(prompt) is not None:
            key = RECAP_ID
        else:
            raise ScriptExhausted("a request that names no moment")
        replies = script.get(key, ())
        n = len(_EARLIER.findall(prompt))
        if n >= len(replies):
            raise ScriptExhausted(f"no scripted reply {n + 1} for moment {key}")
        return replies[n](prompt) if callable(replies[n]) else replies[n]

    return reply


def _text(messages: Sequence[Message]) -> str:
    """A request as one text: the messages' text, and each tool result on a line of its own."""
    lines = []
    for m in messages:
        lines.append(m.text or "")
        lines += [TOOL_RESULT + str(c.result) for c in m.contents if c.type == "function_result"]
    return "\n".join(lines)


def echo(prompt: str) -> Reply:
    """The `--fake` Analyst and Recap Writer: one claim, the score so far as the prompt says to
    write it, citing the score fact and the first trigger event. It copies, it computes
    nothing. When the prompt says to read the facts with a tool, it first calls the tool, then
    reads the score from the tool's result. As the `--fake` Persona Editor it copies the
    caption it was given; as the `--fake` Translator the text it was given, its own sentence in
    Slovak (`SCORE_SK`), anything else as it is."""
    if _TRANSLATION.search(prompt) is not None:
        source = _SOURCE.search(prompt)
        if source is None:
            raise ScriptExhausted("a translation prompt without the source")
        return source.group(1).replace(*SCORE_SK)
    if _PERSONA.search(prompt) is not None:
        caption = _CAPTION.search(prompt)
        if caption is None:
            raise ScriptExhausted("a persona prompt without the caption")
        return caption.group(1)
    trigger, call = _TRIGGER.search(prompt), _CALL.search(prompt)
    if trigger is not None and (score := _SCORE.search(prompt)) is not None:
        return _score_draft(score.group(1), score.group(2), trigger.group(1))
    if trigger is None or call is None:
        raise ScriptExhausted("a prompt without a score fact or a trigger event")
    results = [line for line in prompt.splitlines() if line.startswith(TOOL_RESULT)]
    if not results:
        name, match_id, period, clock_ms = call.groups()
        args = {"match_id": match_id, "period": int(period), "clock_ms": int(clock_ms)}
        content = Content.from_function_call(call_id="echo-1", name=name, arguments=args)
        return ChatResponse(
            messages=[Message(role="assistant", contents=[content])], finish_reason="tool_calls"
        )
    try:
        facts = json.loads(results[-1].removeprefix(TOOL_RESULT))["result"]
    except (ValueError, KeyError, TypeError):  # the tool failed: no facts to copy
        return "no facts: the tool failed"
    score = next(f for f in facts if f["name"] == "score" and "/to-" in f["fact_id"])
    return _score_draft(score["fact_id"], score["display"], trigger.group(1))


def _score_draft(fact_id: str, display: str, event_id: str) -> str:
    text = f"The score is {display}."
    claim = {"text": text, "fact_ids": [fact_id], "event_ids": [event_id], "frame_ids": []}
    return json.dumps({"text": text, "claims": [claim]})
