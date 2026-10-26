"""The submission's texts (docs/submission.md) are pasted and recorded as they are: the page's
limits, a video under two minutes, numbers that the Metrics hold, the live app's URL, and a
terminal shot that shows the one real refusal of the demo runs."""

import json
import re
import subprocess
from pathlib import Path
from urllib.parse import parse_qsl

from test_league import famous_surname_hits, real_club_hits

from matchlens.api import LiveLimits
from matchlens.stream import DEFAULT_HZ

REPO = Path(__file__).resolve().parents[1]
DOC = (REPO / "docs" / "submission.md").read_text(encoding="utf-8")
METRICS = (
    (REPO / "PROGRESS.md").read_text(encoding="utf-8").split("## Metrics", 1)[1].split("\n## ")[0]
)
APP_URL = r"https://[\w.-]+\.azurecontainerapps\.io/"
MAX_VIDEO_S = 115  # the rules ask for less than 2:00 (4.4); 5 s for the recording to slip
MAX_WORDS_PER_S = 2.5  # a calm pace of voice-over


def pasted(label: str) -> str:
    """The text of the code block after a bold label: what the owner copies."""
    found = re.search(rf"\*\*{label}\*\*[^\n]*:\n\n```\w*\n(.*?)\n```", DOC, re.DOTALL)
    assert found, label
    return found[1]


def metrics_row(label: str) -> str:
    (row,) = [line for line in METRICS.splitlines() if line.startswith(f"| {label} |")]
    return row


def shots() -> list[tuple[int, int, str]]:
    """The video's shots: start and end in seconds, and the voice-over."""
    lines = [line for line in DOC.splitlines() if re.match(r"\| \d:\d\d–", line)]
    found = []
    for line in lines:
        cells = re.fullmatch(r"\| (\d):(\d\d)–(\d):(\d\d) \| .+? \| \"(.+)\" \|", line)
        assert cells, line  # every row of the table has its times and a quoted voice-over
        a, b, c, d, voice = cells.groups()
        found.append((int(a) * 60 + int(b), int(c) * 60 + int(d), voice))
    return found


def fits_page(text: str, limit: int) -> bool:
    return "\n" not in text and len(text) <= limit


def test_the_texts_to_paste_fit_the_page():
    """The page takes a title of 140 and a tagline of 300 characters, on one line; the stated
    counts are the real ones. On the limit a text fits, one character over it does not."""
    for label, limit in (("Title", 140), ("Tagline", 300)):
        stated = re.search(rf"\*\*{label}\*\* \((\d+) of (\d+) characters\)", DOC)
        text = pasted(label)
        assert (len(text), int(stated[2])) == (int(stated[1]), limit)
        assert fits_page(text, limit)
        assert fits_page("x" * limit, limit) and not fits_page("x" * (limit + 1), limit)
        assert not fits_page("x\ny", limit)  # one line


def test_the_pitch_names_the_category_and_the_live_app():
    """The rules name the category two ways; the tagline and the keywords name it too; the
    pitch links the app the runbook names."""
    description = pasted("Description")
    assert "Best Multi-Agent System" in description
    assert "Best Multi-Agent Orchestration" in description
    assert "Best Multi-Agent System" in pasted("Tagline")
    assert "Best Multi-Agent System" in pasted("Keywords")
    runbook = (REPO / "docs" / "deploy.md").read_text(encoding="utf-8")
    assert set(re.findall(APP_URL, description)) == set(re.findall(APP_URL, runbook))


def test_the_pitch_numbers_stand_in_their_metrics_rows():
    """Each measured claim of the pitch is the value of its row in PROGRESS.md's Metrics."""
    measured = pasted("Description").split("**Measured.**", 1)[1].split("\n\n", 1)[0]
    claims = {
        "28 of 28": "Guard pass rate",
        "62 of 62": "Slovak translations (M5 item 6)",
        "€3.43": "Cost, October to 25 Oct",
    }
    for claim, label in claims.items():
        assert claim in measured
        assert claim in metrics_row(label), label
    guard = metrics_row("Guard pass rate")
    assert "Haiku 5.5: 28 of 28 first attempt" in guard and "Sonnet 5.5: 28 of 28," in guard
    assert "every model call of M3–M5) €3.43" in metrics_row("Cost, October to 25 Oct")
    # no other number: 28 of 28, the models 5.5, 62 of 62, 25 October, €3.43
    assert re.findall(r"\d+(?:\.\d+)?", measured) == [
        "28",
        "28",
        "5.5",
        "5.5",
        "62",
        "62",
        "25",
        "3.43",
    ]
    assert "61 at the first attempt" in metrics_row("Slovak translations (M5 item 6)")
    assert "one after a retry" in measured


