"""The web page: served files (TestClient) and end-to-end runs in headless Chromium, with a
server that a test stops and starts again."""

import itertools
import json
import re
import socket
import threading
import time

import pytest
import real
import uvicorn
from fastapi.testclient import TestClient

from matchlens.api import WEB_DIR, create_app
from matchlens.events import display_clock
from matchlens.league import load_league

SVG_NS = "http://www.w3.org/2000/svg"


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app([real.match(7)], cues={"m7": real.cues(7)}))


def test_page_links_its_assets(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assets = re.findall(r'(?:src|href)="(/static/[^"]+)"', r.text)
    assert sorted(assets) == ["/static/app.css", "/static/app.js"]
    types = {".css": "text/css", ".js": "text/javascript"}
    for path in assets:
        asset = client.get(path)
        assert asset.status_code == 200
        assert asset.headers["content-type"].startswith(types[path[path.rfind(".") :]])
    for anchor in ('id="pitch"', 'viewBox="-4 -3 113 74"', 'id="rail"', 'id="lower-third"'):
        assert anchor in r.text
    for anchor in ("<title>Footnote</title>", 'class="brand" href="/">Footnote<'):
        assert anchor in r.text  # the product's name (M5)
    assert re.findall(r'data-persona="(\w+)">(\w+)<', r.text) == [
        ("analyst", "Analyst"),
        ("fan", "Fan"),
    ]
    assert client.get("/static/missing.js").status_code == 404


def test_page_loads_nothing_from_outside():
    """No CDN, no external fonts: the only absolute URL is the SVG namespace, which is a name."""
    for path in WEB_DIR.iterdir():
        text = path.read_text(encoding="utf-8")
        assert re.findall(r"(?:https?:)?//[\w.-]+\.\w", text.replace(SVG_NS, "")) == [], path
        assert "@import" not in text and "@font-face" not in text, path


def test_league_gives_kits_and_shirt_numbers(client):
    league = load_league()
    body = client.get("/league").json()
    assert [c["id"] for c in body["clubs"]] == [c.id for c in league.clubs]
    for given, club in zip(body["clubs"], league.clubs, strict=True):
        assert given["colours"] == {
            "primary": club.primary_colour,
            "secondary": club.secondary_colour,
        }
        assert given["name"] == club.name
        assert {p["id"]: p["number"] for p in given["players"]} == {
            p.id: p.number for p in club.players
        }


# --- end to end: a real server and headless Chromium --------------------------------------------


class Server:
    """uvicorn in a thread serving a fresh `make_app()` on one local port; a test stops it and
    starts it again on the same port, so the page reconnects to the same URL. A stop cuts open
    streams after 1 s."""

    def __init__(self, make_app):
        self.make_app = make_app
        self.port = 0  # a free one at the first start
        self.server = None
        self.thread = None

    def start(self) -> str:
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # the port of the last run
        sock.bind(("127.0.0.1", self.port))
        self.port = sock.getsockname()[1]
        config = uvicorn.Config(self.make_app(), log_level="warning", timeout_graceful_shutdown=1)
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(
            target=self.server.run, kwargs={"sockets": [sock]}, daemon=True
        )
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            assert time.monotonic() < deadline, "uvicorn did not start"
            time.sleep(0.05)
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(10)
        assert not self.thread.is_alive(), "uvicorn did not stop"

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()


@pytest.fixture(scope="module")
def site():
    """uvicorn on a free port serving seed 7, cold (the cue timeline is computed at start), and a
    headless Chromium; both stop at the end of the module."""
    from playwright.sync_api import sync_playwright

    server = Server(lambda: create_app([real.match(7)]))
    base = server.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            yield browser, base
            browser.close()
    finally:
        server.stop()


@pytest.fixture
def warm(site):
    """The browser of `site` and a server of its own that a test stops and starts again: seed 7
    with its cue timeline given, so every start serves at once."""
    server = Server(lambda: create_app([real.match(7)], cues={"m7": real.timeline(7)}))
    base = server.start()
    yield site[0], server, base
    if server.running:
        server.stop()


# Records what the page shows over time: the cue ids put into the lower third and the cards it
# held together, and every value of the clock, so a test sees cards that came and went and a
# clock that jumped back.
RECORDER = """
window.__lower = []; window.__together = []; window.__clocks = []; window.__watch = [];
window.__lowerTheirs = []; window.__lowerTheirsOpacity = [];
document.addEventListener("DOMContentLoaded", () => {
  const lower = document.querySelector("#lower-third");
  new MutationObserver((changes) => {
    for (const c of changes) {
      for (const n of c.addedNodes) if (n.dataset) __lower.push(n.dataset.cueId);
      for (const n of c.addedNodes) {
        if (n.classList && n.classList.contains("theirs")) {
          __lowerTheirs.push(n.dataset.cueId);
          __lowerTheirsOpacity.push(getComputedStyle(n).opacity);  // as it came
        }
      }
    }
    __together.push([...lower.children].map((n) => n.dataset.cueId));
  }).observe(lower, { childList: true });
  const clock = document.querySelector("#clock");
  new MutationObserver(() => __clocks.push(clock.textContent))
    .observe(clock, { childList: true, characterData: true, subtree: true });
  const watch = document.querySelector("#watch");
  new MutationObserver((changes) => {
    for (const c of changes) {
      __watch.push(`${c.attributeName}=${watch.getAttribute(c.attributeName)}`);
    }
  }).observe(watch, { attributes: true, attributeFilter: ["hidden", "data-state"] });
});
"""


def open_page(browser):
    """A page that records console errors, uncaught exceptions, lower-third cues and clocks."""
    page = browser.new_page(viewport={"width": 1600, "height": 900})
    page.add_init_script(RECORDER)
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    return page, errors


def clock_ms(display: str) -> int:
    """`MM:SS` of the first minutes, in ms (no stoppage time there)."""
    minutes, seconds = display.split(":")
    return (int(minutes) * 60 + int(seconds)) * 1000


def test_whole_match_in_the_browser(site):
    browser, base = site
    page, errors = open_page(browser)
    page.goto(f"{base}/?match=m7&speed=1000&hz=2")
    # a cold server computes the cue timeline first (about 5 s): the page says it is loading
    page.wait_for_selector('#watch[data-state="ended"]', timeout=60_000)
    # the watch view shows up in its loading state; meta turns it live (on a cold server the
    # cue timeline takes about 5 s, then the stream runs)
    assert page.evaluate("window.__watch")[:2] == ["hidden=null", "data-state=live"]
    assert page.locator("#loading").is_hidden()

    match = real.match(7)
    meta = match.meta
    clubs = {c.id: c for c in load_league().clubs}
    players = page.locator("#players g.player")
    assert players.count() == 22
    numbers = sorted(int(t) for t in page.locator("#players text").all_text_contents())
    squad = {p.id: p.number for c in clubs.values() for p in c.players}
    assert numbers == sorted(squad[p] for p in meta.home_lineup + meta.away_lineup)
    assert all(
        t != "translate(-10 -10)" for t in [g.get_attribute("transform") for g in players.all()]
    )
    for team, lineup in ((meta.home, meta.home_lineup), (meta.away, meta.away_lineup)):
        for player in lineup:  # slt and cor do not clash: both wear their primary colour
            shirt = page.locator(f'#players g[data-player="{player}"] circle')
            assert shirt.get_attribute("fill") == clubs[team].primary_colour
            assert shirt.get_attribute("stroke") == clubs[team].secondary_colour

    # at the end everyone stands where the last frame of the stream puts them (2 Hz: every 500 ms)
    last = list(match.frames(500))[-1]
    page.wait_for_timeout(100)  # past the interpolation of the last frame
    for p in last.players:
        transform = page.get_attribute(f'#players g[data-player="{p.player}"]', "transform")
        assert transform == f"translate({p.x:.2f} {p.y:.2f})"
    ball = page.locator("#ball")
    assert (ball.get_attribute("cx"), ball.get_attribute("cy")) == (
        f"{last.ball.x:.2f}",
        f"{last.ball.y:.2f}",
    )

    cues = real.timeline(7)  # the facts' cues and the stats-only moment cues
    cards = page.locator("#rail article.cue")
    shown = [card.get_attribute("data-fact-ids") for card in cards.all()]
    assert [json.loads(s) for s in shown] == [list(c.fact_ids) for c in reversed(cues)]
    assert page.evaluate("window.__lower") == [c.cue_id for c in cues]
    home = sum(e.type == "goal" and e.team == meta.home for e in match.events)
    away = sum(e.type == "goal" and e.team == meta.away for e in match.events)
    assert page.text_content("#score") == f"{home}–{away}"
    assert page.text_content("#status") == "Full time"

    # a key moment's card shows its stats-only text as it is, after the goal it explains
    moment = next(c for c in cues if c.kind == "moment")
    lines = page.locator(f'#rail article[data-cue-id="{moment.cue_id}"] .cue-lines p')
    assert lines.all_text_contents() == list(moment.lines)
    assert moment.lines[0].startswith("Key moment · ")
    assert [c.kind for c in cues if c.due == moment.due] == ["goal", "moment"]
    # due together, the goal and its moment share the lower third; a later cue replaces both
    together = page.evaluate("window.__together")
    goal_at = next(c for c in cues if c.kind == "goal" and c.due == moment.due)
    assert [goal_at.cue_id, moment.cue_id] in together
    assert max(len(t) for t in together) == 2

    # every cue is stamped once, in order, after it was drawn: delivery from the cue message,
    # latency from its trigger (the last of its events in the stream; the cue itself if none)
    stamps = page.evaluate("window.matchlensLatency")
    assert [s["cue_id"] for s in stamps] == [c.cue_id for c in cues]
    assert [s["kind"] for s in stamps] == [c.kind for c in cues]
    order = {e.event_id: n for n, e in enumerate(match.events)}
    triggers = [max(c.event_ids, key=order.get) if c.event_ids else c.cue_id for c in cues]
    assert [s["trigger"] for s in stamps] == triggers
    assert {c.kind for c in cues if len(c.event_ids) > 1} >= {"goal"}  # the pick is pinned
    assert all(0 <= s["delivery_ms"] <= s["latency_ms"] < 5000 for s in stamps), stamps
    no_event = [s for s, c in zip(stamps, cues, strict=True) if not c.event_ids]
    assert no_event and all(s["latency_ms"] == s["delivery_ms"] for s in no_event)

    # the verified chip opens and closes the cue's fact and event ids
    goal = next(c for c in cues if c.kind == "goal")
    card = page.locator(f'#rail article[data-cue-id="{goal.cue_id}"]')
    evidence = card.locator(".evidence")
    assert evidence.is_hidden()
    card.locator(".chip").click()
    assert evidence.is_visible()
    assert card.locator(".chip").get_attribute("aria-expanded") == "true"
    assert evidence.locator("code").all_text_contents() == [*goal.fact_ids, *goal.event_ids]
    card.locator(".chip").click()
    assert evidence.is_hidden()
    assert page.locator("#highlight circle").count() == 0  # the chip is not a click on the card

    # a click on the card marks where its first event happened
    card.click()
    shot = next(e for e in match.events if e.event_id == goal.event_ids[0])
    spot = page.locator("#highlight circle").first
    spot_x = spot.get_attribute("cx")  # read at once: the mark goes after 4 s
    assert (float(spot.get_attribute("cx")), float(spot.get_attribute("cy"))) == (
        shot.start.x,
        shot.start.y,
    )
    assert "selected" in card.get_attribute("class")

    # a card with no place (a window's numbers) is not clickable and leaves the mark alone
    window = next(c for c in cues if c.kind == "window")
    other = page.locator(f'#rail article[data-cue-id="{window.cue_id}"]')
    assert "locatable" not in other.get_attribute("class")
    other.click()
    assert page.locator("#highlight circle").count() in (0, 2)  # 0: the 4 s are over
    assert all(c.get_attribute("cx") == spot_x for c in page.locator("#highlight circle").all())

    # the page closed the stream at its end: no retry of the browser (1 s), no reopen
    page.wait_for_timeout(1500)
    assert page.text_content("#status") == "Full time"
    assert page.evaluate("window.__watch")[-1] == "data-state=ended"
    assert errors == []
    page.close()


def test_interpolation_and_speed_switch(site):
    browser, base = site
    page, errors = open_page(browser)
    page.goto(f"{base}/?match=m7&speed=10&hz=1")
    page.wait_for_function("document.querySelector('#clock').textContent >= '00:10'")

    # at 10x and 1 Hz a frame arrives every 100 ms; players move between frames, not in steps
    seen = page.evaluate("""() => new Promise((done) => {
      const poses = new Set(), balls = new Set(), clocks = new Set();
      const end = performance.now() + 1000;
      const sample = () => {
        poses.add([...document.querySelectorAll("#players g")]
          .map((g) => g.getAttribute("transform")).join());
        balls.add(document.querySelector("#ball").getAttribute("cx"));
        clocks.add(document.querySelector("#clock").textContent);
        if (performance.now() < end) requestAnimationFrame(sample);
        else done([poses.size, balls.size, clocks.size]);
      };
      requestAnimationFrame(sample);
    })""")
    poses, balls, frames = seen
    assert poses >= 1.5 * frames, seen  # without interpolation: at most one pose a frame
    assert balls > 1, seen

    # a speed switch resumes after the last message: the clock never goes back, no cue twice
    page.click('[data-speed="30"]')
    assert page.get_attribute('[data-speed="30"]', "aria-pressed") == "true"
    assert page.get_attribute('[data-speed="10"]', "aria-pressed") == "false"
    assert "speed=30" in page.url
    page.wait_for_function("document.querySelector('#clock').textContent >= '05:30'")
    page.click('[data-speed="60"]')
    assert "speed=60" in page.url
    page.wait_for_function("document.querySelector('#clock').textContent >= '07:00'")
    clocks = page.evaluate("window.__clocks")
    assert all("+" not in c for c in clocks)
    assert [clock_ms(c) for c in clocks] == sorted(clock_ms(c) for c in clocks)
    assert page.text_content("#score") == "0–1"  # m7: cor scores at 04:18, slt next at 12:34
    shown = [c.get_attribute("data-cue-id") for c in page.locator("#rail article.cue").all()]
    order = [c.cue_id for c in real.timeline(7)]
    assert shown[::-1] == order[: len(shown)]
    assert len(shown) >= 3  # the goal at 04:18, its moment and the window at 05:00
    assert page.locator("#watch").get_attribute("data-state") == "live"
    assert errors == []
    page.close()


# Per rail card, newest first: its cue id, its lines, its fact ids and the ids of its evidence.
RAIL = """() => [...document.querySelectorAll("#rail article.cue")].map((a) => [
  a.dataset.cueId,
  [...a.querySelectorAll(".cue-lines p")].map((p) => p.textContent),
  JSON.parse(a.dataset.factIds),
  [...a.querySelectorAll(".evidence code")].map((c) => c.textContent),
])"""


def test_a_persona_switch_re_renders_the_cards_without_reconnecting(site):
    browser, base = site
    page, errors = open_page(browser)
    streams = []
    page.on("request", lambda r: streams.append(r.url) if "/live?" in r.url else None)
    page.goto(f"{base}/?match=m7&speed=1000&hz=1&persona=fan")
    page.wait_for_selector('#watch[data-state="ended"]', timeout=60_000)
    assert page.title() == "SLT v COR · Footnote"
    cues = real.timeline(7)

    def expected(persona):
        texts = [(c.cue_id, c.rendition(persona)) for c in reversed(cues)]
        return [[i, list(r.lines), list(r.fact_ids), [*r.fact_ids, *r.event_ids]] for i, r in texts]

    def lower():
        return [
            [a.get_attribute("data-cue-id"), a.locator(".cue-lines p").all_text_contents()]
            for a in page.locator("#lower-third article.cue").all()
        ]

    at_end = cues[-2:]  # in the lower third for 10 s after the end, the recap for 20 s
    assert [c.kind for c in at_end] == ["period_end", "recap"]
    differ = [c for c in cues if c.rendition("fan").fact_ids != c.fact_ids]
    # every period end, goal, chance and window; a moment without a run reads the same
    assert len(differ) == 2 + 5 + 10 + 18
    for n, (persona, other) in enumerate(
        (("fan", "analyst"), ("analyst", "fan"), ("fan", "analyst"))
    ):
        if n:  # the first is the page's persona from the URL, before any click
            page.click(f'[data-persona="{persona}"]')
        assert f"persona={persona}" in page.url
        assert page.get_attribute(f'[data-persona="{persona}"]', "aria-pressed") == "true"
        assert page.get_attribute(f'[data-persona="{other}"]', "aria-pressed") == "false"
        assert page.evaluate(RAIL) == expected(persona)
        assert lower() == [[c.cue_id, list(c.rendition(persona).lines)] for c in at_end]
    assert expected("fan") != expected("analyst")
    # a card re-rendered in the lower third still leaves when its time is up
    page.wait_for_function("!document.querySelector('#lower-third article')", timeout=25_000)
    assert streams == [streams[0]] and "persona" not in streams[0]  # one stream, never reopened
    assert errors == []
    page.close()


def test_a_language_switch_re_renders_the_cards_in_slovak_without_reconnecting(site):
    browser, base = site
    page, errors = open_page(browser)
    streams = []
    page.on("request", lambda r: streams.append(r.url) if "/live?" in r.url else None)
    page.goto(f"{base}/?match=m7&speed=1000&hz=1&lang=sk&persona=fan")
    page.wait_for_selector('#watch[data-state="ended"]', timeout=60_000)
    cues = real.timeline(7)

    def expected(persona, lang):
        texts = [(c.cue_id, c.translated(persona, lang)) for c in reversed(cues)]
        return [[i, list(r.lines), list(r.fact_ids), [*r.fact_ids, *r.event_ids]] for i, r in texts]

    # every cue has its Slovak lines: no run, so the moments are stats-only in Slovak words
    assert all(c.translated(p, "sk").lang == "sk" for c in cues for p in ("analyst", "fan"))
    for persona, lang in (("fan", "sk"), ("fan", "en"), ("analyst", "en"), ("analyst", "sk")):
        if (persona, lang) != ("fan", "sk"):  # the first is the page's from the URL
            page.click(f'[data-persona="{persona}"]')
            page.click(f'[data-lang="{lang}"]')
        assert f"lang={lang}" in page.url and f"persona={persona}" in page.url
        other = "en" if lang == "sk" else "sk"
        assert page.get_attribute(f'[data-lang="{lang}"]', "aria-pressed") == "true"
        assert page.get_attribute(f'[data-lang="{other}"]', "aria-pressed") == "false"
        assert page.evaluate(RAIL) == expected(persona, lang)
        langs = page.eval_on_selector_all("#rail .cue-lines", "(a) => a.map((n) => n.lang)")
        assert set(langs) == {lang}
    rail = page.evaluate(RAIL)
    assert any(lines[:1] == ["Polčas"] for _, lines, *_ in rail)
    assert any(lines[0].startswith("Kľúčový moment · ") for _, lines, *_ in rail)
    assert expected("analyst", "sk") != expected("analyst", "en")
    assert streams == [streams[0]] and "lang" not in streams[0]  # one stream, never reopened
    assert errors == []
    page.close()


ACCENT = "getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()"
# where the accent colours text (app.js `ACCENT_SURFACES`) and the verified chip's tint of it
SURFACES = """() => {
  const style = getComputedStyle(document.documentElement);
  return [["--bg", "--panel", "--moment"].map((n) => style.getPropertyValue(n).trim()),
    parseFloat(style.getPropertyValue("--chip-tint")) / 100];
}"""
_CSS = (WEB_DIR / "app.css").read_text()
DEFAULT_ACCENT = re.search(r"--accent: (#[0-9a-f]{6});", _CSS)[1]
NEUTRAL = re.search(r"--neutral: (#[0-9a-f]{6});", _CSS)[1]
MIN_CONTRAST = 4.5  # WCAG AA for text

Channels = tuple[float, ...]


def channels(colour: str) -> Channels:
    """`#rrggbb` as (r, g, b) in 0..255."""
    return tuple(int(colour[i : i + 2], 16) for i in (1, 3, 5))


def contrast(a: Channels, b: Channels) -> float:
    """WCAG 2.x contrast ratio of two colours."""

    def luminance(c: Channels) -> float:
        s = [x / 255 for x in c]
        linear = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in s]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def over(top: Channels, alpha: float, under: Channels) -> Channels:
    """`top` at `alpha` over an opaque `under`."""
    return tuple(u + (t - u) * alpha for t, u in zip(top, under, strict=True))


