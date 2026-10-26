// Footnote page: a match picker, and a watch view that replays one match from its live SSE
// stream (/matches/{id}/live): players and ball on an SVG pitch, the score, the clock and the
// overlay cues. Every number on a cue comes from the stream; the page only tallies goal events
// for the scoreboard.
//
// Personas (?persona=analyst|fan): a cue carries a rendition per persona besides the analyst's
// own lines. The page keeps every cue it received, so a switch re-renders the rail and the
// cards in the lower third from them, without reconnecting.
//
// Languages (?lang=en|sk): a cue also carries, per language, what each persona reads there
// (a translation that passed the Guard, or the English text where none did). The language
// switch re-renders like the persona switch; the page's own labels stay in English.
//
// A favourite club (?team=vel, chosen in the picker): its cues lead the rail, the other club's
// cards step back there (over the pitch they read at full strength), and the club's colour is
// the page's accent. Cues of no team (windows, half
// and full time, the recap) speak of both clubs: they keep their place, their stripe and full
// colour, only their accent text takes the club's. A club that does not play the match is no
// favourite there.
//
// Latency: each cue is stamped at the start of the next animation frame after its card went in
// (the frame that draws it, before its layout and paint, so a few ms early); the stamps collect in window.matchlensLatency for scripts/measure_latency.py. Browser and server
// read the same clock only on one machine, so the numbers mean something only locally.
"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";
const DEFAULT_SPEED = 30;
const PERSONAS = ["analyst", "fan"];
const LANGS = ["en", "sk"]; // the first is the cues' own language
const SPOTLIGHT_MS = 4000;
const MIN_CONTRAST = 4.5; // WCAG AA for text: the accent colours text
// where the accent colours text: the page, a card or button, a moment's or the recap's card
const ACCENT_SURFACES = ["--bg", "--panel", "--moment"];
const REOPEN_MS = [1000, 2000, 4000, 8000, 16000]; // waits before reopening a closed stream

window.matchlensLatency = [];

// The wait before reopening a stream the server closed `attempt` times in a row since its last
// meta (from 0), or null once the page gives up.
function reopenDelay(attempt) {
  return attempt < REOPEN_MS.length ? REOPEN_MS[attempt] : null;
}

const wallMs = () => performance.timeOrigin + performance.now();

const $ = (selector) => document.querySelector(selector);

function withAttrs(node, attrs, text) {
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
  if (text !== null) node.textContent = text;
  return node;
}

const el = (tag, attrs = {}, text = null) => withAttrs(document.createElement(tag), attrs, text);
const svg = (tag, attrs = {}, text = null) =>
  withAttrs(document.createElementNS(SVG_NS, tag), attrs, text);

async function getJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response.json();
}

function kitDot(club) {
  const dot = el("span", { class: "kit" });
  dot.style.background = club.colours.primary;
  dot.style.borderColor = club.colours.secondary;
  return dot;
}

// --- picker -------------------------------------------------------------------------------------

async function showPicker(clubs, team) {
  const matches = await getJSON("/matches");
  const links = [];
  const list = $("#match-list");
  for (const m of matches) {
    const home = clubs.get(m.home);
    const away = clubs.get(m.away);
    const link = el("a");
    link.append(kitDot(home), el("span", {}, `${home.name} v ${away.name}`), kitDot(away));
    link.append(el("span", { class: "match-id" }, m.match_id));
    links.push([link, m]);
    const item = el("li");
    item.append(link);
    list.append(item);
  }
  const buttons = $("#club-list");
  for (const club of clubs.values()) {
    const button = el("button", { type: "button", "data-team": club.id });
    button.append(kitDot(club), document.createTextNode(club.name));
    button.addEventListener("click", () => choose(team === club.id ? null : club.id));
    buttons.append(button);
  }
  // a match's link carries the favourite only if the club plays it
  function choose(chosen) {
    team = chosen;
    for (const button of buttons.children) {
      button.setAttribute("aria-pressed", String(button.dataset.team === team));
    }
    for (const [link, m] of links) {
      const params = new URLSearchParams({ match: m.match_id });
      if (team === m.home || team === m.away) params.set("team", team);
      link.href = `/?${params}`;
    }
    const params = new URLSearchParams(location.search);
    if (team) params.set("team", team);
    else params.delete("team");
    const query = params.toString();
    history.replaceState(null, "", query ? `/?${query}` : "/");
    setAccent(team && clubs.get(team));
    keepTeam(team);
  }
  choose(team);
  list.removeAttribute("aria-busy");
}

