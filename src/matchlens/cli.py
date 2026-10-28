"""Command line: `matchlens generate` writes a match as JSON, `matchlens cues` its overlay cues,
`matchlens serve` streams matches, `matchlens mcp` serves their facts to agents, `matchlens
explain` runs the agents on a match, `matchlens recap` adds the recap at full time to a run,
`matchlens translate` adds the translations of its texts.

    matchlens generate --seed 7 [--home cor --away vel] [--out match.json]
    matchlens cues --seed 7 [--run DIR] [--out cues.json]
    matchlens serve --seed 7 --seed 8 [--run DIR ...] [--host 127.0.0.1] [--port 8000]
    matchlens mcp --seed 7 [--http [--host 127.0.0.1] [--port 8001]]
    matchlens explain m7 [--until 45:00] [--fake | --deployment claude-sonnet-5-5]
        [--mcp http://127.0.0.1:8001/mcp] [--max-calls N] [--pace 35] [--persona fan ...]
        [--runs runs]
    matchlens recap m7 --run DIR [--fake | --deployment claude-sonnet-5-5] [--max-calls N]
        [--pace 35] [--persona fan ...]
    matchlens translate m7 --run DIR --lang sk [--fake | --deployment claude-sonnet-5-5]
        [--max-calls N] [--pace 35]

Exit codes: 0 done, 1 the output could not be written or a run stopped (an Analyst call no retry
mends, the facts' MCP server unavailable), 2 bad arguments (with the usage), 143 `serve` stopped
by SIGTERM (after closing its open streams once it listens).
Anything else, such as a generated match failing validation, is a bug and shows a traceback.
"""

import argparse
import asyncio
import json
import os
import re
import signal
import sys
import tempfile
import threading
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from matchlens.events import display_clock
from matchlens.explain.state import DEFAULT_MAX_CALLS, Lang, Persona
from matchlens.generator_v2 import generate_match_v2
from matchlens.league import load_league
from matchlens.match import Match

PERSONAS = [p.value for p in Persona]

DEFAULT_SEEDS = (1, 2, 3)
# below Azure Container Apps' default termination grace period (30 s from SIGTERM to SIGKILL),
# so uvicorn closes the open streams itself and clients resume through Last-Event-ID. The other
# 10 s cover the rest of the exit: the lifespan's shutdown cancels the queued cue timelines and
# leaves a running one to its daemon thread, so nothing else waits (measured in `container.sh`)
GRACEFUL_TIMEOUT_S = 20
RUN_HELP = (
    "a run directory of `matchlens explain`: its narratives (and its recap) that pass the Guard"
)
RECAP_LOG, RECAP_SUMMARY = "recap.jsonl", "recap.json"  # what `matchlens recap` adds to a run


def translation_files(lang: str) -> tuple[str, str]:
    """The log and the summary `matchlens translate` adds to a run for `lang`."""
    return f"translate.{lang}.jsonl", f"translate.{lang}.json"


def match_document(match: Match) -> dict:
    """The JSON form of a match: metadata and events (tracking stays in `Match.frames()`)."""
    return {"meta": match.meta.to_dict(), "events": [e.to_dict() for e in match.events]}


# argparse names a type function in its "invalid <name> value" message, hence these names
def seed(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"seed must not be negative: {value}")
    return value


def port(text: str) -> int:
    value = int(text)
    if not 0 <= value <= 65535:
        raise argparse.ArgumentTypeError(f"port must be in 0-65535: {value}")
    return value


def seconds(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"seconds must not be negative: {value}")
    return value


def calls(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"calls must not be negative: {value}")
    return value


def match_id(text: str) -> int:
    """`m7` → 7: a match id names the seed the generator makes the match from."""
    if (found := re.fullmatch(r"m(0|[1-9][0-9]*)", text)) is None:
        raise argparse.ArgumentTypeError(f"a match id is m<seed>, such as m7: {text!r}")
    return seed(found.group(1))


