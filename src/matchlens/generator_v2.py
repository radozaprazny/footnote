"""Generator v2: generator v1's possession-chain decisions over players who move.

`random.Random(seed)` drives every decision, so the same seed gives the same match. The decisions
are v1's (`matchlens.generator`, which stays as submitted): who acts, how, with what outcome; a
few of their constants are re-tuned (the dwell, the duel's odds, the pass's weights, the odds of a
shot and of a failed pass going out) so that the match-level numbers stay in the calibration's
ranges with the players where they now stand. What changes is where everyone is: all 22 players
are bodies that take a 100 ms step at a time under their own limits, tired late in a half
(`matchlens.movement`), towards the aims of `matchlens.targets` in play and of
`matchlens.setpieces` at a restart; the ball is at its carrier's feet, in flight on a straight
line, or resting. So every event happens on the 100 ms grid where the bodies are: a pass ends at
its receiver, an interception where the interceptor gets to the ball's path, a save at the
keeper, a challenge with the ball at the challenger's feet; a loose ball goes to the first player
who can reach it, and a restart is played only once nobody breaks the Laws
(`setpieces.breaches`). Every step is kept as a frame of the match's `Tracking`, to the
centimetre, as are the events' points.
"""

import math
import random
from array import array
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace

from matchlens.events import (
    FRAME_MS,
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
from matchlens.formations import FORMATIONS, ROLE_GROUP, Slot
from matchlens.league import Club, League, Player, load_league
from matchlens.match import (
    CENTRE,
    GOAL_AREA_LENGTH,
    GOAL_HALF_WIDTH,
    PENALTY_SPOT,
    Match,
    Tracking,
    Vec,
    attacking_goal_x,
    validate_match,
)
from matchlens.movement import (
    ARRIVED_M,
    DT,
    FATIGUE_FROM_S,
    FATIGUE_FULL_S,
    Body,
    Limits,
    step,
    time_to_reach,
)
from matchlens.setpieces import breaches, in_penalty_area, layout
from matchlens.targets import Aim, Moment, Team, band, targets

STEP_MS = FRAME_MS  # one step of the movement layer: the tracking's 100 ms
REFRESH_EVERY = 3  # steps between two refreshes of the aims in play, unless the play changes
DWELL_STEPS = (10, 40)  # how long a carrier keeps the ball before he acts, in steps
CARRY_SPEED = 5.0  # m/s, the most a carry covers per second of the dwell
CARRY_MAX = 12.0  # m
PASS_SPEED = (9.0, 22.0)  # m/s
CLEARANCE_SPEED = (15.0, 25.0)
SHOT_SPEED = (18.0, 32.0)
MIN_FLIGHT_MS = 300
# pauses before a restart, seconds; the restart also waits for the Laws and its taker
PAUSES = {
    Restart.KICK_OFF: (30, 50),
    Restart.GOAL_KICK: (8, 15),
    Restart.CORNER: (15, 30),
    Restart.PENALTY: (30, 50),
    Restart.FREE_KICK: (8, 20),
    Restart.THROW_IN: (5, 12),
}
DUEL_M = 1.5  # an opponent this near the ball may challenge its carrier
P_DUEL = 0.30  # the odds he does, once per carry, the first time one is that near
KEEPER_DUEL = 0.2  # a keeper with the ball is challenged at this share of those odds
P_PRESSURE, P_TACKLE = 0.68, 0.24  # the rest is a foul
P_THROUGH_BALL = 0.10  # aim for the most advanced teammate instead of the usual choice
# a pass's recipient is drawn by weight: a bell round the ideal distance (a long goal kick's
# further), times AHEAD for a mate more than 3 m nearer the goal, BEHIND for one more than 3 m
# further from it, KEEPER_PASS for the keeper outside the own third
PASS_IDEAL, LONG_IDEAL, PASS_SPREAD = 20.0, 40.0, 200.0
AHEAD, BEHIND, KEEPER_PASS = 6.0, 0.25, 0.05
P_FOUL_IN_BOX_GIVEN = 0.25  # share of would-be fouls inside the box that are given; the rest
# become a lost tackle, because defenders there pull out of the challenge
P_OUT_NEAR_TOUCHLINE = 0.60  # share of failed passes near a touchline that cross it
P_REGAIN, P_TACKLE_WON = 0.30, 0.45
P_CLEAR_IN_OWN_THIRD = 0.30
P_CORNER_AFTER_SAVE = 0.45
P_SHOT_FROM_FREE_KICK = 0.35
P_PENALTY_GOAL = 0.76
SHOT_ODDS = ((10, 0.50), (18, 0.32), (26, 0.10), (35, 0.03))  # (metres from goal, odds) a carrier
# shoots at; beyond the last, never
INTERCEPT_FROM = 0.2  # the share of a ball's path nearest its kicker that no opponent cuts out
CONTROL_M = 0.75  # a player this near a resting ball takes it (the band's corner lies 0.71 off)
RECOVER_AFTER_MS = 500  # a loose ball is recovered no sooner after it lands
GLIDE_SPEED = 8.0  # m/s, the ball rolled back to a restart's spot
MAX_DEAD_MS = 120_000  # a restart never waits longer: everyone reaches his point well within it
MAX_LOOSE_MS = 60_000  # nor does a loose ball


def generate_match_v2(
    seed: int, home: str | None = None, away: str | None = None, league: League | None = None
) -> Match:
    """A full match from a seed; the same seed, clubs and league give the same match. Its ids are
    v1's (`m<seed>`, with the clubs when chosen by hand)."""
    sim = _new_sim(seed, home, away, league)
    sim.run()
    tracking = Tracking(sim.everyone, tuple(sim.frames[p].tobytes() for p in (1, 2)))
    match = Match(sim.meta, tuple(sim.events), (), tracking)
    validate_match(match, {pid: p.top_speed for pid, p in sim.players.items()})
    return match


def _new_sim(
    seed: int, home: str | None = None, away: str | None = None, league: League | None = None
) -> "_Sim":
    """The clubs, their lineups and the simulation of their match, before its kick-off."""
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
    if home == away:
        raise ValueError(f"home and away are both {home}")
    sides = {team: pick_lineup(rng, clubs[team]) for team in (home, away)}
    lineups = {team: (keeper, *slots) for team, (slots, keeper) in sides.items()}
    match_id = f"m{seed}{home}{away}" if chosen else f"m{seed}"
    meta = MatchMeta(match_id, home, away, lineups[home], lineups[away], seed)
    players = {p.id: p for team in (home, away) for p in clubs[team].players}
    players = {pid: players[pid] for pid in (*lineups[home], *lineups[away])}
    return _Sim(rng=rng, meta=meta, clubs=clubs, sides=sides, players=players)


def pick_lineup(rng: random.Random, club: Club) -> tuple[dict[str, Slot], str]:
    """Per slot of the club's formation a player of the slot's role, of its side if one is free,
    else of another side, else of the role's group (a group's substitute covers the group, not
    each role); then a keeper. Drawn in a shuffled order; returns the slots by player id and the
    keeper."""
    free = sorted(club.players, key=lambda p: p.id)
    rng.shuffle(free)
    slots: dict[str, Slot] = {}
    for slot in FORMATIONS[club.formation]:
        tests = (
            lambda p, s=slot: p.role == s.role and p.side == s.side,
            lambda p, s=slot: p.role == s.role,
            lambda p, s=slot: ROLE_GROUP[p.role] == ROLE_GROUP[s.role],
        )
        pick = next((p for test in tests for p in free if test(p)), None)
        if pick is None:
            raise ValueError(f"{club.id}: no player left for a {slot.role} of {club.formation}")
        free.remove(pick)
        slots[pick.id] = slot
    keeper = next((p.id for p in free if p.role == "GK"), None)
    if keeper is None:
        raise ValueError(f"{club.id}: no keeper")
    return slots, keeper


@dataclass
class _Sim:
    rng: random.Random
    meta: MatchMeta
    clubs: dict[str, Club]
    sides: dict[str, tuple[dict[str, Slot], str]]  # club -> its slots and its keeper
    players: dict[str, Player]  # the 22, as in the league
    bodies: dict[str, Body] = field(default_factory=dict)
    teams: tuple[Team, ...] = ()
    ball: Vec = CENTRE
    carrier: str | None = None
    carry: tuple[Vec, float] | None = None  # where the carrier carries the ball, at what pace
    runner: tuple[str, Vec, int] | None = None  # who runs to meet the ball, where, by when (ms)
    flight: tuple[Vec, Vec, int, int] | None = None  # from, to, from ms, to ms
    glide: tuple[Vec, Vec, int] | None = None  # the ball rolls from, to, since (ms)
    possession: str | None = None
    period: int = 1
    t: int = 0
    limit: int = 0
    pending: tuple[Restart, Vec, str, str | None] | None = None  # kind, spot, team, taker
    aims: dict[str, Aim] = field(default_factory=dict)
    fixed: bool = False  # the aims are a restart's layout, kept until it is taken
    due: bool = True  # the play changed: refresh the aims at the next step
    since: int = 0  # steps since the aims were refreshed
    marks: dict[str, str] = field(default_factory=dict)
    limits: dict[str, Limits] = field(default_factory=dict)  # tired, this second of the half
    tired: dict[str, Player] = field(default_factory=dict)  # the players with those limits
    second: int = -1
    events: list[Event] = field(default_factory=list)
    frames: dict[int, array] = field(default_factory=dict)  # per period, the tracking's values
    framed: int = -1  # the clock of the period's last frame

    # --- driving loop ---------------------------------------------------------------------------

    def run(self) -> None:
        for period in (1, 2):
            self.start_period(period)
            # a penalty awarded in stoppage time is still taken
            while self.t < self.limit or (self.pending or (None,))[0] is Restart.PENALTY:
                self.play()
            self.end_period()

    def start_period(self, period: int) -> None:
        self.period, self.t, self.second = period, 0, -1
        self.frames[period], self.framed = array("h"), -1
        self.limit = HALF_MS + self.rng.randint(60, 300) * 1000
        self.teams = tuple(
            Team(self.clubs[c], *self.sides[c], attacking_goal_x(self.meta, c, period) > 0)
            for c in (self.meta.home, self.meta.away)
        )
        self.bodies = {pid: Body(*CENTRE) for pid in self.everyone}  # placed by the kick-off
        self.ball, self.carrier, self.marks = CENTRE, None, {}
        kicking = self.meta.home if period == 1 else self.meta.away
        self.pending = (Restart.KICK_OFF, CENTRE, kicking, None)

    def end_period(self) -> None:
        for _ in range(self.rng.randint(10, 30)):
            self.tick()
        self.snap()
        self.emit(EventType.PERIOD_END)

    def play(self) -> None:
        """One action: a restart, or a carry and what the carrier then does."""
        if self.pending is not None:
            self.restart()
            return
        holder = self.carrier
        steps = self.rng.randint(*DWELL_STEPS)
        self.carry = self.carry_target(holder, steps * STEP_MS)
        self.due = True
        odds = P_DUEL * (KEEPER_DUEL if self.group(holder) == "goal" else 1.0)
        rolled = False
        for _ in range(steps):
            self.tick()
            rival = self.challenger(holder)
            if rival is not None and not rolled:
                rolled = True
                if self.rng.random() < odds:
                    self.defend(rival)
                    return
        distance = self.distance_to_goal(holder)
        if self.rng.random() < _p_shot(distance):
            self.shoot()
        elif distance > 70 and self.rng.random() < P_CLEAR_IN_OWN_THIRD:
            self.clear()
        else:
            self.pass_()

    # --- the actions ----------------------------------------------------------------------------

    def restart(self) -> None:
        """The ball rolls to the spot while everyone takes his place for the restart; it is played
        once the pause is over, the taker (and at a penalty the keeper) is on his point and nobody
        breaks the Laws. A taker on a touchline or a flag and a keeper on his line at a penalty
        are put there, as the band keeps every aim half a metre inside."""
        kind, spot, team, taker = self.pending
        self.pending, self.marks = None, {}
        taking, other = self.team(team), self.team(self.opponent(team))
        taker = taker or self.taker(kind, spot, team)
        self.aims = layout(kind, spot, taker, taking, other, self.positions(), self.tired_now())
        self.fixed = True
        self.carrier = self.carry = self.runner = self.flight = self.possession = None
        if self.t == 0:  # the period starts with everyone on his point
            self.bodies = {pid: Body(*aim.point) for pid, aim in self.aims.items()}
            self.ball, pause = spot, 0
        else:
            self.glide = (self.ball, spot, self.t)
            pause = self.rng.randint(*PAUSES[kind]) * 1000
        waiting = (taker, other.keeper) if kind is Restart.PENALTY else (taker,)
        start = self.t
        while (
            self.t - start < pause
            or self.ball != spot
            or any(math.dist(self.at(p), self.aims[p].point) >= ARRIVED_M for p in waiting)
            or breaches(kind, spot, taker, taking, other, self.positions())
        ):
            if self.t - start > MAX_DEAD_MS:
                raise AssertionError(f"{self.meta.match_id}: a {kind} at {spot} never got ready")
            self.tick()
        self.glide, self.fixed = None, False
        self.bodies[taker] = Body(*spot)
        if kind is Restart.PENALTY:
            goal_line = PITCH_LENGTH if taking.attacks_right else 0.0
            self.bodies[other.keeper] = Body(goal_line, self.at(other.keeper)[1])
        self.ball = spot
        self.take(taker)
        if kind is Restart.PENALTY or (
            kind is Restart.FREE_KICK
            and self.distance_to_goal(taker) <= 30
            and self.rng.random() < P_SHOT_FROM_FREE_KICK
        ):
            self.shoot(restart=kind)
        else:
            self.pass_(restart=kind)

    def defend(self, rival: str) -> None:
        """`rival` challenges the carrier: the ball is at his feet for the challenge, and back
        at the carrier's on the next step if he keeps it."""
        holder = self.carrier
        team = team_of(holder)
        self.ball = self.at(rival)
        self.snap()
        in_box = in_penalty_area(self.ball, self.goal_x(team) == PITCH_LENGTH)
        roll = self.rng.random()
        if roll < P_PRESSURE:
            regained = self.rng.random() < P_REGAIN
            self.act(EventType.PRESSURE, rival, Outcome.REGAIN if regained else Outcome.RESISTED)
            if regained:
                self.take(rival)
        elif roll < P_PRESSURE + P_TACKLE:
            won = self.rng.random() < P_TACKLE_WON
            self.act(EventType.TACKLE, rival, Outcome.WON if won else Outcome.LOST)
            if won:
                self.take(rival)
        elif in_box and self.rng.random() > P_FOUL_IN_BOX_GIVEN:
            self.act(EventType.TACKLE, rival, Outcome.LOST)  # pulled out of the challenge
        else:
            self.act(EventType.FOUL, rival)
            if in_box:
                self.stop(Restart.PENALTY, self.penalty_spot(team), team)
            else:
                self.stop(Restart.FREE_KICK, self.ball, team, holder)
        if self.carrier == holder:  # he kept it: from here on the ball is at his feet again
            self.ball = self.at(holder)

    def pass_(self, restart: Restart | None = None) -> None:
        holder = self.carrier
        team = team_of(holder)
        goal_x = self.goal_x(team)
        forward = _forward(goal_x)
        own_third = abs(self.ball[0] - goal_x) > 70
        long_ball = restart is Restart.GOAL_KICK and self.rng.random() < 0.5
        ideal = LONG_IDEAL if long_ball else PASS_IDEAL
        mates, weights = [], []
        for mate in self.lineup(team):
            if mate == holder:
                continue
            d = math.dist(self.ball, self.at(mate))
            w = math.exp(-((d - ideal) ** 2) / PASS_SPREAD)
            progress = (self.at(mate)[0] - self.ball[0]) * forward
            w *= AHEAD if progress > 3 else BEHIND if progress < -3 else 1.0
            if self.group(mate) == "goal" and not own_third:
                w *= KEEPER_PASS
            mates.append(mate)
            weights.append(w + 1e-6)
        speed = self.rng.uniform(*PASS_SPEED)
        if restart is None and self.rng.random() < P_THROUGH_BALL:
            first = min(mates, key=lambda p: abs(self.at(p)[0] - goal_x))
            rest = [(m, w) for m, w in zip(mates, weights, strict=True) if m != first]
            candidates = _chain([first], self.drawn(*zip(*rest, strict=True)))
        else:
            candidates = self.drawn(mates, weights)
        recipient, landing, ms = self.reachable(candidates, speed)
        d = math.dist(self.ball, landing)
        into_final_third = abs(landing[0] - goal_x) < 35
        p_complete = max(0.4, 0.93 - 0.005 * max(0.0, d - 8) - (0.06 if into_final_third else 0.0))
        if restart is Restart.CORNER:
            p_complete = 0.35
        self.travel(EventType.PASS, recipient, landing, ms, p_complete, speed, restart)

    def clear(self) -> None:
        holder = self.carrier
        team = team_of(holder)
        forward = _forward(self.goal_x(team))
        aim = band(
            (
                self.ball[0] + forward * self.rng.uniform(25, 50),
                self.ball[1] + self.rng.uniform(-20, 20),
            )
        )
        recipient = self.first_to(aim, [p for p in self.lineup(team) if p != holder])
        speed = self.rng.uniform(*CLEARANCE_SPEED)
        recipient, landing, ms = self.reachable([recipient], speed)
        self.travel(EventType.CLEARANCE, recipient, landing, ms, 0.4, speed, None)

    def travel(
        self,
        kind: EventType,
        recipient: str,
        landing: Vec,
        ms: int,
        p_complete: float,
        speed: float,
        restart: Restart | None,
    ) -> None:
        """A pass or clearance from the carrier towards `landing`, where `recipient` gets to in
        `ms`, and what it leads to."""
        holder = self.carrier
        team = team_of(holder)
        opponent = self.opponent(team)
        start, t0 = self.ball, self.t
        self.snap()
        self.possession = team
        roll = self.rng.random()
        if roll < p_complete:
            self.fly(landing, ms, runner=recipient, caught=True)
            self.emit_travel(kind, holder, start, t0, Outcome.COMPLETE, restart, recipient)
            self.take(recipient)
            return
        near_touchline = min(landing[1], PITCH_WIDTH - landing[1]) < 15
        roll = (roll - p_complete) / (1 - p_complete)
        p_out = P_OUT_NEAR_TOUCHLINE if near_touchline else 0.0
        if roll < 0.5 * (1 - p_out):
            interceptor, point, ms = self.cut_out(start, landing, speed, self.lineup(opponent))
            self.fly(point, ms, runner=interceptor, caught=True)
            self.emit_travel(kind, holder, start, t0, Outcome.INCOMPLETE, restart)
            self.act(EventType.INTERCEPTION, interceptor)
            self.take(interceptor)
        elif roll < 1 - p_out:  # a loose ball
            short = band(
                (
                    start[0] + 0.6 * (landing[0] - start[0]) + self.rng.uniform(-2, 2),
                    start[1] + 0.6 * (landing[1] - start[1]) + self.rng.uniform(-2, 2),
                )
            )
            recoverer = self.first_to(short, self.everyone)
            self.fly(short, _flight_ms(start, short, speed), runner=recoverer)
            self.emit_travel(kind, holder, start, t0, Outcome.INCOMPLETE, restart)
            self.pick_up(recoverer)
        else:
            out = (landing[0], 0.0 if landing[1] < CENTRE[1] else PITCH_WIDTH)
            self.fly(out, _flight_ms(start, out, speed))
            self.emit_travel(kind, holder, start, t0, Outcome.OUT, restart)
            self.stop(Restart.THROW_IN, out, opponent)

    def shoot(self, restart: Restart | None = None) -> None:
        holder = self.carrier
        team = team_of(holder)
        opponent = self.opponent(team)
        goal_x = self.goal_x(team)
        inwards = -_forward(goal_x)  # from the goal line into the pitch
        start, t0 = self.ball, self.t
        distance = self.distance_to_goal(holder)
        keeper = self.sides[opponent][1]
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
        self.snap()
        self.possession = team
        if outcome is Outcome.SAVED:
            y = min(
                CENTRE[1] + 3.5,
                max(CENTRE[1] - 3.5, self.at(keeper)[1] + self.rng.uniform(-1.5, 1.5)),
            )
            save = band(_nearest_on(start, (goal_x + inwards, y), self.at(keeper)))
            ms = _flight_ms(start, save, speed)
            if not self.reaches_save(keeper, save, ms):
                outcome = Outcome.GOAL  # the keeper is out of position and cannot get there
        if outcome is Outcome.GOAL:
            end = (goal_x, CENTRE[1] + side * self.rng.uniform(0, 3.4))
            self.fly(end, _flight_ms(start, end, speed))
            self.emit_travel(EventType.SHOT, holder, start, t0, outcome, restart)
            # the goal is recorded where the ball crossed the line; the shot says where from
            self.emit_by(EventType.GOAL, holder, self.ball, related=self.events[-1].event_id)
            self.stop(Restart.KICK_OFF, CENTRE, opponent)
        elif outcome is Outcome.SAVED:
            self.fly(save, ms, runner=keeper, caught=True)
            self.emit_travel(EventType.SHOT, holder, start, t0, outcome, restart)
            self.act(EventType.SAVE, keeper, related=self.events[-1].event_id)
            if self.rng.random() < P_CORNER_AFTER_SAVE:
                corner = (goal_x, 0.0 if self.ball[1] < CENTRE[1] else PITCH_WIDTH)
                self.stop(Restart.CORNER, corner, team)
            else:
                self.take(keeper)
        elif outcome is Outcome.BLOCKED:
            outfield = [p for p in self.lineup(opponent) if self.group(p) != "goal"]
            blocker, point, ms = self.cut_out(start, (goal_x, CENTRE[1]), speed, outfield)
            self.fly(point, ms, runner=blocker, caught=True)
            self.emit_travel(EventType.SHOT, holder, start, t0, outcome, restart)
            if self.rng.random() < 0.5:
                self.pick_up(self.first_to(self.ball, self.lineup(team)))
            else:
                self.take(blocker)
                self.clear()
        elif outcome is Outcome.OFF_TARGET:
            wide = (goal_x, CENTRE[1] + side * self.rng.uniform(4.0, 14.0))
            self.fly(wide, _flight_ms(start, wide, speed))
            self.emit_travel(EventType.SHOT, holder, start, t0, outcome, restart)
            spot = (goal_x + inwards * GOAL_AREA_LENGTH, CENTRE[1] + self.rng.uniform(-8, 8))
            self.stop(Restart.GOAL_KICK, spot, opponent)
        else:
            post = (goal_x, CENTRE[1] + side * GOAL_HALF_WIDTH)
            recoverer = self.first_to(post, self.everyone)
            self.fly(post, _flight_ms(start, post, speed), runner=recoverer)
            self.emit_travel(EventType.SHOT, holder, start, t0, outcome, restart)
            self.pick_up(recoverer)

    def pick_up(self, player: str) -> None:
        """A loose ball rests where it landed; `player` runs to it and recovers it once he is
        within CONTROL_M, no sooner than RECOVER_AFTER_MS after it landed."""
        landed, where = self.t, self.ball
        self.possession = None
        self.runner = (player, where, landed)
        self.due = True
        while self.t - landed < RECOVER_AFTER_MS or not self.reached(player, where):
            if self.t - landed > MAX_LOOSE_MS:
                raise AssertionError(f"{self.meta.match_id}: {player} never reached the ball")
            self.tick()
        self.runner = None
        self.ball = self.at(player)
        self.snap()
        self.act(EventType.RECOVERY, player)
        self.take(player)

    # --- the movement ---------------------------------------------------------------------------

    def tick(self) -> None:
        """100 ms pass: everyone takes a step towards his aim, then the ball follows. Where they
        are when the step starts is the frame of its clock, unless a snapshot was taken then."""
        if self.framed != self.t:
            self.snap()
        self.tired_now()
        if not self.fixed and (self.due or self.since >= REFRESH_EVERY):
            at = self.positions()
            velocity = {pid: (b.vx, b.vy) for pid, b in self.bodies.items()}
            self.aims = targets(
                self.moment(), self.teams, at, velocity, self.tired, self.meta.seed, self.marks
            )
            self.marks = {pid: a.mark for pid, a in self.aims.items() if a.mark is not None}
            self.due, self.since = False, 0
        lag = self.since * DT  # an aim that moves has moved on since it was set
        for pid, body in self.bodies.items():
            aim = self.aims[pid]
            vx, vy = aim.velocity
            point = (aim.point[0] + vx * lag, aim.point[1] + vy * lag)
            self.bodies[pid] = step(
                body, point, aim.pace, self.limits[pid], aim.velocity, aim.braking
            )
        self.since += 1
        self.t += STEP_MS
        if self.carrier is not None:
            self.ball = self.at(self.carrier)
        elif self.flight is not None:
            (x0, y0), (x1, y1), t0, t1 = self.flight
            f = min(1.0, (self.t - t0) / (t1 - t0))
            self.ball = (x0 + (x1 - x0) * f, y0 + (y1 - y0) * f)
        elif self.glide is not None:
            # from where it rolls by the time elapsed, so its arrival lies on the grid exactly
            (x0, y0), (x1, y1), t0 = self.glide
            d = math.hypot(x1 - x0, y1 - y0)
            rolled = GLIDE_SPEED * (self.t - t0) / 1000
            f = 1.0 if rolled >= d else rolled / d
            self.ball = (x1, y1) if f == 1.0 else (x0 + (x1 - x0) * f, y0 + (y1 - y0) * f)

    def fly(self, end: Vec, ms: int, runner: str | None = None, caught: bool = False) -> None:
        """The ball flies from where it is to `end` in `ms` while `runner` runs to meet it; it
        ends at `end`, or at the runner's feet if he `caught` it."""
        t0 = self.t
        self.carrier = self.carry = None
        self.flight = (self.ball, end, t0, t0 + ms)
        self.runner = (runner, end, t0 + ms) if runner is not None else None
        self.due = True
        while self.t < t0 + ms:
            self.tick()
        self.flight = self.runner = None
        self.ball = self.at(runner) if caught else end
        self.snap()

    def moment(self) -> Moment:
        runner, landing, lands = None, None, 0.0
        if self.runner is not None:
            runner, landing, at_ms = self.runner
            lands = max(DT, (at_ms - self.t) / 1000)
        carry_to, pace = None, 0.0
        if self.carrier is not None:
            carry_to, pace = self.carry or (self.ball, 0.0)
        return Moment(
            self.ball,
            self.possession,
            self.t / 1000,
            self.carrier,
            carry_to,
            pace,
            runner,
            landing,
            lands,
            self.period,
        )

    def tired_now(self) -> dict[str, Player]:
        """The players with their limits at this second of the half (fatigue changes slowly, and
        only between FATIGUE_FROM_S and FATIGUE_FULL_S: outside it the second is clamped, so the
        limits are worked out again only when they can change)."""
        second = min(max(self.t // 1000, FATIGUE_FROM_S), FATIGUE_FULL_S)
        if second != self.second:
            self.second = second
            self.limits = {
                pid: Limits(p.top_speed, p.acceleration).tired(p.stamina, second)
                for pid, p in self.players.items()
            }
            self.tired = {
                pid: replace(p, top_speed=lim.top_speed, acceleration=lim.acceleration)
                for pid, p in self.players.items()
                for lim in (self.limits[pid],)
            }
        return self.tired

    # --- who gets where -------------------------------------------------------------------------

    def reaches_save(self, keeper: str, save: Vec, ms: int) -> bool:
        """Whether `keeper` gets to `save` in a shot's `ms` at his own top speed (v1's reach
        rule, with his top speed in place of v1's KEEPER_REACH)."""
        return math.dist(self.at(keeper), save) / (ms / 1000) <= self.limits[keeper].top_speed

    def reached(self, player: str, ball: Vec) -> bool:
        """Whether `player` is near enough a resting ball to take it."""
        return math.dist(self.at(player), ball) <= CONTROL_M

    def carry_target(self, holder: str, dwell_ms: int) -> tuple[Vec, float]:
        """Where the carrier runs with the ball during `dwell_ms`, and how fast; keepers stay."""
        if self.group(holder) == "goal":
            return self.ball, 0.0
        forward = _forward(self.goal_x(team_of(holder)))
        length = min(CARRY_MAX, self.rng.uniform(0, 1) * CARRY_SPEED * dwell_ms / 1000)
        angle = self.rng.uniform(-math.pi / 3, math.pi / 3)
        to = band(
            (
                self.ball[0] + forward * length * math.cos(angle),
                self.ball[1] + length * math.sin(angle),
            )
        )
        return to, length / (dwell_ms / 1000)

    def challenger(self, holder: str) -> str | None:
        """The opponent nearest the ball, a keeper never, if within DUEL_M of it."""
        rivals = [p for p in self.lineup(self.opponent(team_of(holder))) if self.group(p) != "goal"]
        d, rival = min((math.dist(self.at(p), self.ball), p) for p in rivals)
        return rival if d <= DUEL_M else None

    def led(self, recipient: str, speed: float) -> tuple[Vec, int, bool]:
        """Where a ball kicked at `speed` first meets `recipient` if he runs on as he runs now:
        at the earliest step at which it can be where he then is (it flies that long, so never
        faster than kicked), inside the band; its flight in ms; and whether he gets there by
        running on (the band did not cut his lead short). A runner the ball never catches within
        the schema's longest flight is met where he is by then, not by running on."""
        b = self.bodies[recipient]
        for ms in range(MIN_FLIGHT_MS, MAX_TRAVEL_MS + 1, STEP_MS):
            lead = (b.x + b.vx * ms / 1000, b.y + b.vy * ms / 1000)
            landing = band(lead)
            if math.dist(self.ball, landing) <= speed * ms / 1000:
                return landing, ms, landing == lead
        return landing, MAX_TRAVEL_MS, False

    def reachable(self, candidates: Iterable[str], speed: float) -> tuple[str, Vec, int]:
        """The first candidate who can be on his led landing when the ball gets there (`led`):
        by running on, or else by `time_to_reach`, which stops him there; if none can, the
        first, with the ball played as slowly as he needs (within the schema's longest
        flight)."""
        first = None
        for recipient in candidates:
            landing, ms, running_on = self.led(recipient, speed)
            first = first or (recipient, landing, ms)
            if running_on or self.in_time(recipient, landing, ms):
                return recipient, landing, ms
        recipient, landing, ms = first
        need = time_to_reach(
            self.bodies[recipient], landing, self.limits[recipient], within_s=MAX_TRAVEL_MS / 1000
        )
        return recipient, landing, min(MAX_TRAVEL_MS, max(ms, _ceil_ms(min(need, MAX_TRAVEL_MS))))

    def in_time(self, player: str, point: Vec, ms: int) -> bool:
        """Whether `player` can be on `point` (stopped there) within `ms`."""
        limits = self.limits[player]
        return time_to_reach(self.bodies[player], point, limits, within_s=ms / 1000) <= ms / 1000

    def cut_out(
        self, start: Vec, end: Vec, speed: float, candidates: Iterable[str]
    ) -> tuple[str, Vec, int]:
        """Of `candidates`, the one who first gets to the ball's path from `start` to `end` (to
        his nearest point on it beyond INTERCEPT_FROM of its length), that point, and when the
        ball gets there in ms: at its speed, or later if he needs longer."""
        best = None
        for pid in candidates:
            point = band(_nearest_on(start, end, self.at(pid), INTERCEPT_FROM))
            ball_s = math.dist(start, point) / speed
            his_s = time_to_reach(
                self.bodies[pid], point, self.limits[pid], within_s=MAX_TRAVEL_MS / 1000
            )
            key = (max(ball_s, his_s), pid)
            if best is None or key < best[0]:
                best = (key, point)
        (when, pid), point = best
        ms = min(MAX_TRAVEL_MS, max(MIN_FLIGHT_MS, _ceil_ms(min(when, MAX_TRAVEL_MS / 1000))))
        return pid, point, ms

    def first_to(self, point: Vec, candidates: Iterable[str]) -> str:
        """Of `candidates`, the one who can be on `point` first (then by id)."""
        best_s, best = math.inf, None
        top = max(lim.top_speed for lim in self.limits.values())
        there = band(point)  # where `step` takes him
        for d, pid in sorted((math.dist(self.at(p), there), p) for p in candidates):
            if best is not None and (d - ARRIVED_M) / top > best_s:
                break  # nobody further away can be quicker
            s = time_to_reach(self.bodies[pid], point, self.limits[pid])
            if best is None or (s, pid) < (best_s, best):
                best_s, best = s, pid
        return best

    def taker(self, kind: Restart, spot: Vec, team: str) -> str:
        group = {Restart.GOAL_KICK: "goal", Restart.KICK_OFF: "attack", Restart.PENALTY: "attack"}
        if kind in group:
            return self.rng.choice([p for p in self.lineup(team) if self.group(p) == group[kind]])
        outfield = [p for p in self.lineup(team) if self.group(p) != "goal"]
        return min(outfield, key=lambda p: (math.dist(self.at(p), spot), p))

    def drawn(self, items: Iterable[str], weights: Iterable[float]) -> Iterator[str]:
        """`items` one by one, each drawn by weight from those not yet drawn."""
        items, weights = list(items), list(weights)
        while items:
            i = self.rng.choices(range(len(items)), weights)[0]
            weights.pop(i)
            yield items.pop(i)

    # --- bookkeeping ----------------------------------------------------------------------------

    def stop(self, kind: Restart, spot: Vec, team: str, taker: str | None = None) -> None:
        """The ball is dead: a restart of `kind` at `spot` for `team` is due, nobody has it."""
        self.pending = (kind, spot, team, taker)
        self.carrier = self.carry = self.runner = self.possession = None
        self.due = True

    def take(self, player: str) -> None:
        """`player` has the ball at his feet."""
        self.carrier, self.carry = player, None
        self.possession = team_of(player)
        self.due = True

    def snap(self) -> None:
        """Everyone's position now, to the centimetre, as the frame of this clock: one frame per
        instant, the last snapshot taken at it."""
        values = [_centi(self.ball[0]), _centi(self.ball[1])]
        for pid in self.everyone:
            b = self.bodies[pid]
            values += (round(b.x * 100), round(b.y * 100))  # _centi, written out: 2.6 M a match
        frames = self.frames[self.period]
        if self.framed == self.t:
            frames[-len(values) :] = array("h", values)
        else:
            frames.extend(values)
            self.framed = self.t

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
        start: Vec,
        t0: int,
        outcome: Outcome,
        restart: Restart | None,
        recipient: str | None = None,
    ) -> None:
        """A ball flight by `player` from `start` at `t0` to where the ball is now."""
        self.emit(
            kind,
            clock=t0,
            team=team_of(player),
            player=player,
            start=Point(*_cm(start)),
            end=Point(*_cm(self.ball)),
            duration_ms=self.t - t0,
            outcome=outcome,
            restart=restart,
            recipient=recipient,
        )

    def emit_by(self, kind: EventType, player: str, start: Vec, **fields) -> None:
        """An event by `player` for their team, starting at `start`."""
        self.emit(kind, team=team_of(player), player=player, start=Point(*_cm(start)), **fields)

    def emit(self, kind: EventType, clock: int | None = None, **fields) -> None:
        """An event at `clock` (now if None), numbered in emit order."""
        self.events.append(
            Event(
                event_id=make_event_id(self.meta.match_id, len(self.events)),
                period=self.period,
                clock_ms=self.t if clock is None else clock,
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

    def team(self, club: str) -> Team:
        return self.teams[0] if club == self.meta.home else self.teams[1]

    def opponent(self, team: str) -> str:
        return self.meta.away if team == self.meta.home else self.meta.home

    def group(self, player: str) -> str:
        """The player's role group (`formations.ROLE_GROUP`) by the slot he plays."""
        slots, keeper = self.sides[team_of(player)]
        return "goal" if player == keeper else ROLE_GROUP[slots[player].role]

    def at(self, player: str) -> Vec:
        b = self.bodies[player]
        return b.x, b.y

    def positions(self) -> dict[str, Vec]:
        return {pid: (b.x, b.y) for pid, b in self.bodies.items()}

    def goal_x(self, team: str) -> float:
        return attacking_goal_x(self.meta, team, self.period)

    def distance_to_goal(self, player: str) -> float:
        return math.dist(self.ball, (self.goal_x(team_of(player)), CENTRE[1]))

    def penalty_spot(self, attacking: str) -> Vec:
        goal_x = self.goal_x(attacking)
        return (goal_x - _forward(goal_x) * PENALTY_SPOT, CENTRE[1])


def _forward(goal_x: float) -> float:
    """+1 when the attacked goal is at x = PITCH_LENGTH, -1 when it is at x = 0."""
    return 1.0 if goal_x == PITCH_LENGTH else -1.0


def _p_shot(distance: float) -> float:
    for limit, p in SHOT_ODDS:
        if distance <= limit:
            return p
    return 0.0


def _ceil_ms(seconds: float) -> int:
    """`seconds` rounded up onto the 100 ms grid, in ms (a float's last bit never adds a step)."""
    return math.ceil(round(seconds * 1000 / STEP_MS, 6)) * STEP_MS


def _flight_ms(start: Vec, end: Vec, speed: float) -> int:
    """Milliseconds a ball kicked at `speed` takes, on the grid and inside what the schema
    allows (so it may fly slower than kicked, never faster)."""
    return min(MAX_TRAVEL_MS, max(MIN_FLIGHT_MS, _ceil_ms(math.dist(start, end) / speed)))


def _nearest_on(start: Vec, end: Vec, point: Vec, least: float = 0.0) -> Vec:
    """The point of the segment from `start` to `end` nearest `point`, at least the share
    `least` of the way along it."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    length2 = dx * dx + dy * dy
    u = (
        1.0
        if length2 == 0.0
        else ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length2
    )
    u = min(1.0, max(least, u))
    return start[0] + u * dx, start[1] + u * dy


def _centi(metres: float) -> int:
    """Whole centimetres: the frames' unit."""
    return round(metres * 100)


def _cm(p: Vec) -> Vec:
    """A point to the centimetre, rounded as the frames are, so an event and the tracking agree
    exactly."""
    return _centi(p[0]) / 100, _centi(p[1]) / 100


def _chain(*parts: Iterable[str]) -> Iterator[str]:
    for part in parts:
        yield from part