// --- accent -------------------------------------------------------------------------------------

// Relative luminance and contrast ratio as WCAG 2.x defines them, of [r, g, b] in 0..255.
function luminance(channels) {
  const [r, g, b] = channels.map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

// `colour` as text on each of `surfaces` and on the verified chip there (the colour at `tint`
// over the surface): itself if its contrast is at least MIN_CONTRAST on every one, else the
// first of its mixes with white, in steps of 5%, that is (VEL's claret and COR's navy are too
// dark to read on the page).
function readable(colour, surfaces, tint) {
  const base = rgb(colour);
  const under = surfaces.map(rgb);
  let mixed = colour;
  for (let step = 0; step <= 20; step++) {
    const channels = base.map((c) => Math.round(c + ((255 - c) * step) / 20));
    mixed = `#${channels.map((c) => c.toString(16).padStart(2, "0")).join("")}`;
    const chips = under.map((s) => s.map((c, i) => c + (channels[i] - c) * tint));
    if ([...under, ...chips].every((s) => contrast(channels, s) >= MIN_CONTRAST)) break;
  }
  return mixed;
}

// The page's accent: the club's primary colour, made readable where the accent colours text;
// the page's own without a club.
function setAccent(club) {
  const root = document.documentElement;
  root.style.removeProperty("--accent");
  if (!club) return;
  const style = getComputedStyle(root);
  const surfaces = ACCENT_SURFACES.map((name) => style.getPropertyValue(name).trim());
  const tint = parseFloat(style.getPropertyValue("--chip-tint")) / 100;
  root.style.setProperty("--accent", readable(club.colours.primary, surfaces, tint));
}

// The favourite stays on the way back to the picker.
function keepTeam(team) {
  $(".brand").setAttribute("href", team ? `/?${new URLSearchParams({ team })}` : "/");
}

// --- kits ---------------------------------------------------------------------------------------

function rgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function similar(a, b) {
  const [x, y] = [rgb(a), rgb(b)];
  return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]) < 120;
}

// Shirt and number colours of both teams; the away team wears its secondary colour on a clash.
function kits(home, away) {
  const homeKit = { fill: home.colours.primary, text: home.colours.secondary };
  const awayKit = similar(home.colours.primary, away.colours.primary)
    ? { fill: away.colours.secondary, text: away.colours.primary }
    : { fill: away.colours.primary, text: away.colours.secondary };
  return { [home.id]: homeKit, [away.id]: awayKit };
}

// --- watch view ---------------------------------------------------------------------------------

class Watch {
  constructor(matchId, clubs, speed, hz, persona, team, lang) {
    this.matchId = matchId;
    this.clubs = clubs;
    this.speed = speed;
    this.hz = hz;
    this.persona = persona;
    this.lang = lang;
    this.team = team; // the favourite club from the URL; it counts once the match is known
    this.favourite = null; // that club, if it plays this match
    this.cues = []; // every cue received, in arrival order, with its display clock
    this.lower = []; // the cards in the lower third: { cue, clock, node }
    this.players = new Map(); // player id -> its <g> on the pitch
    this.squad = new Map(); // player id -> league player
    for (const club of clubs.values()) for (const p of club.players) this.squad.set(p.id, p);
    this.events = new Map(); // event id -> event, as far as the stream got
    this.emitted = new Map(); // event id -> its message's emitted_at_ms, in arrival order
    this.prev = null; // the two latest frames, for interpolation
    this.curr = null;
    this.score = null;
    this.lastId = null;
    this.source = null;
    this.ready = false;
    this.attempts = 0; // reopens of a closed stream since its last meta
    this.reopenTimer = null;
    this.streamHz = null; // tracking rate of the stream, from its meta
    this.lowerDue = null; // the due moment of the cards in the lower third
    this.spotTimer = null;
  }

