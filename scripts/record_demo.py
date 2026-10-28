"""Record the watch page as a 1920×1080 webm in runs/: headless Chromium replays one match, then
opens the evidence of the newest key moment's card (else the newest card that has a place) and
marks that place on the pitch. With `--run`, the moments show the narratives of that run of
`matchlens explain` that the Guard passes again; without it, their stats-only text.

Playwright records the video itself (its own ffmpeg); the length is read back from the file's
header with that ffmpeg.

    uv run python scripts/record_demo.py [--seed 7] [--run DIR] [--speed 30] [--seconds 60]
"""

import argparse
import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright
from serving import serve  # scripts/serving.py, next to this file

from matchlens.explain.log import read_handoffs
from matchlens.generator_v2 import generate_match_v2
from matchlens.render.moments import NARRATIVE, match_cues

RUNS = Path(__file__).resolve().parent.parent / "runs"
SIZE = {"width": 1920, "height": 1080}


def playwright_ffmpeg() -> Path:
    """The newest ffmpeg Playwright installed (Linux)."""
    browsers = Path(
        os.environ.get("PLAYWRIGHT_BROWSERS_PATH", Path.home() / ".cache/ms-playwright")
    )
    found = sorted(browsers.glob("ffmpeg-*/ffmpeg-linux"), key=lambda p: int(p.parent.name[7:]))
    if not found:
        raise FileNotFoundError(f"no Playwright ffmpeg under {browsers}")
    return found[-1]


def video_seconds(path: Path) -> float:
    """The length of a video from its header (this ffmpeg has no null muxer, so it is asked about
    the input alone and exits non-zero for the missing output)."""
    run = subprocess.run(
        [playwright_ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True
    )
    found = re.search(r"Duration: (\d+):(\d+):([\d.]+)", run.stderr)
    if not found:
        raise RuntimeError(f"no duration in the header of {path}:\n{run.stderr}")
    h, m, s = found.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--run", type=Path, help="a run directory of `matchlens explain`")
    parser.add_argument("--speed", type=float, default=30)
    parser.add_argument("--seconds", type=float, default=60, help="replay before the card click")
    args = parser.parse_args()

    match = generate_match_v2(args.seed)
    match_id = match.meta.match_id
    try:
        handoffs = read_handoffs(args.run / "handoffs.jsonl") if args.run else []
        if args.run and (args.run / "recap.jsonl").exists():  # `matchlens recap`
            handoffs += read_handoffs(args.run / "recap.jsonl")
        timeline = match_cues(match, handoffs)
    except (OSError, ValueError) as e:
        parser.error(f"the run {args.run} cannot be replayed on {match_id}: {e}")
    narratives = sum(c.lines[0].startswith(f"{NARRATIVE} · ") for c in timeline)
    print(f"{match_id}: {len(timeline)} cues, {narratives} narratives from the run")
    cues = {match_id: timeline}
    RUNS.mkdir(exist_ok=True)
    raw = RUNS / "video-raw"
    with serve([match], cues) as base, sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport=SIZE, record_video_dir=raw, record_video_size=SIZE)
        page = context.new_page()
        started = time.monotonic()
        page.goto(f"{base}/?match={match_id}&speed={args.speed:g}")
        page.wait_for_selector('#watch[data-state="live"]', timeout=60_000)
        page.wait_for_timeout(args.seconds * 1000)
        newest = page.locator("#rail article.cue-moment").first
        if not newest.count():
            newest = page.locator("#rail article.cue.locatable").first
        if newest.count():  # pinned by id: a newer card may arrive while the demo goes on
            card = page.locator(f'#rail [data-cue-id="{newest.get_attribute("data-cue-id")}"]')
            card.locator(".chip").click()
            page.wait_for_timeout(1500)
            card.click()
            page.wait_for_timeout(3000)
        recorded = time.monotonic() - started
        video = page.video
        context.close()  # writes the video
        browser.close()
        out = RUNS / f"demo-{match_id}-{datetime.now():%Y%m%d-%H%M%S}.webm"
        shutil.move(video.path(), out)
    shutil.rmtree(raw, ignore_errors=True)
    size_mb = out.stat().st_size / 1e6
    print(
        f"{out}: {video_seconds(out):.1f} s of video ({recorded:.1f} s recorded), {size_mb:.2f} MB"
    )


if __name__ == "__main__":
    main()
