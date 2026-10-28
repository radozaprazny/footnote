import pytest

from matchlens.events import PITCH_LENGTH, PITCH_WIDTH
from matchlens.formations import FORMATIONS, ROLE_GROUP, ROLES, SIDES, to_pitch

MIDDLE = PITCH_WIDTH / 2
SHAPES = ("attack", "defend")


def size(slots, shape: str) -> tuple[float, float]:
    """Length and width of a shape's ten outfield slots."""
    xs = [getattr(s, shape)[0] for s in slots]
    ys = [getattr(s, shape)[1] for s in slots]
    return max(xs) - min(xs), max(ys) - min(ys)


def test_the_four_formations():
    assert sorted(FORMATIONS) == ["3-5-2", "4-2-3-1", "4-3-3", "4-4-2"]


def test_every_outfield_role_has_a_group():
    assert set(ROLE_GROUP) == set(ROLES)


@pytest.mark.parametrize("name", sorted(FORMATIONS))
def test_ten_outfield_slots_each_role_and_side_once(name):
    slots = FORMATIONS[name]
    assert len(slots) == 10 == sum(int(n) for n in name.split("-"))
    assert all(s.role in ROLES and s.role != "GK" and s.side in SIDES for s in slots)
    assert len({(s.role, s.side) for s in slots}) == 10


@pytest.mark.parametrize("name", sorted(FORMATIONS))
@pytest.mark.parametrize("shape", SHAPES)
def test_a_side_is_where_its_slot_is(name, shape):
    # L is y below the middle, R above it, C on it
    for s in FORMATIONS[name]:
        y = getattr(s, shape)[1]
        assert {"L": y < MIDDLE, "R": y > MIDDLE, "C": y == MIDDLE}[s.side], (s, shape)


@pytest.mark.parametrize("name", sorted(FORMATIONS))
@pytest.mark.parametrize("shape", SHAPES)
def test_a_shape_is_its_own_mirror(name, shape):
    mirror = {"L": "R", "C": "C", "R": "L"}
    slots = {(s.role, s.side): getattr(s, shape) for s in FORMATIONS[name]}
    for (role, side), (dx, y) in slots.items():
        assert slots[(role, mirror[side])] == (dx, PITCH_WIDTH - y), (role, side)


@pytest.mark.parametrize("name", sorted(FORMATIONS))
@pytest.mark.parametrize("shape", SHAPES)
def test_the_back_line_is_at_zero_and_the_shape_on_the_pitch(name, shape):
    points = [getattr(s, shape) for s in FORMATIONS[name]]
    assert min(dx for dx, _ in points) == 0
    assert all(0 < y < PITCH_WIDTH for _, y in points)


@pytest.mark.parametrize("name", sorted(FORMATIONS))
def test_in_possession_longer_and_wider_than_out_of_it(name):
    # as in all 7 real matches (PROGRESS, Metrics: Player movement, real reference)
    length_in, width_in = size(FORMATIONS[name], "attack")
    length_out, width_out = size(FORMATIONS[name], "defend")
    assert length_in > length_out
    assert width_in > width_out


# the bands M9 item 1 measured on real matches and the owner approved, in metres; the shapes are
# the normal ones, before a club's width and the ball's pull move them
BANDS = {
    "length in": (28.5, 39.1),
    "length out": (26.3, 35.8),
    "width in": (28.4, 54.7),
    "width out": (24.9, 44.0),
    "length in minus out": (0.7, 5.9),
    "width in minus out": (2.8, 12.2),
}


@pytest.mark.parametrize("name", sorted(FORMATIONS))
def test_the_shapes_lie_in_the_measured_bands(name):
    length_in, width_in = size(FORMATIONS[name], "attack")
    length_out, width_out = size(FORMATIONS[name], "defend")
    sizes = {
        "length in": length_in,
        "length out": length_out,
        "width in": width_in,
        "width out": width_out,
        "length in minus out": length_in - length_out,
        "width in minus out": width_in - width_out,
    }
    for band, (low, high) in BANDS.items():
        assert low <= sizes[band] <= high, (band, sizes[band])


@pytest.mark.parametrize("name", sorted(FORMATIONS))
@pytest.mark.parametrize("shape", SHAPES)
def test_a_team_keeps_its_left_whichever_way_it_attacks(name, shape):
    # attacking right, the left is the top of the screen (y below 34); attacking left, the bottom
    for s in FORMATIONS[name]:
        dx, y = getattr(s, shape)
        x = 30.0 + dx  # a back line 30 m from the team's own goal
        right, left = to_pitch(x, y, attacks_right=True), to_pitch(x, y, attacks_right=False)
        assert right == (x, y)
        assert left == (PITCH_LENGTH - x, PITCH_WIDTH - y)
        if s.side == "L":
            assert right[1] < MIDDLE < left[1]
        elif s.side == "R":
            assert left[1] < MIDDLE < right[1]