  start() {
    $("#picker").hidden = true;
    $("#watch").hidden = false;
    for (const button of document.querySelectorAll("[data-speed]")) {
      button.addEventListener("click", () => this.setSpeed(Number(button.dataset.speed)));
    }
    for (const button of document.querySelectorAll("[data-persona]")) {
      button.addEventListener("click", () => this.setPersona(button.dataset.persona));
    }
    for (const button of document.querySelectorAll("[data-lang]")) {
      button.addEventListener("click", () => this.setLang(button.dataset.lang));
    }
    this.markSpeed();
    this.markPersona();
    this.markLang();
    keepTeam(this.team); // also when the match never loads
    this.connect();
    requestAnimationFrame((t) => this.draw(t));
  }

  setState(state, text) {
    $("#watch").dataset.state = state;
    $("#status").textContent = text;
  }

  markSpeed() {
    for (const button of document.querySelectorAll("[data-speed]")) {
      button.setAttribute("aria-pressed", String(Number(button.dataset.speed) === this.speed));
    }
  }

  markPersona() {
    for (const button of document.querySelectorAll("[data-persona]")) {
      button.setAttribute("aria-pressed", String(button.dataset.persona === this.persona));
    }
  }

  markLang() {
    for (const button of document.querySelectorAll("[data-lang]")) {
      button.setAttribute("aria-pressed", String(button.dataset.lang === this.lang));
    }
  }

  setPersona(persona) {
    if (persona === this.persona) return;
    this.persona = persona;
    this.markPersona();
    this.redraw("persona", persona);
  }

  setLang(lang) {
    if (lang === this.lang) return;
    this.lang = lang;
    this.markLang();
    this.redraw("lang", lang);
  }

  // After a switch of persona or language: the URL keeps it, the rail and the lower third are
  // drawn anew from the cues received.
  redraw(param, value) {
    const params = new URLSearchParams(location.search);
    params.set(param, value);
    history.replaceState(null, "", `/?${params}`);
    clearTimeout(this.spotTimer); // the selected card is drawn anew: no spotlight without it
    $("#highlight").replaceChildren();
    const rail = this.cues.map(({ cue, clock }) => this.railItem(cue, clock)).reverse();
    const mine = (item) => item.classList.contains("mine");
    $("#rail").replaceChildren(...rail.filter(mine), ...rail.filter((item) => !mine(item)));
    for (const shown of this.lower) {
      const node = this.card(shown.cue, shown.clock);
      shown.node.replaceWith(node);
      shown.node = node;
    }
  }

  setSpeed(speed) {
    const state = $("#watch").dataset.state;
    if (state === "ended" || (speed === this.speed && state !== "error")) return;
    this.speed = speed;
    this.markSpeed();
    const params = new URLSearchParams(location.search);
    params.set("speed", String(speed));
    history.replaceState(null, "", `/?${params}`);
    this.attempts = 0; // a click after "Connection lost" gets the whole backoff again
    this.connect(); // resumes after the last message seen, at the new speed
  }