def worst(colour: Channels, surfaces: list[str], tint: float) -> float:
    """The lowest contrast of `colour` as text on the surfaces and on its chip on each."""
    under = [channels(s) for s in surfaces]
    return min(contrast(colour, s) for s in [*under, *(over(colour, tint, s) for s in under)])


def readable(colour: str, surfaces: list[str], tint: float) -> str:
    """The oracle of the page's accent: `colour`, else its first mix with white in 5% steps that
    reads on every surface and chip (channels rounded half up, as JS does)."""
    for step in range(21):
        mixed = tuple(int(c + (255 - c) * step / 20 + 0.5) for c in channels(colour))
        if worst(mixed, surfaces, tint) >= MIN_CONTRAST:
            return "#" + "".join(f"{c:02x}" for c in mixed)
    raise AssertionError("white does not read on the surfaces")


def css_colour(value: str) -> tuple[Channels, float]:
    """A computed colour, `rgb(r, g, b)`, `rgba(r, g, b, a)` or `color(srgb r g b / a)`, as
    (r, g, b) in 0..255 and its alpha."""
    numbers = [float(x) for x in re.findall(r"[0-9.]+", value)]
    if value.startswith("color(srgb"):
        rgb, alpha = numbers[:3], numbers[3] if len(numbers) > 3 else 1.0
        return tuple(c * 255 for c in rgb), alpha
    return tuple(numbers[:3]), numbers[3] if len(numbers) > 3 else 1.0


