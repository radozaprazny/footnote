"""Test helpers: a fake clock for replays and a minimal SSE parser."""

import asyncio
import json

from matchlens.stream import Clock

WALL_START_MS = 1_800_000_000_000


class FakeClock:
    """Time moves only when the replay sleeps; every sleep is recorded."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds

    def wall_ms(self) -> int:
        return WALL_START_MS + round(self.t * 1000)

    def clock(self) -> Clock:
        return Clock(monotonic=self.monotonic, sleep=self.sleep, wall_ms=self.wall_ms)


def collect(stream) -> list[str]:
    """Run an async SSE generator to the end and return its chunks."""

    async def run():
        return [chunk async for chunk in stream]

    return asyncio.run(run())


def parse(text: str) -> list[dict]:
    """SSE messages as dicts of their fields; `data` is decoded JSON, comments are `comment`."""
    messages = []
    for block in text.split("\n\n"):
        if not block:
            continue
        message: dict = {}
        for line in block.split("\n"):
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "":
                message["comment"] = value
            elif field == "data":
                assert "data" not in message, "one data line per message"
                message["data"] = json.loads(value)
            else:
                message[field] = value
        messages.append(message)
    return messages