  connect() {
    clearTimeout(this.reopenTimer);
    if (this.source) this.source.close();
    const params = new URLSearchParams({ speed: String(this.speed) });
    if (this.hz) params.set("hz", String(this.hz));
    if (this.lastId) params.set("last_event_id", this.lastId);
    const source = new EventSource(`/matches/${encodeURIComponent(this.matchId)}/live?${params}`);
    const on = (kind, handle) =>
      source.addEventListener(kind, (message) => {
        handle(JSON.parse(message.data));
        if (message.lastEventId) this.lastId = message.lastEventId; // only once handled
      });
    on("meta", (data) => this.onMeta(data));
    on("frame", (data) => this.onFrame(data));
    on("match_event", (data) => this.onEvent(data));
    on("cue", (data) => this.onCue(data));
    on("end", () => this.onEnd());
    // After a network error the browser reconnects by itself (CONNECTING) and resumes with
    // Last-Event-ID; any answer but 200 (a 503 while a replica restarts) closes the source for
    // good, so the page reopens it itself. A stream refused before its first message asks why.
    source.onerror = () => {
      if (source.readyState === EventSource.CONNECTING && this.ready) {
        this.setState("reconnecting", "Reconnecting…");
      } else if (source.readyState === EventSource.CLOSED && !this.ready) {
        this.refusedFirst(source);
      } else if (source.readyState === EventSource.CLOSED) {
        this.reopen();
      }
    };
    this.source = source;
  }

  // A stream refused before its first message: the page asks the same link why. An unknown
  // match (404) or a link the server never serves (422: too slow, too many frames a second)
  // says so at once, with the server's reason; a full replica (503) or a lost connection is
  // tried again as a reopen. A newer stream opened meanwhile (a click on a speed) wins.
  async refusedFirst(source) {
    let status = 0;
    let detail = "";
    const asked = new AbortController();
    try {
      const response = await fetch(source.url, { signal: asked.signal });
      status = response.status;
      if (status === 200) asked.abort(); // a share freed meanwhile: no need to read on
      else {
        const body = await response.json();
        detail = typeof body.detail === "string" ? body.detail : ""; // FastAPI's own: a list
      }
    } catch (error) {
      if (status === 0) console.error(error); // offline: a reopen tries again
    }
    if (source !== this.source) return;
    if (status === 404 || status === 422) {
      const why = status === 422 && detail ? `: ${detail}` : "";
      this.setState("error", `This match could not be loaded${why}`);
      $("#loading").textContent = `This match could not be loaded${why}.`;
      return;
    }
    this.reopen();
  }

  // Reopens a stream closed before its end after the last message seen, the last frame staying
  // on screen meanwhile; waits longer each time, then gives up.
  reopen() {
    const wait = reopenDelay(this.attempts);
    if (wait === null) {
      this.setState("error", "Connection lost: pick a speed to try again");
      $("#loading").textContent = "Connection lost: pick a speed to try again.";
      return;
    }
    this.attempts += 1;
    this.setState("reconnecting", "Reconnecting…");
    this.reopenTimer = setTimeout(() => this.connect(), wait);
  }

  onMeta(data) {
    if (!this.ready) this.setup(data.meta);
    this.ready = true;
    this.attempts = 0;
    this.streamHz = data.hz;
    this.setState("live", `Live · ${this.speed}×`);
  }

  setup(meta) {
    const home = this.clubs.get(meta.home);
    const away = this.clubs.get(meta.away);
    this.home = meta.home;
    this.away = meta.away;
    this.favourite = [meta.home, meta.away].includes(this.team) ? this.team : null;
    setAccent(this.favourite && this.clubs.get(this.favourite));
    if (this.favourite) {
      $(".rail h2").textContent = `Cues · ${this.clubs.get(this.favourite).short_name} first`;
    }
    this.score = { [meta.home]: 0, [meta.away]: 0 };
    $("#home-name").replaceChildren(kitDot(home), document.createTextNode(home.name));
    $("#away-name").replaceChildren(document.createTextNode(away.name), kitDot(away));
    document.title = `${home.short_name} v ${away.short_name} · Footnote`;
    const colours = kits(home, away);
    const layer = $("#players");
    for (const [team, lineup] of [[meta.home, meta.home_lineup], [meta.away, meta.away_lineup]]) {
      for (const id of lineup) {
        const node = svg("g", { class: "player", "data-player": id, transform: "translate(-10 -10)" });
        const shirt = svg("circle", { r: "1.6", fill: colours[team].fill, stroke: colours[team].text });
        const { number, name } = this.squad.get(id);
        const label = svg("text", { fill: colours[team].text }, String(number));
        node.append(shirt, label, svg("title", {}, name));
        layer.append(node);
        this.players.set(id, node);
      }
    }
    this.renderScore();
  }