# Every card in the rail that is not stepped back: its chip's text on the chip over the card, and
# a moment's or the recap's header on the card, as the browser computes them.
ACCENT_TEXT = """() => [...document.querySelectorAll("#rail article.cue:not(.theirs)")].map((a) => {
  const style = (n) => getComputedStyle(n);
  const chip = a.querySelector(".chip"), head = a.querySelector(".cue-lines p");
  return { id: a.dataset.cueId, card: style(a).backgroundColor, chip: style(chip).color,
    tint: style(chip).backgroundColor, head: style(head).color, kind: a.className };
})"""


def accent_contrasts(page) -> list[tuple[str, float]]:
    """(what, contrast) of every accent text on a card in the rail, measured in the browser."""
    found = []
    for card in page.evaluate(ACCENT_TEXT):
        under, _ = css_colour(card["card"])
        chip, _ = css_colour(card["chip"])
        tint, alpha = css_colour(card["tint"])
        found.append((f"{card['id']} chip", contrast(chip, over(tint, alpha, under))))
        if "cue-moment" in card["kind"] or "cue-recap" in card["kind"]:
            found.append((f"{card['id']} header", contrast(css_colour(card["head"])[0], under)))
    return found


def club(team: str):
    return next(c for c in load_league().clubs if c.id == team)


