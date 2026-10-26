"""Seeded match generator: a possession-chain state machine over a simple player model.

`random.Random(seed)` drives every choice, so the same seed gives the same match. At every event
the ball carrier and the receivers are placed where the event says; everyone else drifts towards a
4-3-3 formation slot that follows the ball, never faster than FOLLOW_SPEED. Tracking frames are
interpolated between these snapshots, so events and tracking agree by construction.

Realism is modest on purpose: no dribbles past opponents, no cards, substitutions or own goals,
no offside. What is tuned are the match-level numbers: passes, pass accuracy, shots and goals
(see the calibration test).
"""

import math
import random
from dataclasses import dataclass, field

from matchlens.events import (
    HALF_MS,
    MAX_TRAVEL_MS,
    PITCH_LENGTH,
    PITCH_WIDTH,
    Event,
    EventType,
    MatchMeta,
    Outcome,
    Point,
    Restart,
    make_event_id,
    team_of,
)
from matchlens.league import Club, League, load_league
from matchlens.match import (
    CENTRE,
    GOAL_AREA_LENGTH,
    GOAL_HALF_WIDTH,
    PENALTY_AREA_HALF_WIDTH,
    PENALTY_AREA_LENGTH,
    PENALTY_SPOT,
    PLAYER_SPEED_LIMIT,
    Match,
    Snapshot,
    Vec,
    attacking_goal_x,
    validate_match,
)

FOLLOW_SPEED = 6.0  # m/s, drifting to the formation target
CARRY_SPEED = 5.0  # m/s, running with the ball
APPROACH_SPEED = 6.5  # m/s, closing down the ball or a loose ball
PASS_SPEED = (9.0, 22.0)  # m/s
CLEARANCE_SPEED = (15.0, 25.0)
SHOT_SPEED = (18.0, 32.0)
# 4-3-3 in the attacking frame: x towards the goal the team attacks; (group, slot, ball pull)
FORMATION = (
    ("GK", (1.5, 34.0), 0.0),
    ("DF", (20.0, 9.0), 0.4),
    ("DF", (18.0, 25.0), 0.4),
    ("DF", (18.0, 43.0), 0.4),
    ("DF", (20.0, 59.0), 0.4),
    ("MF", (40.0, 17.0), 0.5),
    ("MF", (38.0, 34.0), 0.5),
    ("MF", (40.0, 51.0), 0.5),
    ("FW", (62.0, 12.0), 0.6),
    ("FW", (66.0, 34.0), 0.6),
    ("FW", (62.0, 56.0), 0.6),
)
# pauses before a restart, seconds
PAUSES = {
    Restart.KICK_OFF: (30, 50),
    Restart.GOAL_KICK: (8, 15),
    Restart.CORNER: (15, 30),
    Restart.PENALTY: (30, 50),
    Restart.FREE_KICK: (8, 20),
    Restart.THROW_IN: (5, 12),
}
P_DEFEND = 0.20  # an opponent acts before the holder does
P_PRESSURE, P_TACKLE = 0.68, 0.24  # the rest is a foul
P_THROUGH_BALL = 0.10  # aim for the most advanced teammate instead of the usual choice
P_FOUL_IN_BOX_GIVEN = 0.25  # share of would-be fouls inside the box that are given; the rest
# become a lost tackle, because defenders there pull out of the challenge
KEEPER_REACH = 0.9 * PLAYER_SPEED_LIMIT  # m/s a keeper may need to get to a save
P_OUT_NEAR_TOUCHLINE = 0.35  # share of failed passes near a touchline that cross it
P_REGAIN, P_TACKLE_WON = 0.30, 0.45
P_CLEAR_IN_OWN_THIRD = 0.30
P_CORNER_AFTER_SAVE = 0.45
P_SHOT_FROM_FREE_KICK = 0.35
P_PENALTY_GOAL = 0.76


