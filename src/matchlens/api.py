"""HTTP API: the generated matches and their live replay as Server-Sent Events.

`/events` replays a match's events; `/live` merges them with tracking frames and overlay cues;
`/recap` gives the recap at full time with its claims and evidence (the studio output).
The cue timeline of every match is computed once (about 5 s a match): at server start, one
match after the other in a worker thread, or on the first `/live` or `/recap` request of a match
that is not ready yet; clients share it. `/` is the web page (`matchlens/web`, static files) that
watches a match through `/live`; `/league` gives it club names, kit colours and shirt numbers.
`/healthz` answers as soon as the server listens (liveness); `/readyz` only once every cue
timeline is computed (readiness), so a new revision takes traffic warm.

Limits (`LiveLimits`, issue #2): the public app (`matchlens serve`) bounds what anonymous
clients may ask of `/live`, the stream that renders tracking frames. A whole match at speed 0
and 10 Hz is 58 540 frames at once, 42.6 MB and 16.7–18.3 s of CPU (m0, measured 26 Oct in one
process with its client: PROGRESS.md, Metrics, Live limits), more than a minute of a 0.25 vCPU
replica, so a few such requests would stall everyone's streams. With limits, `/live` refuses
(422) a speed under `min_speed` or more than `max_fps` frames a second (speed × hz), and answers
503 with `Retry-After` while the open streams' frames a second would pass `budget_fps` or
`max_streams` streams are open; `/events`, the probes and `/` are never limited. An app built
without limits (tests, scripts) serves any speed.
"""

import asyncio
import logging
import queue
import threading
import weakref
from collections.abc import AsyncIterator, Callable, Iterable, Mapping, Sequence
from concurrent.futures import Future
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from matchlens.explain.log import Handoff
from matchlens.league import load_league
from matchlens.match import Match
from matchlens.render.cues import Cue
from matchlens.render.moments import Overlay, match_overlay
from matchlens.stream import (
    DEFAULT_HZ,
    LIVE_HZ,
    Clock,
    LiveTimeline,
    end_id,
    live,
    live_timeline,
    replay,
    resume_index,
    tracking_ends,
)

MAX_SPEED = 1000.0
MIN_SPEED = 0.1  # slower replays would hold a connection (and a billed replica) for days


@dataclass(frozen=True)
class LiveLimits:
    """What one replica serves of `/live` to anonymous clients. A stream's CPU grows with the
    frames it sends a second, speed × hz: 286–312 µs a frame at 10 Hz, 344–345 at 5 Hz, 404–468
    at 1 Hz (Metrics, Live limits; upper bounds, the client ran in the same process), so a 0.25
    vCPU replica could send about 530 to 870 a second and do nothing else.
    - `min_speed`: the slowest replay, so one stream holds its share for a match's length at most.
    - `max_fps`: one stream's frames a second, the page's most (60× at 5 Hz).
    - `budget_fps`: the frames a second of all open streams together, about 0.21 s of CPU a
      second at 5 Hz, up to 0.28 s at 1 Hz (a design choice: 4 viewers at the page's 30× and
      5 Hz, 12 at 10×; the page's own links stay at 5 Hz, where the rest of the replica is left
      to the probes and the page).
    - `max_streams`: open streams whatever their rate, each a connection and its memory.
    - `retry_after_s`: the 503's `Retry-After`; the page tries again after 1, 2, 4, 8 and 16 s."""

    min_speed: float = 1.0
    max_fps: float = 300.0
    budget_fps: float = 600.0
    max_streams: int = 30
    retry_after_s: int = 5

    def admits(self, speed: float, hz: int) -> bool:
        """Whether one stream at `speed` and `hz` is within the limits on its own (the budget
        and the open streams aside): every link the page or a script gives must be."""
        return speed >= self.min_speed and speed * hz <= self.max_fps


SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
log = logging.getLogger(__name__)
WEB_DIR = Path(str(files("matchlens").joinpath("web")))


class _DaemonWorker:
    """Runs jobs one after the other in a daemon thread, started by the first job. The interpreter
    joins a `ThreadPoolExecutor`'s threads at exit, so a cue timeline still computing when the
    server stops (about a minute at 0.25 vCPU) held the process until the container's SIGKILL; a
    daemon thread is not joined. Not thread-safe: the app submits under its lock."""

    def __init__(self) -> None:
        self._jobs: queue.SimpleQueue[tuple[Future, Callable[[], object]] | None]
        self._jobs = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._closed = False
        weakref.finalize(self, self._jobs.put, None)  # an app dropped unshut ends its thread

    def submit[T](self, fn: Callable[..., T], /, *args: object) -> Future[T]:
        if self._closed:
            raise RuntimeError("cannot submit a job after shutdown")
        future: Future[T] = Future()
        self._jobs.put((future, lambda: fn(*args)))
        if self._thread is None:
            self._thread = threading.Thread(
                target=_run_jobs, args=(self._jobs,), name="cues", daemon=True
            )
            self._thread.start()
        return future

    def shutdown(self) -> None:
        """Cancels the queued jobs; the running one finishes in the background, unwaited."""
        self._closed = True
        while True:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                break
            if job is not None:
                job[0].cancel()
        self._jobs.put(None)