def rail_ids(page, selector: str = "article.cue") -> list[str]:
    return page.eval_on_selector_all(f"#rail {selector}", "(a) => a.map((n) => n.dataset.cueId)")


def border(page, cue_id: str) -> Channels:
    style = f'#rail article[data-cue-id="{cue_id}"]'
    return css_colour(page.eval_on_selector(style, "(a) => getComputedStyle(a).borderLeftColor"))[0]


def test_a_favourite_club_s_cues_lead_the_rail_and_the_other_club_s_step_back(site):
    browser, base = site
    page, errors = open_page(browser)
    page.goto(f"{base}/?match=m7&speed=1000&hz=1&team=cor")
    page.wait_for_selector('#watch[data-state="ended"]', timeout=60_000)
    newest = list(reversed(real.timeline(7)))
    mine = [c.cue_id for c in newest if c.team == "cor"]
    theirs = [c.cue_id for c in newest if c.team == "slt"]
    rest = [c.cue_id for c in newest if c.team != "cor"]
    assert mine and theirs and len(rest) > len(theirs)  # cues of no team are in the rest too
    assert page.inner_text(".rail h2") == "Cues · COR first"
    assert page.get_attribute(".brand", "href") == "/?team=cor"
    for _ in range(2):  # as the cues came, then after a persona switch drew the rail anew
        assert rail_ids(page) == mine + rest
        assert rail_ids(page, "article.cue.mine") == mine
        assert rail_ids(page, "article.cue.theirs") == theirs
        page.click('[data-persona="fan"]')
    assert "team=cor" in page.url and "persona=fan" in page.url
    # every card of the other club is marked as theirs in the lower third too, as it came
    assert page.evaluate("window.__lowerTheirs") == list(reversed(theirs))

    def opacity(cue_id: str) -> str:
        return page.eval_on_selector(
            f'#rail article[data-cue-id="{cue_id}"]', "(a) => getComputedStyle(a).opacity"
        )

    no_team = next(c.cue_id for c in newest if c.team is None)
    assert [opacity(i) for i in (mine[0], theirs[0], no_team)] == ["1", "0.5", "1"]
    page.hover(f'#rail article[data-cue-id="{theirs[0]}"]')
    assert opacity(theirs[0]) == "1"
    page.focus(f'#rail article[data-cue-id="{theirs[1]}"] .chip')  # from the keyboard too
    assert opacity(theirs[1]) == "1"
    # over the pitch every card of the other club read at full strength when it came
    assert page.evaluate("window.__lowerTheirsOpacity") == ["1"] * len(theirs)
    # a card of no team keeps the page's own colour, not the favourite's
    assert border(page, no_team) == channels(NEUTRAL) != channels(page.evaluate(ACCENT))
    assert border(page, mine[0]) == channels(club("cor").primary_colour)
    # COR's navy is too dark to read on the page: the accent is its first readable lighter mix
    accent, (surfaces, tint) = page.evaluate(ACCENT), page.evaluate(SURFACES)
    primary = club("cor").primary_colour
    assert worst(channels(primary), surfaces, tint) < MIN_CONTRAST
    assert accent == readable(primary, surfaces, tint) != primary.lower()
    # as the browser draws it: every chip and header in the accent reads, on every card not
    # stepped back
    measured = accent_contrasts(page)
    assert len({what.split()[0] for what, _ in measured}) == len(newest) - len(theirs)
    assert min(c for _, c in measured) >= MIN_CONTRAST, measured
    # the verified chip is tinted with the accent: `color(srgb r g b / 0.15)`
    tint_seen, alpha = css_colour(
        page.eval_on_selector("#rail .chip", "(c) => getComputedStyle(c).backgroundColor")
    )
    assert "#" + "".join(f"{round(c):02x}" for c in tint_seen) == accent and alpha == tint
    assert errors == []
    page.close()