def clock(text: str) -> tuple[int, int]:
    """A broadcast clock as `display_clock` writes it, read back as (period, clock_ms): `67:23`
    is the second half, `45:00` its kick-off, `45+2:13` the first half's stoppage time."""
    found = re.fullmatch(r"([0-9]{2})(?:\+([0-9]+))?:([0-5][0-9])", text)
    if found is not None:
        minutes, extra, secs = int(found.group(1)), found.group(2), int(found.group(3))
        if extra is None:
            period, minutes = (1, minutes) if minutes < 45 else (2, minutes - 45)
        else:
            period, minutes = minutes // 45, 45 + int(extra)
        clock_ms = (minutes * 60 + secs) * 1000
        try:
            if period in (1, 2) and display_clock(period, clock_ms) == text:
                return period, clock_ms
        except ValueError:  # past the longest period
            pass
    raise argparse.ArgumentTypeError(f"a broadcast clock such as 67:23 or 45+2:13: {text!r}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="matchlens",
        description="Generate synthetic football matches, stream them as live events and "
        "explain their key moments.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    gen = commands.add_parser("generate", help="generate one match and write it as JSON")
    gen.add_argument("--seed", type=seed, required=True)
    gen.add_argument("--home", help="home club id (default: drawn from the seed)")
    gen.add_argument("--away", help="away club id (default: drawn from the seed)")
    gen.add_argument("--out", type=Path, help="file to write (default: standard output)")
    gen.set_defaults(run=_generate, error=gen.error)

    cues = commands.add_parser("cues", help="write the overlay cues of one match as JSON")
    cues.add_argument("--seed", type=seed, required=True)
    cues.add_argument("--out", type=Path, help="file to write (default: standard output)")
    cues.add_argument("--run", type=Path, dest="run_dir", help=RUN_HELP)
    cues.set_defaults(run=_cues, error=cues.error)

    serve = commands.add_parser("serve", help="serve generated matches over HTTP and SSE")
    serve.add_argument(
        "--seed",
        type=seed,
        action="append",
        dest="seeds",
        help=f"seed of a match to serve; repeat for more (default: {DEFAULT_SEEDS})",
    )
    serve.add_argument("--run", type=Path, action="append", dest="runs", help=RUN_HELP)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=port, default=8000)
    serve.add_argument(
        "--graceful-timeout",
        type=seconds,
        default=GRACEFUL_TIMEOUT_S,
        help="seconds open streams get on shutdown before they are closed",
    )
    serve.set_defaults(run=_serve, error=serve.error)

    mcp = commands.add_parser("mcp", help="serve the facts of generated matches over MCP")
    mcp.add_argument(
        "--seed",
        type=seed,
        action="append",
        dest="seeds",
        help=f"seed of a match to serve; repeat for more (default: {DEFAULT_SEEDS})",
    )
    mcp.add_argument("--http", action="store_true", help="streamable HTTP instead of stdio")
    mcp.add_argument("--host", help="with --http (default: 127.0.0.1)")
    mcp.add_argument("--port", type=port, help="with --http (default: 8001)")
    mcp.set_defaults(run=_mcp, error=mcp.error)

    exp = commands.add_parser("explain", help="explain a match's key moments with the agents")
    exp.add_argument("match", type=match_id, help="match id, m<seed>: m7")
    exp.add_argument(
        "--until", type=clock, help="only moments that end by this clock (45:00: the first half)"
    )
    exp.add_argument("--fake", action="store_true", help="a scripted Analyst, no model call")
    exp.add_argument("--deployment", help="Foundry deployment (default: as `foundry_client`)")
    exp.add_argument(
        "--max-calls",
        type=calls,
        help=f"model requests per run, two per attempt with --mcp (required for a model; "
        f"{DEFAULT_MAX_CALLS} with --fake)",
    )
    exp.add_argument(
        "--pace",
        type=seconds,
        default=0,
        help="seconds between the starts of two model attempts, to stay under the deployment's "
        "tokens per minute (0)",
    )
    exp.add_argument(
        "--mcp",
        metavar="URL",
        help="the Analyst reads the facts from this `matchlens mcp --http` server",
    )
    exp.add_argument(
        "--persona",
        action="append",
        choices=PERSONAS,
        dest="personas",
        help="a persona every narrative is rewritten for by the Persona Editor; repeat for more",
    )
    exp.add_argument("--runs", type=Path, default=Path("runs"), help="where runs go (runs)")
    exp.set_defaults(run=_explain, error=exp.error)

    rec = commands.add_parser("recap", help="write a match's recap at full time with the agents")
    rec.add_argument("match", type=match_id, help="match id, m<seed>: m7")
    rec.add_argument(
        "--run",
        type=Path,
        required=True,
        dest="run_dir",
        help="a run directory of `matchlens explain` of the match: the recap's log and summary "
        f"go into it ({RECAP_LOG}, {RECAP_SUMMARY})",
    )
    rec.add_argument("--fake", action="store_true", help="a scripted Recap Writer, no model call")
    rec.add_argument("--deployment", help="Foundry deployment (default: as `foundry_client`)")
    rec.add_argument(
        "--max-calls",
        type=calls,
        help=f"model requests of the recap and its renditions (required for a model; "
        f"{DEFAULT_MAX_CALLS} with --fake)",
    )
    rec.add_argument(
        "--pace", type=seconds, default=0, help="seconds between two model attempts (0)"
    )
    rec.add_argument(
        "--persona",
        action="append",
        choices=PERSONAS,
        dest="personas",
        help="a persona the recap is rewritten for by the Persona Editor; repeat for more",
    )
    rec.set_defaults(run=_recap, error=rec.error)

    tra = commands.add_parser(
        "translate", help="translate a run's narratives, renditions and recap with the agents"
    )
    tra.add_argument("match", type=match_id, help="match id, m<seed>: m7")
    tra.add_argument(
        "--run",
        type=Path,
        required=True,
        dest="run_dir",
        help="a run directory of `matchlens explain` of the match, after `matchlens recap` if it "
        "is to have one (a recap written later stays in English): the translations' log and "
        "summary go into it (translate.<lang>.jsonl, .json)",
    )
    tra.add_argument("--lang", required=True, choices=[lang.value for lang in Lang])
    tra.add_argument("--fake", action="store_true", help="a scripted Translator, no model call")
    tra.add_argument("--deployment", help="Foundry deployment (default: as `foundry_client`)")
    tra.add_argument(
        "--max-calls",
        type=calls,
        help=f"model requests of the translations (required for a model; {DEFAULT_MAX_CALLS} "
        "with --fake)",
    )
    tra.add_argument(
        "--pace", type=seconds, default=0, help="seconds between two model attempts (0)"
    )
    tra.set_defaults(run=_translate, error=tra.error)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a subcommand; bad arguments exit 2 with the subcommand's usage, like argparse."""
    args = _parser().parse_args(argv)
    return args.run(args)


