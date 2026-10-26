"""The app on a free local port, for the scripts that drive the page in headless Chromium."""

import contextlib
import socket
import threading
import time
from collections.abc import Iterator, Mapping, Sequence

import uvicorn

from matchlens.api import create_app
from matchlens.match import Match
from matchlens.render.cues import Cue


@contextlib.contextmanager
def serve(matches: Sequence[Match], cues: Mapping[str, Sequence[Cue]]) -> Iterator[str]:
    """uvicorn serving `matches` with their precomputed `cues`; yields the base URL."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(
        create_app(matches, cues=cues), log_level="warning", timeout_graceful_shutdown=1
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(10)