  renderScore() {
    $("#score").textContent = `${this.score[this.home]}–${this.score[this.away]}`;
  }

  onFrame(frame) {
    const positions = new Map(frame.players.map(([id, x, y]) => [id, [x, y]]));
    this.prev = this.curr;
    this.curr = { positions, ball: frame.ball, at: performance.now() };
    $("#clock").textContent = frame.display_clock;
  }

  onEvent(data) {
    const event = data.event;
    this.events.set(event.event_id, event);
    this.emitted.set(event.event_id, data.emitted_at_ms);
    if (event.type === "goal") {
      this.score[event.team] += 1;
      this.renderScore();
    }
  }

  onCue(data) {
    const cue = data.cue;
    const clock = data.display_clock;
    this.cues.push({ cue, clock });
    // newest first: the favourite's cues at the top, every other cue at the top of the rest
    const rail = $("#rail");
    const item = this.railItem(cue, clock);
    const mine = item.classList.contains("mine");
    rail.insertBefore(item, mine ? rail.firstElementChild : rail.querySelector("li:not(.mine)"));
    // cues due together (a goal and the moment that explains it) share the lower third
    const shown = { cue, clock, node: this.card(cue, clock) };
    const due = cue.due.join(":");
    if (due === this.lowerDue) {
      $("#lower-third").append(shown.node);
      this.lower.push(shown);
    } else {
      $("#lower-third").replaceChildren(shown.node);
      this.lower = [shown];
    }
    this.lowerDue = due;
    setTimeout(() => {
      shown.node.remove();
      this.lower = this.lower.filter((s) => s !== shown);
    }, cue.ttl_ms);
    this.stamp(cue, data.emitted_at_ms);
  }

  railItem(cue, clock) {
    const item = el("li");
    if (this.side(cue) === "mine") item.classList.add("mine");
    item.append(this.card(cue, clock));
    return item;
  }

  // Whose a cue is for a favourite club: "mine", "theirs" (the other club's), or null for a cue
  // of no team or a page without a favourite.
  side(cue) {
    if (!this.favourite || !cue.team) return null;
    return cue.team === this.favourite ? "mine" : "theirs";
  }

  // What the current persona reads of a cue in the current language: its lines there, else
  // its rendition, else the analyst's lines.
  rendition(cue) {
    return this.translation(cue) || (cue.renditions && cue.renditions[this.persona]) || cue;
  }

  // The current persona's lines of a cue in the current language, if the cue has them.
  translation(cue) {
    const there = cue.translations && cue.translations[this.lang];
    return (there && there[this.persona]) || null;
  }

  // The cue's trigger is the last of its events to arrive, else the cue message itself (a
  // window's numbers have no event): latency counts from the trigger, delivery from the cue.
  stamp(cue, cueEmitted) {
    const cited = new Set(cue.event_ids);
    let trigger = cue.cue_id;
    for (const id of this.emitted.keys()) if (cited.has(id)) trigger = id;
    const from = trigger === cue.cue_id ? cueEmitted : this.emitted.get(trigger);
    requestAnimationFrame(() => {
      const shown = wallMs();
      window.matchlensLatency.push({
        cue_id: cue.cue_id,
        kind: cue.kind,
        trigger,
        latency_ms: shown - from,
        delivery_ms: shown - cueEmitted,
      });
    });
  }

  onEnd() {
    this.source.close();
    this.setState("ended", "Full time");
  }