def test_a_club_that_does_not_play_the_match_is_no_favourite_there(site):
    browser, base = site
    page, errors = open_page(browser)
    page.goto(f"{base}/?match=m7&speed=1000&hz=1&team=vel")
    page.wait_for_selector('#watch[data-state="ended"]', timeout=60_000)
    newest = list(reversed(real.timeline(7)))
    assert rail_ids(page) == [c.cue_id for c in newest]
    assert rail_ids(page, "article.cue.mine, article.cue.theirs") == []
    assert page.evaluate("window.__lowerTheirs") == []
    assert page.evaluate(ACCENT) == DEFAULT_ACCENT
    assert page.inner_text(".rail h2") == "Cues"
    assert page.get_attribute(".brand", "href") == "/?team=vel"  # still the viewer's club
    no_team = next(c.cue_id for c in newest if c.team is None)
    assert border(page, no_team) == channels(NEUTRAL)
    assert errors == []
    page.close()


def test_the_picker_chooses_a_favourite_club_for_the_page_and_its_matches(site):
    browser, base = site
    page, errors = open_page(browser)
    page.goto(f"{base}/?team=xyz")  # no club of the league: no favourite
    page.wait_for_selector("#match-list:not([aria-busy])")
    link = page.locator("#match-list a")
    surfaces, tint = page.evaluate(SURFACES)

    def pressed() -> list[str]:
        return page.eval_on_selector_all(
            '#club-list button[aria-pressed="true"]', "(b) => b.map((n) => n.dataset.team)"
        )

    def state() -> tuple:
        return pressed(), link.get_attribute("href"), page.url, page.get_attribute(".brand", "href")

    teams = page.eval_on_selector_all("#club-list button", "(b) => b.map((n) => n.dataset.team)")
    assert teams == [c.id for c in load_league().clubs]
    assert state() == ([], "/?match=m7", f"{base}/", "/")
    assert page.evaluate(ACCENT) == DEFAULT_ACCENT
    for team, href in (
        ("slt", "/?match=m7&team=slt"),  # the home club of m7
        ("cor", "/?match=m7&team=cor"),  # its away club
        ("vel", "/?match=m7"),  # no club of m7: the page takes its colour, the match link not
    ):
        page.click(f'[data-team="{team}"]')
        assert state() == ([team], href, f"{base}/?team={team}", f"/?team={team}")
        assert page.evaluate(ACCENT) == readable(club(team).primary_colour, surfaces, tint)
        # the pressed button's name reads on its button, as the browser draws it
        button = f'[data-team="{team}"]'
        text = page.eval_on_selector(button, "(b) => getComputedStyle(b).color")
        under = page.eval_on_selector(button, "(b) => getComputedStyle(b).backgroundColor")
        assert contrast(css_colour(text)[0], css_colour(under)[0]) >= MIN_CONTRAST, team
    assert page.evaluate(ACCENT) != club("vel").primary_colour.lower()  # claret, made readable
    page.click('[data-team="vel"]')  # again: no favourite
    assert state() == ([], "/?match=m7", f"{base}/", "/")
    assert page.evaluate(ACCENT) == DEFAULT_ACCENT
    page.click('[data-team="qrd"]')
    assert page.evaluate(ACCENT) == "#ffffff"  # QRD's white reads as it is
    page.click('[data-team="slt"]')
    orange = readable(club("slt").primary_colour, surfaces, tint)
    assert orange != club("slt").primary_colour.lower()  # too dark on a moment's chip
    link.click()
    page.wait_for_selector('#watch[data-state="live"]', timeout=30_000)
    assert "match=m7" in page.url and "team=slt" in page.url
    assert page.evaluate(ACCENT) == orange
    assert page.get_attribute(".brand", "href") == "/?team=slt"
    page.click('[data-speed="60"]')  # a speed switch keeps the favourite
    assert "speed=60" in page.url and "team=slt" in page.url
    assert errors == []
    page.close()