def _generate(args: argparse.Namespace) -> int:
    clubs = sorted(c.id for c in load_league().clubs)
    for side in ("home", "away"):
        club = getattr(args, side)
        if club is not None and club not in clubs:
            args.error(f"unknown {side} club {club!r}; choose from {', '.join(clubs)}")
    if args.home is not None and args.home == args.away:
        args.error(f"home and away are both {args.home}")
    match = generate_match_v2(args.seed, home=args.home, away=args.away)
    text = json.dumps(match_document(match), separators=(",", ":")) + "\n"
    if not _write(args.out, text, "generate"):
        return 1
    home_goals, away_goals = match.score()
    print(
        f"{match.meta.match_id}: {match.meta.home} {home_goals}-{away_goals} {match.meta.away}, "
        f"{len(match.events)} events",
        file=sys.stderr,
    )
    return 0


def _runs(args: argparse.Namespace, dirs: Sequence[Path]) -> dict[str, list]:
    """The handoffs of each run directory (`matchlens explain`, and its recap's and translations'
    if it has them), by match id; one run a match."""
    from matchlens.explain.log import read_handoffs

    runs: dict[str, list] = {}
    for run in dirs:
        try:
            handoffs = read_handoffs(run / "handoffs.jsonl")
            for added in (RECAP_LOG, *(translation_files(lang)[0] for lang in Lang)):
                if (run / added).exists():
                    handoffs += read_handoffs(run / added)
        except OSError as e:
            args.error(f"cannot read the run {run}: {e.strerror}")
        except ValueError as e:
            args.error(f"the run {run} has a bad handoff log: {e}")
        for match_id in dict.fromkeys(h.case.match_id for h in handoffs):
            if match_id in runs:
                args.error(f"two runs of {match_id}")
            runs[match_id] = [h for h in handoffs if h.case.match_id == match_id]
    return runs