def _run_jobs(jobs: queue.SimpleQueue[tuple[Future, Callable[[], object]] | None]) -> None:
    while (job := jobs.get()) is not None:
        future, fn = job
        if future.set_running_or_notify_cancel():
            try:
                future.set_result(fn())
            except BaseException as e:  # as ThreadPoolExecutor: the future carries it
                future.set_exception(e)


def create_app(
    matches: Iterable[Match],
    clock: Clock | None = None,
    cues: Mapping[str, Sequence[Cue]] | None = None,
    handoffs: Mapping[str, Sequence[Handoff]] | None = None,
    overlays: Mapping[str, Overlay] | None = None,
    limits: LiveLimits | None = None,
) -> FastAPI:
    """An app serving `matches`, looked up by match id (ids are never parsed back into seeds).
    `cues`: cue timelines already computed, by match id (they have no recap endpoint); the
    others are computed by the app (`match_overlay`), with the narratives and the recap of a
    run's `handoffs` of the match if given. `overlays`: overlays already computed (a run's
    replay, checked before the server starts), by match id. `limits`: what `/live` serves to
    anonymous clients; None serves any speed (tests and scripts)."""
    registry: dict[str, Match] = {}
    for m in matches:
        if m.meta.match_id in registry:
            raise ValueError(f"duplicate match id {m.meta.match_id}")
        registry[m.meta.match_id] = m
    handoffs = dict(handoffs or {})
    if unknown := sorted(handoffs.keys() - registry.keys()):
        raise ValueError(f"handoffs of matches not served: {', '.join(unknown)}")
    given = [set(handoffs), set(cues or {}), set(overlays or {})]
    if both := sorted((given[0] & given[1]) | (given[0] & given[2]) | (given[1] & given[2])):
        raise ValueError(f"two of cues, handoffs and overlays given for {', '.join(both)}")
    if unknown := sorted(given[2] - registry.keys()):
        raise ValueError(f"overlays of matches not served: {', '.join(unknown)}")

    worker = _DaemonWorker()
    lock = threading.Lock()
    computed: dict[str, Future[Overlay]] = {}
    for match_id, given in (cues or {}).items():
        computed[match_id] = Future()
        computed[match_id].set_result(Overlay(list(given)))
    for match_id, overlay in (overlays or {}).items():
        computed[match_id] = Future()
        computed[match_id].set_result(overlay)
    timelines: dict[tuple[str, int], LiveTimeline] = {}
    open_live = 0  # `/live` responses admitted and not over
    open_mfps = 0  # their frames a second together, in thousandths: sums and differences exact

    def release(mfps: int) -> None:
        nonlocal open_live, open_mfps
        open_live -= 1
        open_mfps -= mfps

    class Held(StreamingResponse):
        """A `/live` stream that holds its share until the response is over, however it ends:
        sent to its end, cut by its client or never started."""

        mfps = 0

        async def __call__(self, scope, receive, send) -> None:
            try:
                await super().__call__(scope, receive, send)
            finally:
                release(self.mfps)

    def overlay_of(match_id: str) -> Future[Overlay]:
        with lock:
            done = computed.get(match_id)
            cancelled = done is not None and done.cancelled()
            failed = done is not None and done.done() and not cancelled and done.exception()
            if failed:  # a probe retries unseen (no client reaches an unready replica): say why
                log.error(
                    "cue timeline of %s failed, computing it again", match_id, exc_info=failed
                )
            if done is None or cancelled or failed:  # retry
                logged = handoffs.get(match_id, ())
                computed[match_id] = worker.submit(match_overlay, registry[match_id], logged)
            return computed[match_id]

    async def timeline_of(match: Match, hz: int) -> LiveTimeline:
        key = match.meta.match_id, hz
        if key not in timelines:
            overlay = await asyncio.wrap_future(overlay_of(match.meta.match_id))
            timelines[key] = live_timeline(
                match.meta.match_id, match.events, overlay.cues, tracking_ends(match), hz
            )
        return timelines[key]

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        for match_id in registry:
            overlay_of(match_id)  # queued in the worker, one match after the other
        yield
        worker.shutdown()

    app = FastAPI(
        title="Footnote",
        summary="Synthetic football match events, replayed live.",
        lifespan=lifespan,
    )

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def page() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    league = load_league()

    @app.get("/league")
    def league_info() -> dict:
        """Clubs with their kit colours and squads (shirt numbers), for the page."""
        return {
            "id": league.id,
            "name": league.name,
            "clubs": [
                {
                    "id": c.id,
                    "name": c.name,
                    "short_name": c.short_name,
                    "colours": {"primary": c.primary_colour, "secondary": c.secondary_colour},
                    "players": [
                        {"id": p.id, "name": p.name, "number": p.number, "position": p.position}
                        for p in c.players
                    ],
                }
                for c in league.clubs
            ],
        }

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz(response: Response) -> dict[str, str | list[str]]:
        """503 with the matches still warming until every cue timeline is computed, then 200.
        A timeline that failed, or that a leaving client cancelled while it was queued, is
        queued again here, so the probe itself brings the app to ready."""
        pending = [match_id for match_id in registry if not overlay_of(match_id).done()]
        if pending:
            response.status_code = 503
            return {"status": "warming", "pending": pending}
        return {"status": "ok"}

    @app.get("/matches")
    def list_matches() -> list[dict[str, str]]:
        return [
            {"match_id": m.meta.match_id, "home": m.meta.home, "away": m.meta.away}
            for m in registry.values()
        ]

    @app.get("/matches/{match_id}/events")
    async def stream_events(
        match_id: str,
        speed: Annotated[float, Query(ge=0, le=MAX_SPEED, allow_inf_nan=False)] = 1.0,
        last_event_id: Annotated[str | None, Query()] = None,
        last_event_id_header: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    ) -> Response:
        """Replay at `speed` x real time (0: no waiting, else at least MIN_SPEED). Resumes after
        `Last-Event-ID`: the header browsers send on reconnect, or a query parameter for the
        first connect. After the `end` message's id it answers 204, which stops a browser's
        automatic reconnect."""
        match = registry.get(match_id)
        if match is None:
            raise HTTPException(404, f"unknown match {match_id}")
        if 0 < speed < MIN_SPEED:
            raise HTTPException(422, f"speed must be 0 or at least {MIN_SPEED:g}")
        last = last_event_id_header or last_event_id
        if last == end_id(match_id):
            return Response(status_code=204)
        try:
            start = resume_index(match.events, last)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return StreamingResponse(
            replay(match, speed, start, clock),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    @app.get("/matches/{match_id}/recap")
    async def recap(match_id: str) -> dict:
        """The recap at full time, per persona: who wrote it (the Recap Writer, the engine or
        the Persona Editor), the text, its claims and their fact and event ids. It speaks of the
        whole match: the page shows it only at the final whistle."""
        match = registry.get(match_id)
        if match is None:
            raise HTTPException(404, f"unknown match {match_id}")
        overlay = await asyncio.wrap_future(overlay_of(match_id))
        if overlay.recap is None:
            raise HTTPException(404, f"no recap of {match_id}")
        return overlay.recap.to_dict()

    @app.get("/matches/{match_id}/live")
    async def stream_live(
        match_id: str,
        speed: Annotated[float, Query(ge=0, le=MAX_SPEED, allow_inf_nan=False)] = 1.0,
        hz: Annotated[int, Query()] = DEFAULT_HZ,
        last_event_id: Annotated[str | None, Query()] = None,
        last_event_id_header: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    ) -> Response:
        """The match at `speed` with tracking frames at `hz` (1, 2, 5 or 10) and overlay cues
        merged into one stream; resumes after any message id, as `/events` does after an event
        id, and answers 204 after the `end` message's id. The public app limits it: a speed
        under 1× or more than 300 frames a second (speed × hz) gets a 422 with the reason, and a
        full replica (600 frames a second or 30 streams open) a 503 with `Retry-After`."""
        match = registry.get(match_id)
        if match is None:
            raise HTTPException(404, f"unknown match {match_id}")
        if 0 < speed < MIN_SPEED:
            raise HTTPException(422, f"speed must be 0 or at least {MIN_SPEED:g}")
        if hz not in LIVE_HZ:
            raise HTTPException(422, f"hz must be one of {', '.join(map(str, LIVE_HZ))}")
        if limits is not None:
            if speed < limits.min_speed:
                raise HTTPException(422, f"speed must be at least {limits.min_speed:g} here")
            if speed * hz > limits.max_fps:
                raise HTTPException(
                    422, f"at most {limits.max_fps:g} frames a second here: lower speed or hz"
                )
        last = last_event_id_header or last_event_id
        if last == end_id(match_id):
            return Response(status_code=204)
        nonlocal open_live, open_mfps
        mfps = round(speed * hz * 1000)
        if limits is not None and (
            open_live >= limits.max_streams or open_mfps + mfps > round(limits.budget_fps * 1000)
        ):
            raise HTTPException(
                503,
                "too many streams open here, try again shortly",
                headers={"Retry-After": str(limits.retry_after_s)},
            )
        # the share is taken with the check, before any await: no request slips past it
        open_live, open_mfps = open_live + 1, open_mfps + mfps
        try:  # until there is a response to hold it, any failure gives the share back
            timeline = await timeline_of(match, hz)
            try:
                start = timeline.resume_index(last)
            except ValueError as e:
                raise HTTPException(400, str(e)) from None
        except BaseException:
            release(mfps)
            raise
        response = Held(
            live(match, timeline, speed, start, clock),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )
        response.mfps = mfps
        return response

    return app