  card(cue, clock) {
    const text = this.rendition(cue);
    const card = el("article", {
      class: `cue cue-${cue.kind}`,
      "data-cue-id": cue.cue_id,
      "data-fact-ids": JSON.stringify(text.fact_ids),
    });
    if (cue.team && this.clubs.has(cue.team)) {
      card.style.setProperty("--team", this.clubs.get(cue.team).colours.primary);
    }
    const side = this.side(cue);
    if (side) card.classList.add(side);
    const chip = el("button", { type: "button", class: "chip", "aria-expanded": "false" }, "✓ verified");
    const head = el("div", { class: "cue-head" });
    head.append(el("span", {}, clock), chip);
    const lang = this.translation(cue) ? this.lang : LANGS[0]; // an English text stands in
    const lines = el("div", { class: "cue-lines", lang });
    for (const line of text.lines) lines.append(el("p", {}, line));
    const evidence = el("dl", { class: "evidence", hidden: "" });
    for (const [label, ids] of [["Facts", text.fact_ids], ["Events", text.event_ids]]) {
      if (!ids.length) continue;
      const values = el("dd");
      for (const id of ids) values.append(el("code", {}, id));
      evidence.append(el("dt", {}, label), values);
    }
    chip.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = evidence.hidden;
      evidence.hidden = !open;
      chip.setAttribute("aria-expanded", String(open));
    });
    const where = this.location(cue);
    if (where) {
      card.classList.add("locatable");
      card.addEventListener("click", () => this.spotlight(where, card));
    }
    card.append(head, lines, evidence);
    return card;
  }

  // Where a cue happened: the first of its events with a location, else its anchor.
  location(cue) {
    for (const id of cue.event_ids) {
      const event = this.events.get(id);
      if (event && event.start) return [event.start.x, event.start.y];
    }
    return cue.anchor;
  }

  spotlight(where, card) {
    for (const selected of document.querySelectorAll(".cue.selected")) selected.classList.remove("selected");
    const layer = $("#highlight");
    layer.replaceChildren();
    clearTimeout(this.spotTimer);
    card.classList.add("selected");
    const [x, y] = where;
    layer.append(
      svg("circle", { class: "spotlight", cx: x, cy: y, r: "3" }),
      svg("circle", { class: "spotlight pulse", cx: x, cy: y, r: "3" }),
    );
    this.spotTimer = setTimeout(() => {
      layer.replaceChildren();
      card.classList.remove("selected");
    }, SPOTLIGHT_MS);
  }

  // Players and ball between the two latest frames, by the time since the latest arrived.
  draw(now) {
    if (this.curr) {
      const interval = 1000 / (this.streamHz * this.speed);
      const t = this.prev ? Math.min(1, (now - this.curr.at) / interval) : 1;
      const lerp = (a, b) => (a && b ? [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t] : b);
      for (const [id, node] of this.players) {
        const to = this.curr.positions.get(id);
        if (!to) continue;
        const [x, y] = lerp(this.prev && this.prev.positions.get(id), to);
        node.setAttribute("transform", `translate(${x.toFixed(2)} ${y.toFixed(2)})`);
      }
      const [bx, by] = lerp(this.prev && this.prev.ball, this.curr.ball);
      withAttrs($("#ball"), { cx: bx.toFixed(2), cy: by.toFixed(2) }, null);
    }
    requestAnimationFrame((t) => this.draw(t));
  }
}

async function main() {
  const league = await getJSON("/league");
  const clubs = new Map(league.clubs.map((c) => [c.id, c]));
  const params = new URLSearchParams(location.search);
  const team = clubs.has(params.get("team")) ? params.get("team") : null;
  const matchId = params.get("match");
  if (!matchId) return showPicker(clubs, team);
  const speed = Number(params.get("speed")) || DEFAULT_SPEED;
  const hz = Number(params.get("hz")) || null;
  const persona = PERSONAS.includes(params.get("persona")) ? params.get("persona") : PERSONAS[0];
  const lang = LANGS.includes(params.get("lang")) ? params.get("lang") : LANGS[0];
  new Watch(matchId, clubs, speed, hz, persona, team, lang).start();
}

main().catch((error) => {
  const list = $("#match-list");
  list.removeAttribute("aria-busy");
  list.replaceChildren(el("li", {}, "The matches could not be loaded."));
  console.error(error);
});