def generate_match(
    seed: int, home: str | None = None, away: str | None = None, league: League | None = None
) -> Match:
    """A full match from a seed; the same seed, clubs and league give the same match."""
    league = load_league() if league is None else league
    rng = random.Random(seed)
    clubs = {c.id: c for c in league.clubs}
    pair = rng.sample(sorted(clubs), 2)
    chosen = home is not None or away is not None
    if home is None:
        home = next(c for c in pair if c != away)
    if away is None:
        away = next(c for c in pair if c != home)
    for club in (home, away):
        if not isinstance(club, str) or club not in clubs:
            raise ValueError(f"unknown club: {club!r}")
    lineups, slots = {}, {}
    for team in (home, away):
        lineups[team], team_slots = _pick_lineup(rng, clubs[team])
        slots.update(team_slots)
    # one id per seed; clubs picked by hand become part of the id so the two never collide
    match_id = f"m{seed}{home}{away}" if chosen else f"m{seed}"
    meta = MatchMeta(match_id, home, away, lineups[home], lineups[away], seed)
    sim = _Sim(rng=rng, meta=meta, slots=slots)
    sim.run()
    match = Match(meta, tuple(sim.events), tuple(sim.snapshots))
    validate_match(match)  # cheap, and the generator must never hand out an invalid match
    return match


_GROUPS = ("GK", "DF", "MF", "FW")


def _pick_lineup(rng: random.Random, club: Club) -> tuple[tuple[str, ...], dict]:
    """Eleven players for the formation, drawn per position group; slots keyed by player id."""
    pool = {group: sorted(p.id for p in club.players if p.position == group) for group in _GROUPS}
    for group in _GROUPS:
        needed = sum(g == group for g, _, _ in FORMATION)
        if len(pool[group]) < needed:
            raise ValueError(f"{club.id}: {len(pool[group])} {group}, the formation needs {needed}")
        rng.shuffle(pool[group])
    lineup, slots = [], {}
    for group, slot, pull in FORMATION:
        player = pool[group].pop()
        lineup.append(player)
        slots[player] = (group, slot, pull)
    return tuple(lineup), slots


