"""Event → overlay latency, measured locally: the app and headless Chromium on this machine replay
each match through the page, which stamps every cue after the next animation frame (app.js).

Server and browser read the same wall clock only because they run on one machine. The cues (the
facts', the stats-only moment cues and the deterministic recap, as the page shows them without a
run) are precomputed, so
the stamps measure delivery and drawing; the cue timeline's compute time is measured apart.
Matches run one after the other, so they do not compete for the CPU.

    uv run python scripts/measure_latency.py [--seeds 0 1 2 3 4] [--speed 20] [--hz 5]
"""

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright
from serving import serve  # scripts/serving.py, next to this file

from matchlens.facts import match_facts
from matchlens.generator import generate_match
from matchlens.latency import summarize
from matchlens.render.moments import match_cues

RUNS = Path(__file__).resolve().parent.parent / "runs"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2, 3, 4])
    parser.add_argument("--speed", type=float, default=20)
    parser.add_argument("--hz", type=int, default=None, help="tracking rate (default: the page's)")
    args = parser.parse_args()

    matches, cues, compute_s = [], {}, {}
    for seed in args.seeds:
        match = generate_match(seed)
        started = time.perf_counter()
        cues[match.meta.match_id] = match_cues(match, (), match_facts(match))
        compute_s[match.meta.match_id] = round(time.perf_counter() - started, 2)
        matches.append(match)
        print(
            f"{match.meta.match_id}: {len(cues[match.meta.match_id])} cues, "
            f"facts + timeline {compute_s[match.meta.match_id]} s"
        )

    stamps, errors = {}, []
    with serve(matches, cues) as base, sync_playwright() as p:
        browser = p.chromium.launch()
        for match in matches:
            match_id = match.meta.match_id
            page = browser.new_page(viewport={"width": 1600, "height": 900})
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            query = f"match={match_id}&speed={args.speed:g}" + (f"&hz={args.hz}" if args.hz else "")
            started = time.monotonic()
            page.goto(f"{base}/?{query}")
            page.wait_for_selector('#watch[data-state="ended"]', timeout=30 * 60_000)
            page.wait_for_timeout(100)  # the last cue's animation frame
            stamps[match_id] = page.evaluate("window.matchlensLatency")
            page.close()
            print(
                f"{match_id}: {len(stamps[match_id])} of {len(cues[match_id])} cues stamped in "
                f"{time.monotonic() - started:.0f} s"
            )
        version = browser.version
        browser.close()

    every = [s for seed_stamps in stamps.values() for s in seed_stamps]
    result = {
        "measured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "speed": args.speed,
        "hz": args.hz,
        "chromium": version,
        "cue_compute_s": compute_s,
        "latency_ms": summarize([s["latency_ms"] for s in every]),
        "delivery_ms": summarize([s["delivery_ms"] for s in every]),
        "missing": {m: len(cues[m]) - len(s) for m, s in stamps.items() if len(s) != len(cues[m])},
        "console_errors": errors,
        "stamps": stamps,
    }
    RUNS.mkdir(exist_ok=True)
    out = RUNS / f"latency-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(result, indent=1))
    for name in ("latency_ms", "delivery_ms"):
        s = result[name]
        print(f"{name}: p50 {s['p50']:.2f} / p95 {s['p95']:.2f} / max {s['max']:.2f} / n {s['n']}")
    print(f"missing {result['missing']}, console errors {len(errors)} → {out}")


if __name__ == "__main__":
    main()