def _replay(args: argparse.Namespace, match, handoffs: Sequence):
    """Every cue of `match` with its run's narratives and recap, checked before anything is
    served: a run that does not fit the match (another generator or engine) is a usage error.
    Says on stderr how many logged narratives show and how many the Guard refuses now, the same
    of the fan's own renditions and of the translations if the run has any, and whether a recap
    the run wrote shows."""
    from matchlens.explain.log import Role
    from matchlens.explain.state import Persona
    from matchlens.render.moments import FAN_VIEW, NARRATIVE, match_overlay
    from matchlens.render.recap import FAN_RECAP, WRITTEN, closed_cases

    try:
        overlay = match_overlay(match, handoffs)
    except ValueError as e:
        args.error(f"the run of {match.meta.match_id} does not fit the match: {e}")
    cues = [c for c in overlay.cues if c.kind == "moment"]
    if handoffs:
        every = closed_cases(handoffs)
        closed = [c for c in every.values() if not c.is_recap]
        logged = sum(c.narrative is not None for c in closed)
        shown = sum(c.lines[0].startswith(f"{NARRATIVE} · ") for c in cues)
        print(
            f"{match.meta.match_id}: {shown} narratives from the run, "
            f"{logged - shown} refused at replay",
            file=sys.stderr,
        )
        fan = Persona.FAN
        if own := sum(
            r.persona is fan and r.draft is not None for c in closed for r in c.renditions
        ):
            shown = sum(c.rendition(fan).lines[0].startswith(f"{FAN_VIEW} · ") for c in cues)
            print(
                f"{match.meta.match_id}: {shown} fan renditions from the run, "
                f"{own - shown} refused at replay",
                file=sys.stderr,
            )
        mid = match.meta.match_id
        _translations_line(mid, list(every.values()), cues, overlay.recap)
        recaps = [h for h in handoffs if h.case.is_recap]
        logged = [h.case for h in recaps if h.receiver is Role.RENDER]
        if recaps and not logged:
            print(f"{mid}: the run's recap never left the Guard", file=sys.stderr)
        if logged and logged[0].narrative is not None:
            shown = overlay.recap.texts["analyst"][0] == WRITTEN
            refused = "" if shown else ", refused at replay"
            print(f"{mid}: the recap from the run{refused}", file=sys.stderr)
            if any(r.draft is not None for r in logged[0].renditions):
                shown = overlay.recap.texts[fan.value][0] == FAN_RECAP
                refused = "" if shown else ", refused at replay"
                print(f"{mid}: the fan recap from the run{refused}", file=sys.stderr)
    return overlay


def _translations_line(mid: str, logged: Sequence, cues: Sequence, recap) -> None:
    """On stderr, per language the run has translations in: how many of its moments'
    translations that passed show and how many the Guard refuses now, and how many texts of the
    recap are the run's translations. `logged`: the run's closed cases, the recap's too."""
    from matchlens.explain.state import ANALYST
    from matchlens.render import moments
    from matchlens.render import recap as recaps

    by_id = {c.cue_id.rpartition("/")[2]: c for c in cues}
    for lang in Lang:
        labels = moments.LABELS[lang]
        heads = {ANALYST: labels[moments.NARRATIVE], Persona.FAN.value: labels[moments.FAN_VIEW]}
        if not any(t.lang == lang for c in logged for t in c.translations):
            continue
        closed = [c for c in logged if not c.is_recap]
        passed = [(c, t) for c in closed for t in c.translations if t.lang == lang and t.draft]
        shown = sum(
            by_id[c.moment_id]
            .translated(t.persona, lang)
            .lines[0]
            .startswith(f"{heads[t.persona]} ·")
            for c, t in passed
        )
        line = f"{mid}: {shown} {lang} translations from the run, {len(passed) - shown} refused"
        texts = recap.translations.get(lang.value, {}) if recap else {}
        written = (recaps.LABELS[lang][recaps.WRITTEN], recaps.LABELS[lang][recaps.FAN_RECAP])
        on_recap = sum(label in written for label, _ in texts.values())
        print(f"{line} at replay; {on_recap} on the recap", file=sys.stderr)


def _cues(args: argparse.Namespace) -> int:
    match = generate_match_v2(args.seed)
    runs = _runs(args, [args.run_dir] if args.run_dir else [])
    if others := sorted(runs.keys() - {match.meta.match_id}):
        args.error(f"the run is of {', '.join(others)}, not {match.meta.match_id}")
    timeline = _replay(args, match, runs.get(match.meta.match_id, ())).cues
    document = {"match_id": match.meta.match_id, "cues": [c.to_dict() for c in timeline]}
    if not _write(args.out, json.dumps(document, separators=(",", ":")) + "\n", "cues"):
        return 1
    kinds = Counter(c.kind.value for c in timeline)
    print(
        f"{match.meta.match_id}: {len(timeline)} cues ("
        + ", ".join(f"{kind} {n}" for kind, n in sorted(kinds.items()))
        + ")",
        file=sys.stderr,
    )
    return 0