@dataclass
class _Sim:
    rng: random.Random
    meta: MatchMeta
    slots: dict[str, tuple[str, Vec, float]]
    pos: dict[str, Vec] = field(default_factory=dict)
    ball: Vec = CENTRE
    period: int = 1
    t: int = 0
    limit: int = 0
    holder: str = ""
    pending: tuple[Restart, Vec, str] | None = None
    goal: dict[str, float] = field(default_factory=dict)  # player -> x of the goal they attack
    events: list[Event] = field(default_factory=list)
    snapshots: list[Snapshot] = field(default_factory=list)

    # --- driving loop ---------------------------------------------------------------------------

    def run(self) -> None:
        for period in (1, 2):
            self.start_period(period)
            # a penalty awarded in stoppage time is still taken
            while self.t < self.limit or (self.pending or (None,))[0] is Restart.PENALTY:
                self.step()
            self.end_period()

    def start_period(self, period: int) -> None:
        self.period, self.t = period, 0
        self.limit = HALF_MS + self.rng.randint(60, 300) * 1000
        self.ball = CENTRE
        for player in self.everyone:
            self.goal[player] = self.goal_x(team_of(player))
            self.pos[player] = self.target(player)
        kicking = self.meta.home if period == 1 else self.meta.away
        self.pending = (Restart.KICK_OFF, CENTRE, kicking)

    def end_period(self) -> None:
        self.advance(self.rng.randint(1000, 3000), {})
        self.emit(EventType.PERIOD_END)

    def step(self) -> None:
        if self.pending is not None:
            self.take_restart()
            return
        holder = self.holder
        dwell = self.rng.randint(700, 3000)
        self.ball = self.carry(holder, dwell)
        self.advance(dwell, {holder: self.ball})
        defend_chance = P_DEFEND * (0.2 if self.group(holder) == "GK" else 1.0)
        if self.rng.random() < defend_chance:
            self.defend()
            return
        distance = self.distance_to_goal(holder)
        if self.rng.random() < _p_shot(distance):
            self.shoot()
        elif distance > 70 and self.rng.random() < P_CLEAR_IN_OWN_THIRD:
            self.clear()
        else:
            self.pass_()

    # --- the actions ----------------------------------------------------------------------------

    def take_restart(self) -> None:
        kind, where, team = self.pending
        self.pending = None
        group = {Restart.GOAL_KICK: "GK", Restart.KICK_OFF: "FW", Restart.PENALTY: "FW"}.get(kind)
        if group is not None:
            taker = self.rng.choice([p for p in self.lineup(team) if self.group(p) == group])
        elif kind is Restart.FREE_KICK and team_of(self.holder) == team:
            taker = self.holder
        else:
            taker = self.nearest(team, where, outfield=True)
        if self.t == 0:  # the period starts with the taker already on the spot
            self.pos[taker] = where
            pause = 0
        else:
            pause = self.rng.randint(*PAUSES[kind]) * 1000
        pause = max(pause, _ms(math.dist(self.pos[taker], where) / APPROACH_SPEED))
        self.ball = where
        self.advance(pause, {taker: where})
        self.holder = taker
        if kind is Restart.PENALTY or (
            kind is Restart.FREE_KICK
            and self.distance_to_goal(taker) <= 30
            and self.rng.random() < P_SHOT_FROM_FREE_KICK
        ):
            self.shoot(restart=kind)
        else:
            self.pass_(restart=kind)

    def defend(self) -> None:
        holder = self.holder
        team = team_of(holder)
        defender = self.nearest(self.opponent(team), self.ball, outfield=True)
        approach = max(600, _ms(math.dist(self.pos[defender], self.ball) / APPROACH_SPEED))
        self.advance(approach, {holder: self.ball, defender: self.ball})
        in_box = self.in_penalty_area(self.ball, team)
        roll = self.rng.random()
        if roll < P_PRESSURE:
            regained = self.rng.random() < P_REGAIN
            self.act(EventType.PRESSURE, defender, Outcome.REGAIN if regained else Outcome.RESISTED)
            if regained:
                self.holder = defender
        elif roll < P_PRESSURE + P_TACKLE:
            won = self.rng.random() < P_TACKLE_WON
            self.act(EventType.TACKLE, defender, Outcome.WON if won else Outcome.LOST)
            if won:
                self.holder = defender
        elif in_box and self.rng.random() > P_FOUL_IN_BOX_GIVEN:
            self.act(EventType.TACKLE, defender, Outcome.LOST)  # pulled out of the challenge
        else:
            self.act(EventType.FOUL, defender)
            if in_box:
                self.pending = (Restart.PENALTY, self.penalty_spot(team), team)
            else:
                self.pending = (Restart.FREE_KICK, self.ball, team)

    def pass_(self, restart: Restart | None = None) -> None:
        holder = self.holder
        team = team_of(holder)
        goal_x = self.goal_x(team)
        forward = _forward(goal_x)
        own_third = abs(self.ball[0] - goal_x) > 70
        long_ball = restart is Restart.GOAL_KICK and self.rng.random() < 0.5
        ideal = 40.0 if long_ball else 16.0
        mates, weights = [], []
        for mate in self.lineup(team):
            if mate == holder:
                continue
            d = math.dist(self.ball, self.pos[mate])
            w = math.exp(-((d - ideal) ** 2) / 200)
            progress = (self.pos[mate][0] - self.ball[0]) * forward
            w *= 1.6 if progress > 3 else 0.6 if progress < -3 else 1.0
            if self.group(mate) == "GK" and not own_third:
                w *= 0.05
            mates.append(mate)
            weights.append(w + 1e-6)
        if restart is None and self.rng.random() < P_THROUGH_BALL:
            recipient = min(mates, key=lambda p: abs(self.pos[p][0] - goal_x))
        else:
            recipient = self.rng.choices(mates, weights)[0]
        d = math.dist(self.ball, self.pos[recipient])
        into_final_third = abs(self.pos[recipient][0] - goal_x) < 35
        p_complete = max(0.4, 0.93 - 0.005 * max(0.0, d - 8) - (0.06 if into_final_third else 0.0))
        if restart is Restart.CORNER:
            p_complete = 0.35
        self.travel(EventType.PASS, recipient, p_complete, PASS_SPEED, restart)

    def clear(self) -> None:
        holder = self.holder
        team = team_of(holder)
        forward = _forward(self.goal_x(team))
        aim = _clamp(
            (
                self.ball[0] + forward * self.rng.uniform(25, 50),
                self.ball[1] + self.rng.uniform(-20, 20),
            )
        )
        recipient = self.nearest(team, aim, exclude={holder})
        self.travel(EventType.CLEARANCE, recipient, 0.4, CLEARANCE_SPEED, None)

    def travel(
        self,
        kind: EventType,
        recipient: str,
        p_complete: float,
        speeds: tuple[float, float],
        restart: Restart | None,
    ) -> None:
        """A pass or clearance from the holder towards `recipient`, and what it leads to."""
        holder = self.holder
        team = team_of(holder)
        opponent = self.opponent(team)
        start, aim = self.ball, self.pos[recipient]
        speed = self.rng.uniform(*speeds)
        roll = self.rng.random()
        if roll < p_complete:
            end, duration = self.aimed(start, aim, speed, 2.5)
            self.emit_travel(kind, holder, end, duration, Outcome.COMPLETE, restart, recipient)
            self.advance(duration, {holder: start, recipient: end})
            self.holder = recipient
            return
        near_touchline = min(aim[1], PITCH_WIDTH - aim[1]) < 15
        roll = (roll - p_complete) / (1 - p_complete)
        p_out = P_OUT_NEAR_TOUCHLINE if near_touchline else 0.0
        if roll < 0.5 * (1 - p_out):
            interceptor = self.nearest(opponent, aim)
            end, duration = self.aimed(start, self.pos[interceptor], speed, 2.0)
            self.emit_travel(kind, holder, end, duration, Outcome.INCOMPLETE, restart)
            self.advance(duration, {holder: start, interceptor: end})
            self.act(EventType.INTERCEPTION, interceptor)
            self.holder = interceptor
        elif roll < 1 - p_out:  # a loose ball
            short = (
                start[0] + 0.6 * (aim[0] - start[0]) + self.rng.uniform(-2, 2),
                start[1] + 0.6 * (aim[1] - start[1]) + self.rng.uniform(-2, 2),
            )
            end, duration = self.aimed(start, _clamp(short), speed, 0.0)
            self.emit_travel(kind, holder, end, duration, Outcome.INCOMPLETE, restart)
            self.advance(duration, {holder: start})
            self.pick_up(self.nearest(None, end), end)
        else:
            out = (aim[0], 0.0 if aim[1] < CENTRE[1] else PITCH_WIDTH)
            end, duration = self.aimed(start, out, speed, 0.0)
            self.emit_travel(kind, holder, end, duration, Outcome.OUT, restart)
            self.advance(duration, {holder: start})
            self.pending = (Restart.THROW_IN, end, opponent)

    def shoot(self, restart: Restart | None = None) -> None:
        holder = self.holder
        team = team_of(holder)
        opponent = self.opponent(team)
        goal_x = self.goal_x(team)
        inwards = -_forward(goal_x)  # from the goal line into the pitch
        start = self.ball
        distance = self.distance_to_goal(holder)
        keeper = next(p for p in self.lineup(opponent) if self.group(p) == "GK")
        if restart is Restart.PENALTY:
            p_goal, split = P_PENALTY_GOAL, (0.8, 0.0, 0.15, 0.05)
        else:
            p_goal = min(0.6, max(0.02, 0.48 * math.exp(-distance / 10)))
            split = (0.38, 0.30, 0.29, 0.03)
        if self.rng.random() < p_goal:
            outcome = Outcome.GOAL
        else:
            outcome = self.rng.choices(
                [Outcome.SAVED, Outcome.BLOCKED, Outcome.OFF_TARGET, Outcome.WOODWORK], split
            )[0]
        speed = self.rng.uniform(*SHOT_SPEED)
        side = self.rng.choice((-1.0, 1.0))
        if outcome is Outcome.SAVED:
            y = min(
                CENTRE[1] + 3.5,
                max(CENTRE[1] - 3.5, self.pos[keeper][1] + self.rng.uniform(-1.5, 1.5)),
            )
            end, duration = self.aimed(start, (goal_x + inwards, y), speed)
            if math.dist(self.pos[keeper], end) / (duration / 1000) > KEEPER_REACH:
                outcome = Outcome.GOAL  # the keeper is out of position and cannot get there
        if outcome is Outcome.GOAL:
            end, duration = self.aimed(
                start, (goal_x, CENTRE[1] + side * self.rng.uniform(0, 3.4)), speed
            )
            self.emit_travel(EventType.SHOT, holder, end, duration, outcome, restart)
            self.advance(duration, {holder: start})
            # the goal is recorded where the ball crossed the line; the shot says where from
            self.emit_by(EventType.GOAL, holder, end, related=self.events[-1].event_id)
            self.pending = (Restart.KICK_OFF, CENTRE, opponent)
        elif outcome is Outcome.SAVED:
            self.emit_travel(EventType.SHOT, holder, end, duration, outcome, restart)
            self.advance(duration, {holder: start, keeper: end})
            self.act(EventType.SAVE, keeper, related=self.events[-1].event_id)
            if self.rng.random() < P_CORNER_AFTER_SAVE:
                corner = (goal_x, 0.0 if y < CENTRE[1] else PITCH_WIDTH)
                self.pending = (Restart.CORNER, corner, team)
            else:
                self.holder = keeper
        elif outcome is Outcome.BLOCKED:
            blocker = self.nearest(opponent, start, outfield=True)
            end, duration = self.aimed(start, self.pos[blocker], speed, 1.0)
            self.emit_travel(EventType.SHOT, holder, end, duration, outcome, restart)
            self.advance(duration, {holder: start, blocker: end})
            if self.rng.random() < 0.5:
                self.pick_up(self.nearest(team, end), end)
            else:
                self.holder = blocker
                self.clear()
        elif outcome is Outcome.OFF_TARGET:
            wide = (goal_x, CENTRE[1] + side * self.rng.uniform(4.0, 14.0))
            end, duration = self.aimed(start, _clamp(wide), speed)
            self.emit_travel(EventType.SHOT, holder, end, duration, outcome, restart)
            self.advance(duration, {holder: start})
            spot = (goal_x + inwards * GOAL_AREA_LENGTH, CENTRE[1] + self.rng.uniform(-8, 8))
            self.pending = (Restart.GOAL_KICK, _clamp(spot), opponent)
        else:
            end, duration = self.aimed(start, (goal_x, CENTRE[1] + side * GOAL_HALF_WIDTH), speed)
            self.emit_travel(EventType.SHOT, holder, end, duration, outcome, restart)
            self.advance(duration, {holder: start})
            self.pick_up(self.nearest(None, end), end)

    def pick_up(self, player: str, where: Vec) -> None:
        """A loose ball: `player` runs to it while everyone else drifts, and recovers it."""
        wait = max(500, _ms(math.dist(self.pos[player], where) / APPROACH_SPEED))
        self.advance(wait, {player: where})
        self.act(EventType.RECOVERY, player)
        self.holder = player

    # --- geometry and bookkeeping ---------------------------------------------------------------

    def aimed(self, start: Vec, at: Vec, speed: float, lead: float = 0.0) -> tuple[Vec, int]:
        """Where a ball aimed near `at` ends and how long it takes; the receiver can get there."""
        duration = self.flight(start, at, speed)
        reach = min(lead, 0.8 * CARRY_SPEED * duration / 1000)
        angle = self.rng.uniform(0, math.tau)
        r = self.rng.uniform(0, reach)
        end = _clamp((at[0] + r * math.cos(angle), at[1] + r * math.sin(angle)))
        return end, self.flight(start, end, speed)

    @staticmethod
    def flight(start: Vec, end: Vec, speed: float) -> int:
        """Milliseconds the ball takes, kept inside what the schema allows."""
        return max(300, min(MAX_TRAVEL_MS, _ms(math.dist(start, end) / speed)))

    def carry(self, holder: str, dwell: int) -> Vec:
        """Where the holder runs with the ball during `dwell`; keepers stay put."""
        if self.group(holder) == "GK":
            return self.ball
        forward = _forward(self.goal[holder])
        length = min(12.0, self.rng.uniform(0, 1) * CARRY_SPEED * dwell / 1000)
        angle = self.rng.uniform(-math.pi / 3, math.pi / 3)
        return _clamp(
            (
                self.ball[0] + forward * length * math.cos(angle),
                self.ball[1] + length * math.sin(angle),
            )
        )

    def advance(self, dt: int, anchors: dict[str, Vec]) -> None:
        """Time passes: anchored players are placed, the others drift; then a snapshot."""
        self.t += dt
        reach = FOLLOW_SPEED * dt / 1000
        for player in self.pos:
            if player in anchors:
                self.pos[player] = _clamp(anchors[player])
            else:
                self.pos[player] = _towards(self.pos[player], self.target(player), reach)
        self.snapshots.append(
            Snapshot(
                self.period,
                self.t,
                self.ball,
                tuple((p, *self.pos[p]) for p in self.everyone),
            )
        )

    def target(self, player: str) -> Vec:
        """Formation slot in pitch coordinates, pulled towards the ball."""
        group, (sx, sy), pull = self.slots[player]
        goal_x = self.goal[player]
        x = sx if goal_x == PITCH_LENGTH else PITCH_LENGTH - sx
        if group == "GK":
            y = CENTRE[1] + min(6.0, max(-6.0, 0.5 * (self.ball[1] - CENTRE[1])))
        else:
            x += pull * (self.ball[0] - CENTRE[0])
            y = sy + 0.3 * (self.ball[1] - CENTRE[1])
        return _clamp((x, y), 0.5)

    def act(
        self,
        kind: EventType,
        player: str,
        outcome: Outcome | None = None,
        related: str | None = None,
    ) -> None:
        """An on-the-spot event by `player` at the ball."""
        self.emit_by(kind, player, self.ball, outcome=outcome, related=related)

    def emit_travel(
        self,
        kind: EventType,
        player: str,
        end: Vec,
        duration: int,
        outcome: Outcome,
        restart: Restart | None,
        recipient: str | None = None,
    ) -> None:
        """A ball flight by `player` from the ball to `end`, where the ball then is."""
        self.emit_by(
            kind,
            player,
            self.ball,
            end=Point(*end),
            duration_ms=duration,
            outcome=outcome,
            restart=restart,
            recipient=recipient,
        )
        self.ball = end

    def emit_by(self, kind: EventType, player: str, start: Vec, **fields) -> None:
        """An event by `player` for their team, starting at `start`."""
        self.emit(kind, team=team_of(player), player=player, start=Point(*start), **fields)

    def emit(self, kind: EventType, **fields) -> None:
        """An event at the current clock, numbered in emit order."""
        self.events.append(
            Event(
                event_id=make_event_id(self.meta.match_id, len(self.events)),
                period=self.period,
                clock_ms=self.t,
                type=kind,
                **fields,
            )
        )

    @property
    def everyone(self) -> tuple[str, ...]:
        """Both lineups, home first: the player order of every snapshot."""
        return self.meta.home_lineup + self.meta.away_lineup

    def lineup(self, team: str) -> tuple[str, ...]:
        return self.meta.home_lineup if team == self.meta.home else self.meta.away_lineup

    def opponent(self, team: str) -> str:
        return self.meta.away if team == self.meta.home else self.meta.home

    def group(self, player: str) -> str:
        return self.slots[player][0]

    def goal_x(self, team: str) -> float:
        return attacking_goal_x(self.meta, team, self.period)

    def distance_to_goal(self, player: str) -> float:
        return math.dist(self.ball, (self.goal[player], CENTRE[1]))

    def in_penalty_area(self, where: Vec, attacking: str) -> bool:
        goal_x = self.goal_x(attacking)
        return (
            abs(where[0] - goal_x) <= PENALTY_AREA_LENGTH
            and abs(where[1] - CENTRE[1]) <= PENALTY_AREA_HALF_WIDTH
        )

    def penalty_spot(self, attacking: str) -> Vec:
        goal_x = self.goal_x(attacking)
        return (goal_x - _forward(goal_x) * PENALTY_SPOT, CENTRE[1])

    def nearest(
        self, team: str | None, where: Vec, outfield: bool = False, exclude: set[str] = frozenset()
    ) -> str:
        """Closest player of `team` (both teams if None) to `where`."""
        candidates = self.lineup(team) if team else self.everyone
        return min(
            (
                p
                for p in candidates
                if p not in exclude and not (outfield and self.group(p) == "GK")
            ),
            key=lambda p: math.dist(self.pos[p], where),
        )


def _forward(goal_x: float) -> float:
    """+1 when the attacked goal is at x = PITCH_LENGTH, -1 when it is at x = 0."""
    return 1.0 if goal_x == PITCH_LENGTH else -1.0


def _p_shot(distance: float) -> float:
    for limit, p in ((10, 0.35), (18, 0.18), (26, 0.07), (35, 0.03)):
        if distance <= limit:
            return p
    return 0.0


def _ms(seconds: float) -> int:
    return int(round(seconds * 1000))


def _clamp(p: Vec, margin: float = 0.0) -> Vec:
    return (
        round(min(max(p[0], margin), PITCH_LENGTH - margin), 2),
        round(min(max(p[1], margin), PITCH_WIDTH - margin), 2),
    )


def _towards(a: Vec, b: Vec, reach: float) -> Vec:
    d = math.dist(a, b)
    if d <= reach:
        return _clamp(b)
    f = reach / d
    return _clamp((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