def test_the_accent_keeps_a_colour_that_reads_and_lightens_one_a_unit_below(site):
    """The greys on both sides of MIN_CONTRAST on the worst of the page's surfaces and chips."""
    browser, base = site
    page, errors = open_page(browser)
    page.goto(base)
    page.wait_for_selector("#match-list:not([aria-busy])")
    surfaces, tint = page.evaluate(SURFACES)
    grey = [f"#{n:02x}{n:02x}{n:02x}" for n in range(256)]
    n = next(n for n in range(256) if worst(channels(grey[n]), surfaces, tint) >= MIN_CONTRAST)
    below, on = (worst(channels(grey[i]), surfaces, tint) for i in (n - 1, n))
    assert below < MIN_CONTRAST <= on
    accent = "([colour, surfaces, tint]) => readable(colour, surfaces, tint)"
    assert page.evaluate(accent, [grey[n], surfaces, tint]) == grey[n]
    lighter = page.evaluate(accent, [grey[n - 1], surfaces, tint])
    assert lighter == readable(grey[n - 1], surfaces, tint) != grey[n - 1]
    assert errors == []
    page.close()


def test_picker_opens_a_match(site):
    browser, base = site
    page, errors = open_page(browser)
    page.goto(base)
    page.wait_for_selector("#match-list:not([aria-busy])")
    link = page.locator("#match-list a")
    assert link.count() == 1
    assert link.inner_text().startswith("Saltreach FC v Corrowmere Athletic")
    link.click()
    page.wait_for_selector('#watch[data-state="live"]', timeout=30_000)
    assert page.locator("#picker").is_hidden()
    assert page.get_attribute('[data-speed="30"]', "aria-pressed") == "true"
    assert errors == []
    page.close()


def test_unknown_match_says_so(site):
    browser, base = site
    page, errors = open_page(browser)
    page.goto(f"{base}/?match=nope&team=cor")
    page.wait_for_selector('#watch[data-state="error"]')
    assert page.locator("#loading").inner_text() == "This match could not be loaded."
    assert page.get_attribute(".brand", "href") == "/?team=cor"  # back to the picker, still COR
    assert all("404" in e for e in errors), errors  # only the browser's note on the 404
    page.close()


# --- a cut stream: the browser reconnects by itself, the page reopens a closed one --------------

LIVE = "**/matches/m7/live?*"
REOPEN_MS = [1000, 2000, 4000, 8000, 16000]
# what Chromium logs for a cut stream, a stopped server and a 503; any other error fails a test
NETWORK = re.compile(
    r"Failed to load resource: (net::ERR_INCOMPLETE_CHUNKED_ENCODING|net::ERR_CONNECTION_REFUSED"
    r"|the server responded with a status of 503 \(Service Unavailable\))"
)


def until(page, check, timeout_s=10.0):
    """Waits for `check()` in steps that let Playwright run the page's events and routes (a
    `time.sleep` would hold them; `wait_for_function` polls with the page's timers, which a
    paused clock stops)."""
    deadline = time.monotonic() + timeout_s
    while not check():
        assert time.monotonic() < deadline, "timed out"
        page.wait_for_timeout(25)


def shown_clock(page):
    return page.text_content("#clock")


def pose(page):
    """What the pitch shows: every player's place, the ball's and the clock."""
    return page.evaluate("""() => [
      ...[...document.querySelectorAll("#players g")].map((g) => g.getAttribute("transform")),
      ["cx", "cy"].map((a) => document.querySelector("#ball").getAttribute(a)).join(),
      document.querySelector("#clock").textContent,
    ]""")


def assert_last_frame_shown(page):
    """Everyone stands where the last frame the page got puts them: at 1 Hz the frame of the
    clock shown (the page draws only as its clock moves on, so check after a wait)."""
    at = clock_ms(shown_clock(page))
    frame = next(real.match(7).frames(1000, (1, at)))
    assert (frame.period, frame.clock_ms) == (1, at)
    shown = page.evaluate("""() => Object.fromEntries([...document.querySelectorAll("#players g")]
      .map((g) => [g.dataset.player, g.getAttribute("transform")]))""")
    assert shown == {p.player: f"translate({p.x:.2f} {p.y:.2f})" for p in frame.players}
    ball = page.locator("#ball")
    assert (ball.get_attribute("cx"), ball.get_attribute("cy")) == (
        f"{frame.ball.x:.2f}",
        f"{frame.ball.y:.2f}",
    )