def fits(found: list[tuple[int, int, str]]) -> bool:
    """Shot after shot from 0:00, the last ending by MAX_VIDEO_S, each voice-over at a calm pace."""
    return (
        found[0][0] == 0
        and found[-1][1] <= MAX_VIDEO_S
        and all(end == nxt for (_, end, _), (nxt, _, _) in zip(found, found[1:], strict=False))
        and all(len(v.split()) <= MAX_WORDS_PER_S * (end - start) for start, end, v in found)
    )


def test_the_video_is_under_two_minutes():
    """Every row of the table parsed, the shots fit, and the stated word count is the real one."""
    found = shots()
    assert len(found) == 8 and fits(found)
    end = found[-1][1]
    assert f"the shots end at {end // 60}:{end % 60:02d}" in DOC
    words = sum(len(voice.split()) for *_, voice in found)
    assert re.search(rf"with {words} words of voice-over", DOC)


def test_the_video_limit_is_pinned_from_both_sides():
    """1:55 fits and 1:56 does not, both under the rules' 2:00; 25 words in 10 seconds fit and 26
    do not; a gap between shots does not fit either."""
    assert fits([(0, 60, "a b"), (60, 115, "c d")])
    assert not fits([(0, 60, "a b"), (60, 116, "c d")])
    assert fits([(0, 10, "w " * 25)])
    assert not fits([(0, 10, "w " * 26)])
    assert not fits([(0, 60, "a b"), (61, 115, "c d")])
    assert not fits([(1, 60, "a b")])  # it starts at 0:00
    assert not fits([(0, 60, "a b"), (59, 115, "c d")])  # no overlap either


def test_every_page_link_of_the_shots_is_one_the_live_app_serves():
    """Issue #2: the live app refuses a stream past its public limits with a 422, so every page
    link the shots open names its speed and stays within them (the full-time one, 300× at 1 Hz,
    is exactly on the 300 frames a second)."""
    links = re.findall(r"`\?(match=[^`]+)`", DOC)
    assert links
    for link in links:
        query = dict(parse_qsl(link))
        speed, hz = float(query["speed"]), int(query.get("hz", DEFAULT_HZ))
        assert LiveLimits().admits(speed, hz), link


def test_the_terminal_shot_shows_the_refusal_and_the_retry():
    """The command of the terminal shot, pasted into bash at the repo root, prints the refused
    attempt with its reason and then the attempt that passed."""
    (command,) = re.findall(r"^```\n(python3 -c .*?)\n```", DOC, re.MULTILINE | re.DOTALL)
    out = subprocess.run(
        ["bash", "-c", command], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert len(out) == 4
    assert out[0] == "False ['phrase_not_cited']"
    assert out[1].endswith("Saltreach FC má 59% navrch.")
    assert out[2] == "True []"
    assert out[3].endswith("momentum Saltreach FC je 59%.")
    assert "Saltreach FC má 59% navrch" in DOC and "momentum Saltreach FC je 59%" in DOC


def test_it_is_the_one_refusal_of_the_demo_runs():
    """Across every log of the demo runs, one attempt was refused: the one the video shows."""
    refused = set()
    for log in sorted((REPO / "demo" / "runs").glob("*/*.jsonl")):
        for line in log.read_text(encoding="utf-8").splitlines():
            state = json.loads(line)["state"]
            more = (*state.get("renditions", ()), *state.get("translations", ()))
            for rewriting in (state, *more):
                for attempt in rewriting["attempts"]:
                    verdict = attempt.get("verdict")
                    if verdict and not verdict["passed"]:
                        key = (state["match_id"], state["moment_id"], attempt["draft"]["text"])
                        refused.add(key)
    assert [k[:2] for k in refused] == [("m1", "recap")]


def test_the_video_s_cost_is_the_metrics_one():
    """The voice-over's "about three and a half euros" is the Claude calls' cost, rounded."""
    row = metrics_row("Cost, October to 25 Oct")
    claude = float(re.search(r"every model call of M3–M5\) €(\d+\.\d+)", row)[1])
    assert round(claude * 2) / 2 == 3.5
    assert "about three and a half euros" in DOC


def test_the_published_texts_name_no_real_club_or_player():
    """The README and the submission texts go public: whole words of the hashed lists, in any
    case or Slovak form, hit nothing."""
    for path in (REPO / "README.md", REPO / "docs" / "submission.md"):
        for line in path.read_text(encoding="utf-8").splitlines():
            # the engine's word "reading" is an ordinary word, not the club of that name
            line = re.sub(r"\breadings?\b", "", line)
            assert real_club_hits(line) == set(), (path.name, line)
            assert famous_surname_hits(line) == set(), (path.name, line)