def _write(path: Path | None, text: str, command: str) -> bool:
    """`text` to `path`, or to standard output without one; False (with a message) if it could
    not be written."""
    if path is None:
        return _write_stdout(text)
    try:
        _write_atomically(path, text)
    except OSError as e:
        print(f"matchlens {command}: cannot write {path}: {e.strerror}", file=sys.stderr)
        return False
    return True


def _write_stdout(text: str) -> bool:
    """False if the reader went away (e.g. `| head`); stdout is then quietly dropped."""
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except BrokenPipeError:
        # the Python docs' recipe: point stdout at devnull so the exit flush cannot fail again
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return False
    return True


def _write_atomically(path: Path, text: str) -> None:
    """Either the whole file or the old one: write a sibling temp file, then rename it."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(tmp, 0o666 & ~umask)  # mkstemp makes 0600; give the file the usual mode
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _stop(signum: int, _frame: object) -> None:
    raise SystemExit(128 + signum)


def _serve(args: argparse.Namespace) -> int:
    # Python as PID 1 in a container ignores SIGTERM until uvicorn installs its handler, so a stop
    # during the cold start (imports, match generation, the runs' check) waited for SIGKILL.
    # uvicorn puts this handler back after its graceful shutdown and raises the signal again: 143
    # either way. Only the interpreter's start and this module's imports stay unhandled. Signal
    # handlers exist in the main thread only, as uvicorn's
    main = threading.current_thread() is threading.main_thread()
    previous = signal.signal(signal.SIGTERM, _stop) if main else None
    try:
        import uvicorn  # only the server needs it

        from matchlens.api import LiveLimits, create_app

        seeds = _seeds(args)
        runs = _runs(args, args.runs or [])
        matches = [generate_match_v2(s) for s in seeds]
        if others := sorted(runs.keys() - {m.meta.match_id for m in matches}):
            args.error(f"runs of matches not served: {', '.join(others)}")
        overlays = {
            mid: _replay(args, m, runs[mid]) for m in matches if (mid := m.meta.match_id) in runs
        }
        # overlays computed once, before the server listens; limits: it is public (issue #2)
        app = create_app(matches, overlays=overlays, limits=LiveLimits())
        ids = ", ".join(f"m{s}" for s in seeds)
        print(f"serving {ids} on http://{args.host}:{args.port}", file=sys.stderr)
        uvicorn.run(
            app, host=args.host, port=args.port, timeout_graceful_shutdown=args.graceful_timeout
        )
    finally:
        if previous is not None:  # None: not set from Python, nothing to put back
            signal.signal(signal.SIGTERM, previous)
    return 0


def _mcp(args: argparse.Namespace) -> int:
    from matchlens.mcp import create_server  # only this command needs the MCP SDK

    seeds = _seeds(args)
    if not args.http and (args.host is not None or args.port is not None):
        args.error("--host and --port need --http")
    host = "127.0.0.1" if args.host is None else args.host
    port = 8001 if args.port is None else args.port
    server = create_server((generate_match_v2(s) for s in seeds), host=host, port=port)
    where = f"http://{host}:{port}/mcp" if args.http else "stdio"
    # stdout carries the protocol over stdio, so the banner goes to stderr
    print(f"facts of {', '.join(f'm{s}' for s in seeds)} over MCP on {where}", file=sys.stderr)
    server.run("streamable-http" if args.http else "stdio")
    return 0


def _explain(args: argparse.Namespace) -> int:
    # the agents need Agent Framework, a slow import that only this command pays for
    from matchlens.explain.analyst import FatalCallError, foundry_client
    from matchlens.explain.fake import FakeChatClient, echo
    from matchlens.explain.log import HandoffLog, read_handoffs
    from matchlens.explain.summary import summarize
    from matchlens.explain.workflow import FactsUnavailable, explain

    if args.fake and args.deployment is not None:
        args.error("--deployment names a real model; --fake calls none")
    if args.max_calls is None:
        if not args.fake:  # a billed run names its cap
            args.error("a run that calls a model needs --max-calls")
        args.max_calls = DEFAULT_MAX_CALLS
    try:
        client = FakeChatClient(echo) if args.fake else foundry_client(args.deployment)
    except RuntimeError as e:
        args.error(str(e))
    match = generate_match_v2(args.match)
    now = datetime.now(UTC)
    run_id = f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z"  # UTC, to the millisecond
    run_dir = args.runs / match.meta.match_id / run_id
    try:
        run_dir.mkdir(parents=True)
    except OSError as e:
        print(f"matchlens explain: cannot create {run_dir}: {e.strerror}", file=sys.stderr)
        return 1
    log = HandoffLog(run_dir / "handoffs.jsonl")
    stopped, explained = None, []
    try:
        run = explain(
            match,
            client,
            log,
            run_id=run_id,
            until=args.until,
            max_calls=args.max_calls,
            facts_url=args.mcp,
            pace_s=args.pace,
            personas=tuple(args.personas or ()),
        )
        explained = asyncio.run(run)
    except (FatalCallError, FactsUnavailable) as e:
        stopped = str(e)
    summary = summarize(read_handoffs(log.path) if log.path.exists() else [], stopped)
    settings = {
        "max_calls": args.max_calls,
        "pace_s": args.pace,
        "mcp": args.mcp,
        "personas": list(dict.fromkeys(args.personas or ())),
    }
    document = summary.to_dict() | {"settings": settings}  # how the run was made
    _write_atomically(run_dir / "summary.json", json.dumps(document, indent=1) + "\n")
    for e in explained:
        tries = len(e.case.attempts)
        print(f"{e.case.moment_id} {e.case.display_clock} {e.case.outcome} ({tries}): {e.cue.text}")
        for r in e.case.renditions:
            text = e.for_persona(r.persona).text
            print(f"  {r.persona} {r.outcome} ({len(r.attempts)}): {text}")
    print(_summary_line(summary))
    for persona, p in summary.personas.items():
        print(_persona_line(persona, p))
    if summary.personas:
        total = "unknown" if summary.total_cost_usd is None else f"${summary.total_cost_usd:.4f}"
        print(
            f"all agents: {summary.total_requests} requests, tokens {summary.total_tokens_in} in "
            f"/ {summary.total_tokens_out} out, {total}"
        )
    print(f"log and summary: {run_dir}", file=sys.stderr)
    if summary.skipped:
        print(
            f"matchlens explain: {summary.skipped} attempts made no call (circuit breaker or "
            "--max-calls): their moments are stats-only and count in the pass rates",
            file=sys.stderr,
        )
    for persona, p in summary.personas.items():
        if p["skipped"]:
            print(
                f"matchlens explain: {p['skipped']} {persona} attempts made no call (circuit "
                "breaker or --max-calls): their renditions fall back to the narrative",
                file=sys.stderr,
            )
    if stopped is not None:
        print(f"matchlens explain: run stopped: {stopped}", file=sys.stderr)
        return 1
    if summary.crashed:  # a moment that never left the Guard, with no error to say why
        print(f"matchlens explain: moments without a cue: {summary.crashed}", file=sys.stderr)
        return 1
    return 0


def _recap(args: argparse.Namespace) -> int:
    # the agents need Agent Framework, a slow import that only `explain` and `recap` pay for
    from matchlens.explain.analyst import FatalCallError, foundry_client
    from matchlens.explain.fake import FakeChatClient, echo
    from matchlens.explain.log import HandoffLog, Role, read_handoffs
    from matchlens.explain.recap import write_recap
    from matchlens.explain.summary import summarize

    if args.fake and args.deployment is not None:
        args.error("--deployment names a real model; --fake calls none")
    if args.max_calls is None:
        if not args.fake:  # a billed run names its cap
            args.error("a recap that calls a model needs --max-calls")
        args.max_calls = DEFAULT_MAX_CALLS
    match = generate_match_v2(args.match)
    mid = match.meta.match_id
    try:
        handoffs = read_handoffs(args.run_dir / "handoffs.jsonl")
    except OSError as e:
        args.error(f"cannot read the run {args.run_dir}: {e.strerror}")
    except ValueError as e:
        args.error(f"the run {args.run_dir} has a bad handoff log: {e}")
    if not handoffs:
        args.error(f"the run {args.run_dir} has no handoffs")
    runs = {(h.case.run_id, h.case.match_id) for h in handoffs}
    if len(runs) != 1 or next(iter(runs))[1] != mid:
        args.error(f"the run {args.run_dir} is no run of {mid}: {sorted(runs)}")
    log = HandoffLog(args.run_dir / RECAP_LOG)
    if log.path.exists():
        args.error(f"the run {args.run_dir} has a recap already ({RECAP_LOG})")
    try:
        client = FakeChatClient(echo) if args.fake else foundry_client(args.deployment)
    except RuntimeError as e:
        args.error(str(e))
    narratives = [h.case for h in handoffs if h.receiver is Role.RENDER]
    stopped, recap = None, None
    try:  # any error: the log is set aside below, or re-raised after that
        run = write_recap(
            match,
            client,
            log,
            run_id=next(iter(runs))[0],
            narratives=narratives,
            max_calls=args.max_calls,
            pace_s=args.pace,
            personas=tuple(args.personas or ()),
        )
        recap = asyncio.run(run)
    except FatalCallError as e:
        stopped = str(e)
    except BaseException:  # a bug or an interrupt: out of the way of the next try, then raised
        _set_aside(log.path)
        raise
    summary = summarize(read_handoffs(log.path) if log.path.exists() else [], stopped)
    settings = {
        "max_calls": args.max_calls,
        "pace_s": args.pace,
        "personas": list(dict.fromkeys(args.personas or ())),
    }
    document = summary.to_dict() | {"settings": settings}
    _write_atomically(args.run_dir / RECAP_SUMMARY, json.dumps(document, indent=1) + "\n")
    if recap is not None:
        tries = len(recap.case.attempts)
        print(f"recap {recap.case.display_clock} {recap.case.outcome} ({tries}): {recap.cue.text}")
        for r in recap.case.renditions:
            text = recap.for_persona(r.persona).text
            print(f"  {r.persona} {r.outcome} ({len(r.attempts)}): {text}")
    print(_recap_line(summary))
    for persona, p in summary.personas.items():
        print(_persona_line(persona, p))
    if stopped is None and not summary.crashed:
        print(f"log and summary: {log.path}, {args.run_dir / RECAP_SUMMARY}", file=sys.stderr)
        return 0
    kept = _set_aside(log.path)
    why = f"stopped: {stopped}" if stopped is not None else "the recap never left the Guard"
    print(f"matchlens recap: {why}; log and summary: {kept}, {RECAP_SUMMARY}", file=sys.stderr)
    return 1


def _translate(args: argparse.Namespace) -> int:
    # the agents need Agent Framework, a slow import that only the agents' commands pay for
    from matchlens.explain.analyst import FatalCallError, foundry_client
    from matchlens.explain.fake import FakeChatClient, echo
    from matchlens.explain.log import HandoffLog, Role, read_handoffs
    from matchlens.explain.summary import summarize
    from matchlens.explain.translator import translate

    if args.fake and args.deployment is not None:
        args.error("--deployment names a real model; --fake calls none")
    if args.max_calls is None:
        if not args.fake:  # a billed run names its cap
            args.error("a translation that calls a model needs --max-calls")
        args.max_calls = DEFAULT_MAX_CALLS
    match = generate_match_v2(args.match)
    mid = match.meta.match_id
    log_name, summary_name = translation_files(args.lang)
    try:
        handoffs = read_handoffs(args.run_dir / "handoffs.jsonl")
        if (args.run_dir / RECAP_LOG).exists():
            handoffs += read_handoffs(args.run_dir / RECAP_LOG)
    except OSError as e:
        args.error(f"cannot read the run {args.run_dir}: {e.strerror}")
    except ValueError as e:
        args.error(f"the run {args.run_dir} has a bad handoff log: {e}")
    runs = {(h.case.run_id, h.case.match_id) for h in handoffs}
    if len(runs) != 1 or next(iter(runs))[1] != mid:
        args.error(f"the run {args.run_dir} is no run of {mid}: {sorted(runs)}")
    log = HandoffLog(args.run_dir / log_name)
    if log.path.exists():
        args.error(f"the run {args.run_dir} has its {args.lang} translations already ({log_name})")
    try:
        client = FakeChatClient(echo) if args.fake else foundry_client(args.deployment)
    except RuntimeError as e:
        args.error(str(e))
    closed = [h.case for h in handoffs if h.receiver is Role.RENDER]
    stopped, translated = None, []
    try:  # any error: the log is set aside below, or re-raised after that
        run = translate(
            match,
            client,
            log,
            closed,
            langs=(args.lang,),
            max_calls=args.max_calls,
            pace_s=args.pace,
        )
        translated = asyncio.run(run)
    except FatalCallError as e:
        stopped = str(e)
    except BaseException:  # a bug or an interrupt: out of the way of the next try, then raised
        _set_aside(log.path)
        raise
    summary = summarize(read_handoffs(log.path) if log.path.exists() else [], stopped)
    settings = {"max_calls": args.max_calls, "pace_s": args.pace, "lang": args.lang}
    document = summary.to_dict() | {"settings": settings}
    _write_atomically(args.run_dir / summary_name, json.dumps(document, indent=1) + "\n")
    for e in translated:
        print(f"{e.case.moment_id} {e.case.display_clock}")
        for t in e.case.translations:
            text = (t.draft or e.case.source(t)).text
            print(f"  {t.lang}/{t.persona} {t.outcome} ({len(t.attempts)}): {text}")
    for key, t in summary.translations.items():
        print(_persona_line(key, t, "translations", "the English text"))
    if stopped is None and not summary.crashed:
        written = f"{log.path}, " if log.path.exists() else "no log (no narrative to translate), "
        print(f"log and summary: {written}{args.run_dir / summary_name}", file=sys.stderr)
        return 0
    kept = _set_aside(log.path)
    why = (
        f"stopped: {stopped}" if stopped is not None else f"cases without a cue: {summary.crashed}"
    )
    print(f"matchlens translate: {why}; log and summary: {kept}, {summary_name}", file=sys.stderr)
    return 1


def _summary_line(s) -> str:
    def rate(r: float | None) -> str:
        return "-" if r is None else f"{r:.0%}"

    cost = "unknown" if s.cost_usd is None else f"${s.cost_usd:.4f}"
    return (
        f"{s.moments} moments: {s.narratives} narratives, {s.stats_only} stats-only, "
        f"{len(s.crashed)} crashed; pass rate {rate(s.first_attempt_pass_rate)} first attempt, "
        f"{rate(s.final_pass_rate)} final; {s.attempts} attempts, {s.model_calls} model calls "
        f"({s.model_requests} requests), "
        f"{s.skipped} skipped; tokens {s.tokens_in} in / {s.tokens_out} out, {cost}; latency "
        f"p50 {s.latency_ms_p50} ms, p95 {s.latency_ms_p95} ms"
    )


def _set_aside(log: Path) -> Path:
    """A stopped recap's (or translation run's) log, kept under its own name so that a new try
    may run: `recap.stopped.<UTC time>.jsonl`."""
    if not log.exists():
        return log
    now = datetime.now(UTC)
    kept = log.with_name(f"{log.stem}.stopped.{now:%Y%m%dT%H%M%S}{now.microsecond:06d}Z.jsonl")
    log.replace(kept)
    return kept


def _recap_line(s) -> str:
    cost = "unknown" if s.cost_usd is None else f"${s.cost_usd:.4f}"
    by = "by the Recap Writer" if s.narratives else "the facts only (no draft passed)"
    if not s.moments:
        by = "none (the run stopped)"
    return (
        f"recap: {by}; {s.attempts} attempts, {s.model_requests} requests, {s.skipped} skipped; "
        f"tokens {s.tokens_in} in / {s.tokens_out} out, {cost}; latency {s.latency_ms_p50} ms"
    )


def _persona_line(
    persona: str, p: dict, noun: str = "renditions", stand_in: str = "the narrative"
) -> str:
    cost = "unknown" if p["cost_usd"] is None else f"${p['cost_usd']:.4f}"
    return (
        f"{persona}: {p[noun]} {noun}: {p['passed']} passed, {p['fallback']} "
        f"fallback to {stand_in}, {p['open']} open; {p['first_attempt_passed']} passed at the "
        f"first attempt; {p['attempts']} attempts, {p['model_requests']} requests, "
        f"{p['skipped']} skipped; tokens {p['tokens_in']} in / {p['tokens_out']} out, {cost}; "
        f"latency p50 {p['latency_ms_p50']} ms, p95 {p['latency_ms_p95']} ms"
    )


def _seeds(args: argparse.Namespace) -> Sequence[int]:
    seeds = args.seeds or DEFAULT_SEEDS
    if duplicates := sorted({s for s in seeds if seeds.count(s) > 1}):
        args.error(f"duplicate seed: {', '.join(map(str, duplicates))}")
    return seeds