def assert_resumed(page):
    """Every reconnect went on after the last message seen: at 1 Hz the clock showed each second
    from 00:00 once, in order (no frame lost, none twice), and the cards are the timeline's first
    cues in order, each once."""
    clocks = [clock_ms(c) for c in page.evaluate("window.__clocks")]
    assert clocks == list(range(0, 1000 * len(clocks), 1000)), clocks
    shown = [c.get_attribute("data-cue-id") for c in page.locator("#rail article.cue").all()]
    order = [c.cue_id for c in real.timeline(7)]
    assert shown[::-1] == order[: len(shown)]
    return shown


def test_reopen_waits_double_up_to_16_s_then_it_gives_up(site):
    browser, base = site
    page, errors = open_page(browser)
    page.goto(base)
    delays = page.evaluate("[0, 1, 2, 3, 4, 5, 6].map(reopenDelay)")
    assert delays == [*REOPEN_MS, None, None]  # 4: the last wait, 5: the first refusal
    assert errors == []
    page.close()


def test_a_restarted_server_resumes_the_stream(warm):
    """A stop cuts the stream; the browser retries by itself against the closed port, the page
    keeps the last frame, and the restarted server resumes after the browser's Last-Event-ID."""
    browser, server, base = warm
    page, errors = open_page(browser)
    requests = []
    page.on("request", lambda r: requests.append(r) if "/live?" in r.url else None)
    page.goto(f"{base}/?match=m7&speed=120&hz=1")
    page.wait_for_function("document.querySelector('#clock').textContent >= '04:30'")
    server.stop()  # the open stream runs 1 s more, then breaks off
    page.wait_for_selector('#watch[data-state="reconnecting"]')
    assert page.text_content("#status") == "Reconnecting…"
    cards_at_cut = page.locator("#rail article.cue").count()
    page.wait_for_timeout(1200)  # a retry of the browser fails meanwhile
    assert_last_frame_shown(page)  # the last frame stays on screen
    held = pose(page)
    server.start()
    page.wait_for_selector('#watch[data-state="live"]')
    page.wait_for_function("document.querySelector('#clock').textContent >= '10:30'")

    assert "data-state=error" not in page.evaluate("window.__watch")
    resumed = requests[-1].all_headers().get("last-event-id")
    assert "last_event_id" not in requests[-1].url  # the browser's own reconnect, by header
    item = next(i for i in live_items() if i.id == resumed)
    assert display_clock(item.period, item.clock_ms) == held[-1]
    shown = assert_resumed(page)
    assert 0 < cards_at_cut < len(shown)  # cards on both sides of the cut
    assert errors and all(NETWORK.fullmatch(e) for e in errors), errors
    page.close()


def test_a_closed_stream_is_reopened_with_backoff_until_it_gives_up(warm):
    """A 503 closes the browser's source for good: the page reopens it after the last message
    seen, 1, 2, 4, 8 and 16 s later (each pinned 1 ms early and on the dot with a paused clock),
    then says the connection is lost; a meta and a click on a speed start the waits afresh."""
    browser, server, base = warm
    page, errors = open_page(browser)
    page.clock.install()
    requests = []
    page.on("request", lambda r: requests.append(r.url) if "/live?" in r.url else None)
    refused = []

    def refuse(route):
        refused.append(route.request.url)
        route.fulfill(status=503, body="")

    def closings():
        return page.evaluate("window.__watch").count("data-state=reconnecting")

    def wait(ms):
        """Lets the page's next reopen fall due: none 1 ms early, one on the dot."""
        sent = len(requests)
        page.clock.fast_forward(ms - 1)
        page.wait_for_timeout(300)
        assert len(requests) == sent
        page.clock.fast_forward(1)
        until(page, lambda: len(requests) == sent + 1)

    def cut():
        """The stream breaks off and every request gets a 503 until `restore`."""
        page.route(LIVE, refuse)
        server.stop()

    def restore():
        server.start()
        page.unroute(LIVE)

    page.goto(f"{base}/?match=m7&speed=120&hz=1")
    until(page, lambda: shown_clock(page) >= "01:00")
    page.clock.pause_at(page.evaluate("Date.now()") + 1000)

    # two reopens refused, the third gets the restarted server
    cut()
    until(page, lambda: closings() == 2)  # the cut, then the browser's own retry's 503
    assert len(refused) == 1
    wait(REOPEN_MS[0])
    until(page, lambda: closings() == 3)
    restore()
    wait(REOPEN_MS[1])
    until(page, lambda: page.get_attribute("#watch", "data-state") == "live")
    assert len(refused) == 2

    # the meta reset the waits: five reopens from 1 s again, then the page gives up
    until(page, lambda: shown_clock(page) >= "05:30")
    cut()
    for n, ms in enumerate(REOPEN_MS):
        until(page, lambda n=n: closings() == 5 + n)
        assert page.text_content("#status") == "Reconnecting…"
        wait(ms)  # the page draws as the clock moves on: the last frame stays on screen
        assert_last_frame_shown(page)
    until(page, lambda: page.get_attribute("#watch", "data-state") == "error")
    assert page.text_content("#status") == "Connection lost: pick a speed to try again"
    assert page.locator("#loading").inner_text() == "Connection lost: pick a speed to try again."
    assert closings() == 4 + len(REOPEN_MS)
    page.clock.fast_forward(60_000)
    page.wait_for_timeout(300)
    assert len(refused) == 3 + len(REOPEN_MS)  # given up: no more requests

    # a click on a speed tries again with the whole backoff (refused: a reopen waits, the page
    # does not give up); a click while a reopen waits connects at once and drops that reopen
    page.click('[data-speed="30"]')
    until(page, lambda: closings() == 5 + len(REOPEN_MS))
    restore()
    page.click('[data-speed="60"]')
    until(page, lambda: page.get_attribute("#watch", "data-state") == "live")
    assert page.locator("#loading").is_hidden()
    sent = len(requests)
    page.clock.fast_forward(REOPEN_MS[-1])
    page.wait_for_timeout(300)
    assert len(requests) == sent
    until(page, lambda: shown_clock(page) >= "10:30")

    # 1 and 4 are the browser's own retries, by header; the page's reopens and the clicks carry
    # the last id seen in the URL
    assert len(requests) == 12
    assert all("last_event_id=m7-" in url for url in requests[2:4] + requests[5:])
    assert "last_event_id" not in requests[1]
    assert_resumed(page)
    assert errors and all(NETWORK.fullmatch(e) for e in errors), errors
    page.close()


def live_items():
    from matchlens.stream import live_timeline, tracking_ends

    match = real.match(7)
    return live_timeline("m7", match.events, real.timeline(7), tracking_ends(match), 1).items


def test_a_page_refused_at_its_first_stream_tries_again(site):
    """Issue #2: a full replica answers 503 to a new stream. A page opened then tries again on
    the backoff of a reopen and goes live once a slot frees; an unknown match still says at
    once that it could not be loaded."""
    import httpx

    from matchlens.api import LiveLimits

    browser, _ = site
    server = Server(
        lambda: create_app(
            [real.match(7)], cues={"m7": real.timeline(7)}, limits=LiveLimits(max_streams=1)
        )
    )
    base = server.start()
    try:
        url = "/matches/m7/live?speed=1&hz=1"
        with httpx.Client(base_url=base, timeout=10) as client, client.stream("GET", url) as held:
            lines = held.iter_lines()  # hold them: httpx closes a dropped iterator's stream
            assert "event: meta" in itertools.islice(lines, 6)
            page, errors = open_page(browser)
            page.goto(f"{base}/?match=m7&speed=10&hz=1")
            page.wait_for_selector('#watch[data-state="reconnecting"]')
            assert page.locator("#watch").get_attribute("data-state") != "error"
        # the held stream is closed: its slot frees, the next try gets it
        page.wait_for_selector('#watch[data-state="live"]', timeout=20_000)
        assert errors and all("503" in e for e in errors), errors
        page.close()
    finally:
        server.stop()


def test_a_link_the_server_never_serves_says_why_at_once(site):
    """Issue #2: a link past the public limits (1000× at 5 Hz is 5 000 frames a second) is
    refused for good: the page says why at once, with the server's reason, and does not try
    again; a link within them plays."""
    from matchlens.api import LiveLimits

    server = Server(
        lambda: create_app([real.match(7)], cues={"m7": real.timeline(7)}, limits=LiveLimits())
    )
    base = server.start()
    try:
        page, errors = open_page(site[0])
        tries = []
        page.on("request", lambda r: tries.append(r.url) if "/live?" in r.url else None)
        page.goto(f"{base}/?match=m7&speed=1000")
        page.wait_for_selector('#watch[data-state="error"]', timeout=5_000)
        reason = "at most 300 frames a second here: lower speed or hz"
        assert page.text_content("#status") == f"This match could not be loaded: {reason}"
        assert page.text_content("#loading") == f"This match could not be loaded: {reason}."
        page.wait_for_timeout(1_500)  # no reopen: the first reopen would come after 1 s
        assert len(tries) == 2  # the stream, then the page asking the same link why
        assert all("422" in e for e in errors), errors
        page.goto(f"{base}/?match=m7&speed=5000")  # past the API's own bound: a list, no reason
        page.wait_for_selector('#watch[data-state="error"]', timeout=5_000)
        assert page.text_content("#status") == "This match could not be loaded"
        page.goto(f"{base}/?match=m7&speed=60")  # the page's most
        page.wait_for_selector('#watch[data-state="live"]')
        page.close()
    finally:
        server.stop()


def test_a_slot_freed_while_the_page_asks_why_is_taken(site):
    """Issue #2: the first stream is refused with a 503 and the slot frees before the page asks
    why. The ask gets a 200, which the page cuts at once (it would hold the only slot and never
    end), and the reopen goes live."""
    from matchlens.api import LiveLimits

    server = Server(
        lambda: create_app(
            [real.match(7)], cues={"m7": real.timeline(7)}, limits=LiveLimits(max_streams=1)
        )
    )
    base = server.start()
    try:
        page, _ = open_page(site[0])
        streams = []

        def refuse_the_first(route):
            if route.request.resource_type == "eventsource":
                streams.append(route.request.url)
                if len(streams) == 1:
                    route.fulfill(status=503, body="")
                    return
            route.continue_()

        page.route("**/live?*", refuse_the_first)
        page.goto(f"{base}/?match=m7&speed=10")
        page.wait_for_selector('#watch[data-state="live"]', timeout=15_000)
        assert len(streams) == 2, streams  # the refused one, then the reopen
        page.close()
    finally:
        server.stop()


def test_a_late_answer_for_a_replaced_stream_changes_nothing(site):
    """Issue #2: while the page asks why its first stream was refused, a click on a speed opens
    a newer one. The old answer, a 422 that arrives after the new stream is live, is ignored:
    no error, no reopen."""
    from matchlens.api import LiveLimits

    server = Server(
        lambda: create_app([real.match(7)], cues={"m7": real.timeline(7)}, limits=LiveLimits())
    )
    base = server.start()
    try:
        page, errors = open_page(site[0])
        held, streams = [], []

        def hold_the_ask(route):  # the stream goes through; the page's own ask waits
            if route.request.resource_type == "fetch":
                held.append(route)
            else:
                streams.append(route.request.url)
                route.continue_()

        page.route("**/live?*", hold_the_ask)
        page.goto(f"{base}/?match=m7&speed=1000")
        for _ in range(100):  # refused at 5 000 frames a second: the page asks why
            if held:
                break
            page.wait_for_timeout(50)
        assert len(held) == 1, held
        page.click('[data-speed="10"]')
        page.wait_for_selector('#watch[data-state="live"]')
        held[0].continue_()  # the old 422 arrives now
        page.wait_for_timeout(1_500)  # past the first reopen's 1 s
        assert page.locator("#watch").get_attribute("data-state") == "live"
        assert "could not be loaded" not in page.text_content("#status")
        assert len(streams) == 2, streams  # the refused one and the click's: no reopen
        assert all("422" in e for e in errors), errors
        page.close()
    finally:
        server.stop()
