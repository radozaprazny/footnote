import hashlib
import itertools
import json
import math
import re
import unicodedata
from importlib.resources import files

import pytest
from hypothesis import given
from hypothesis import strategies as st

from matchlens.league import MIN_GOALKEEPERS, POSITIONS, SQUAD_SIZE, load_league, parse_league


def digest(name: str) -> str:
    """The first 16 hex digits of the SHA-256 of a lower-cased name. The lists below hold names
    this way, so the public repo spells no real name out, and a text still hits them."""
    return hashlib.sha256(name.lower().encode()).hexdigest()[:16]


def digests(text: str) -> frozenset[str]:
    """Comma-separated digests (`digest`) of names; a name may have several words."""
    found = frozenset(e.strip() for e in text.split(",") if e.strip())
    assert all(re.fullmatch(r"[0-9a-f]{16}", d) for d in found)
    return found


# Distinctive names of real clubs (England, Scotland, big European clubs, Slovakia), at most
# MAX_WORDS words each (2 today). Generic suffixes such as "Town", "Rovers" or "Athletic" are
# fine; the place or nickname is what is real.
REAL_CLUBS = digests("""
008be6875298f5a6, 01735c5ff1608734, 0750752e4c6fb401, 086c1a7256ebf7d6, 099dd595ce6576bb,
108bd0766bf42ad9, 11148d8f6ad4d4f2, 121639758d50ce8f, 1579a6e3112caba1, 15c6d611193988e4,
1887ba32a3e78540, 1ca3323e2ba8e183, 1d1e68a5cff6aa10, 1ecd41c03ef78bd6, 1f73a018e9a6e20b,
2499e63cb269d514, 2501cd2e2e816186, 25e650426bbf0dc9, 26a8181dcae497e7, 27511e620b42e8fb,
2bc0659381c5a5ea, 389afaa88be6e31b, 3b673bc24e8dd974, 3ccf243960d58d97, 3df4897a7599facd,
3e6958a7720967df, 404ade22ac5155b1, 40cea1fd091bafe9, 4151f71c176ed43c, 43fd8ec4f70c9856,
4762caacdc263deb, 49ff1c352b1a6c29, 49ffa0597506d255, 4adff94eb3d10bb3, 4f4668bb19e973a0,
4fb33620977be7c9, 526e264d2a0e21b3, 52b07f18c831ba4b, 57d6f7c06e35a3a3, 5d326708016b2b0d,
5f0d364b5a8e7ab6, 619a2ccf126ce837, 626b208a365327e7, 635450503029fc24, 66123f95d3ed53ff,
7131674d47613784, 73d0a219cada10f0, 76e4aa1b6d2ca68b, 78fee7d47c7648e5, 79996373623b60c0,
7a97152dd8ab4ef2, 7c8159dd2e49a576, 7cd7979a4f54d16f, 7d698c38b714638d, 7d766284a96642bf,
7dd7b5d5a34aaa99, 85b0c4208e2528ea, 8617b1495b83c37a, 8870e6cbc014734d, 8a75cc3509a6b968,
8de1f76afa0e65eb, 8f36b08546c5a3c7, 910aff64ee1e0e5d, 991b08408c2e4625, 9e861941ad8bf5bc,
a0152061d6a032e2, a27fd1720a7c30a6, a744d93f2c6e8830, aab3fce96b5bdd7e, afdc02ac2006ffc0,
b0c27fca74fa9193, b63452302017e9fe, b77207f916d46524, b97805a2d39ea285, bc5fb9abe8d5e72e,
c940429f4dcb49fe, c9b5fcdd10039e80, d2263b3772d959f6, d70afca615203838, d7b7e5a7937eee08,
db849bbf3e5c8127, db8e363f0316fe05, dffc504aa55359b9, e41f61423f6361a8, e5c7c23397fbfcdd,
e647708a52060743, e6608c0847924a16, ecbfb23a44dd829d, ed9d743a0e44fd97, ee2aa44805b51b10,
efee614420c57ddd, f0990dc8a0f70ffb, f56206ec0f42e047, f968b6a56647cf5b, f97557ce9b1cf089,
fb4dac7b8936e9d7, fe4b7eb22e8c2fed, ff479f9d891005c5
""")
# Three-letter codes of Premier League clubs only
REAL_CLUB_CODES = digests("""
081fe58fff095ab9, 11507a0e2f5e69d5, 1508b697895abf03, 1e84b08c59bf24b2, 250fccd5f5f76c7c,
27756f050e14a1cb, 2cda36e6665669fd, 36c68ee284322562, 58a69b8bb1f5e666, 64fe974c8a499fc9,
687bd6a917d4d11e, 6a5845baaa6bf615, 6debeeb262f83b1a, 72c93ad35e5fcb09, 7d296c79bdb526d6,
84dd94d1c401bd07, 85262adf74518bbb, 92a0e70799cb6704, a37f9992b6d1c4e1, a3da79f283bcc136,
a56412139fb41bc4, cf5dd5aafe2a12e7, df893b9e12bb9b2d
""")
# Surnames of famous players, a smoke check against copying real squads
FAMOUS_SURNAMES = digests("""
0422d5b3a69178ae, 043ccc0426d6d4c8, 055654e9d79b0bfa, 08614c84a3bbb4b0, 1491b1be53d40a5c,
1a2e90d2c67a115a, 209f76418ece7c93, 2d2d674c7150952f, 33db7a9acd993064, 401cb0a3c9577a6a,
435f619588259b09, 4c006c647316bd2e, 64365ec140b2bcc7, 68faa1ac202cbcdc, 99d44040c457c34b,
9bcdae8ebc2a970a, a5cca33940ed2a85, b1ea8502c0c642d0, baebd585e1b90837, c1dbd67f9e1d0463,
cd24cb486e6ea1fa, d7d82a15e32ff877, e24dd2210803b473, e610ea143109259c, e675137ec2f19377,
ec3620470529f114, f1f45800d768bcd5, f3c94b10126dca05, f57dbb83bc838bda, fcecca0fd203a501
""")
# letters that NFKD does not decompose and an ASCII encode would drop
_LATIN = str.maketrans({"ø": "o", "Ø": "O", "ł": "l", "Ł": "L", "æ": "ae", "Æ": "AE", "ß": "ss",
                        "đ": "d", "Đ": "D", "ı": "i"})  # fmt: skip
# primaries of two clubs must be told apart on the pitch (the first navy pair was 39 apart)
MIN_PRIMARY_DISTANCE = 100
MAX_WORDS = 3  # at least the longest name of REAL_CLUBS, in words: raise it for a longer one
# Slovak case endings a name takes in a translated caption
SK_ENDINGS = ("ami", "ach", "och", "ovi", "om", "ou", "ho", "mu", "ov",
              "a", "e", "i", "m", "u", "y")  # fmt: skip


def words(text: str) -> list[str]:
    ascii_text = unicodedata.normalize("NFKD", text.translate(_LATIN))
    return re.findall(r"[a-z]+", ascii_text.encode("ascii", "ignore").decode().lower())


def forms(word: str) -> set[str]:
    """`word` and the nominatives it may be a Slovak case of: a translated caption declines a
    name, so its case ending is dropped, or replaced by an "a" or an "o"."""
    found = {word}
    for ending in SK_ENDINGS:
        stem = word.removesuffix(ending)
        if stem != word and len(stem) >= 3:
            found |= {stem, stem + "a", stem + "o"}
    return found


def hits(text: str, names: frozenset[str]) -> set[str]:
    """Digests of `names` whose name occurs in `text` as whole words, the last of them also in a
    Slovak case."""
    found = words(text)
    grams = {
        (*found[i : i + n - 1], last)
        for n in range(1, MAX_WORDS + 1)
        for i in range(len(found) - n + 1)
        for last in forms(found[i + n - 1])
    }
    return {digest(" ".join(g)) for g in grams} & names


def real_club_hits(text: str) -> set[str]:
    """Digests of the REAL_CLUBS that occur in `text`, as `hits` finds them."""
    return hits(text, REAL_CLUBS)


def real_club_code(code: str) -> bool:
    """Whether a club's three-letter code is one of REAL_CLUB_CODES."""
    return digest(code) in REAL_CLUB_CODES


def famous_surname_hits(text: str) -> set[str]:
    """Digests of the FAMOUS_SURNAMES that occur in `text`, as `hits` finds them."""
    return hits(text, FAMOUS_SURNAMES)


def rgb(colour: str) -> tuple[int, int, int]:
    return tuple(int(colour[i : i + 2], 16) for i in (1, 3, 5))


def raw_league():
    return json.loads(files("matchlens").joinpath("data/league.json").read_text(encoding="utf-8"))


def test_packaged_league_has_four_full_squads():
    league = load_league()
    assert len(league.clubs) == 4
    assert all(len(club.players) == SQUAD_SIZE for club in league.clubs)


def test_squad_rules_hold_for_packaged_league():
    for club in load_league().clubs:
        assert [p.id for p in club.players] == sorted(p.id for p in club.players)
        assert len({p.number for p in club.players}) == SQUAD_SIZE
        assert {p.position for p in club.players} <= POSITIONS
        assert sum(p.position == "GK" for p in club.players) >= MIN_GOALKEEPERS


def test_player_ids_are_unique_across_league():
    ids = [p.id for club in load_league().clubs for p in club.players]
    assert len(ids) == len(set(ids))


def test_primary_colours_are_far_apart():
    for a, b in itertools.combinations(load_league().clubs, 2):
        distance = math.dist(rgb(a.primary_colour), rgb(b.primary_colour))
        assert distance >= MIN_PRIMARY_DISTANCE, f"{a.id}/{b.id}: {distance:.0f}"


def fingerprint(names: frozenset[str]) -> str:
    return hashlib.sha256(",".join(sorted(names)).encode()).hexdigest()[:16]


def test_the_lists_keep_their_names():
    """Hashed, the lists cannot be read, so their sizes and contents are pinned: a name lost or a
    digest changed in an edit fails. The values were taken when the plain lists were hashed (26
    Oct), after every plain name was checked to hit (PROGRESS.md, M7)."""
    assert (len(REAL_CLUBS), len(REAL_CLUB_CODES), len(FAMOUS_SURNAMES)) == (98, 23, 30)
    assert fingerprint(REAL_CLUBS) == "76bc33680d06a14a"
    assert fingerprint(REAL_CLUB_CODES) == "f5c8067a385a0a69"
    assert fingerprint(FAMOUS_SURNAMES) == "1832e5bc9a40b425"


def test_a_digest_is_the_sha256_of_the_lower_cased_name():
    """A known answer: the hash, the encoding and the 16 digits are pinned, so the lists keep
    meaning the names they were made of."""
    assert digest("Brackenholt") == "73c599bb30bfefc5"


def test_each_check_reads_its_own_list(monkeypatch):
    """With a made-up name in each list, each check finds its own and not the others'."""
    lists = {"REAL_CLUBS": "brackenholt", "FAMOUS_SURNAMES": "kestrava", "REAL_CLUB_CODES": "qxz"}
    for name, entry in lists.items():
        monkeypatch.setitem(globals(), name, frozenset({digest(entry)}))
    text = "Brackenholt Kestrava QXZ"
    assert real_club_hits(text) == {digest("brackenholt")}
    assert famous_surname_hits(text) == {digest("kestrava")}
    assert real_club_code("QXZ") and not real_club_code("BRA")


def test_a_digest_ignores_case():
    """A club code is upper-case in the league and lower-case in the list: one digest for both."""
    assert digest("QXZ") == digest("qxz") == digest("Qxz")
    assert digest("North Quay") == digest("north quay") != digest("northquay")


def test_detector_catches_a_listed_name_in_any_form():
    """By whole words, one or two of them, in any case and with accents: made-up names here, so
    the test spells no real one out."""
    names = frozenset(map(digest, ["brackenholt", "north quay", "quay", "sao meridel"]))
    assert hits("Brackenholt Rovers", names) == {digest("brackenholt")}
    assert hits("NORTH QUAY", names) == {digest("north quay"), digest("quay")}
    assert hits("São Meridel FC", names) == {digest("sao meridel")}
    assert hits("North Quayside, Brackenholtz", names) == set()
    assert hits("north", names) == set()
    both = {digest("sao meridel"), digest("north quay"), digest("quay")}
    assert hits("Sao Meridel and north   quay", names) == both


def test_detector_catches_a_listed_name_in_a_slovak_case():
    """A translated caption declines a name: the last word's case ending is dropped or replaced
    by an "a" or an "o"; a part of a name or another word is still no hit."""
    names = frozenset(map(digest, ["brackenholt", "kestrava", "vellano", "north quay"]))
    assert hits("gól Brackenholtu", names) == {digest("brackenholt")}
    assert hits("v Kestrave", names) == {digest("kestrava")}
    assert hits("proti Vellanu", names) == {digest("vellano")}
    assert hits("hráči North Quayom", names) == {digest("north quay")}
    # every ending that fits is tried: "-mu" and "-u" both end "Brackenholmu"
    assert hits("Brackenholmu", frozenset({digest("brackenholm")})) == {digest("brackenholm")}
    assert hits("Brackenhol, Kestrel, Vella, Vellan, Quayside", names) == set()


def test_a_name_of_three_words_hits():
    """Up to MAX_WORDS words, the last one also in a Slovak case."""
    names = frozenset({digest("isle of quay")})
    assert hits("the Isle of Quay end", names) == {digest("isle of quay")}
    assert hits("v Isle of Quayi", names) == {digest("isle of quay")}
    assert hits("Isle of", names) == set()


def test_a_slovak_case_needs_a_stem_of_three_letters():
    """Exactly on the boundary a stem of 3 letters hits, one letter less does not."""
    assert hits("Tovy", frozenset({digest("tova")})) == {digest("tova")}
    assert hits("Tou Toy Toe", frozenset(map(digest, ["to", "toa", "too"]))) == set()


# the Slovak case endings, written out here so that one dropped from SK_ENDINGS fails its case
CASE_ENDINGS = ("ami", "ach", "och", "ovi", "om", "ou", "ho", "mu", "ov",
                "a", "e", "i", "m", "u", "y")  # fmt: skip


@pytest.mark.parametrize("ending", CASE_ENDINGS)
def test_every_slovak_ending_reaches_its_name(ending):
    """Each case ending, after a name that ends in a consonant and in place of the "a" or "o" of
    one that ends in a vowel."""
    names = frozenset(map(digest, ["brackenholt", "kestrava", "vellano"]))
    assert hits(f"Brackenholt{ending}", names) == {digest("brackenholt")}
    assert hits(f"Kestrav{ending}", names) == {digest("kestrava")}
    assert hits(f"Vellan{ending}", names) == {digest("vellano")}


def test_no_listed_club_in_generic_or_fictional_names():
    # parts of a phrase alone are generic, and matching is by whole words
    assert real_club_hits("West Vellbridge Park") == set()
    assert real_club_hits("Saltreach FC") == set()
    assert real_club_hits("Corrowmere Athletic") == set()


def test_words_keep_letters_nfkd_cannot_decompose():
    assert words("Bjørn Ødevang") == ["bjorn", "odevang"]
    assert words("Łucjan Weißmar") == ["lucjan", "weissmar"]


def test_no_real_club_name_anywhere():
    league = load_league()
    texts = [league.name]
    for club in league.clubs:
        texts += [club.name, club.city] + [p.name for p in club.players]
        assert not real_club_code(club.short_name), club.short_name
    for text in texts:
        assert real_club_hits(text) == set(), f"{text!r} looks like a real club"


def test_no_player_has_a_famous_surname():
    for club in load_league().clubs:
        for p in club.players:
            assert famous_surname_hits(p.name) == set(), f"{p.id}: {p.name!r}"


@given(st.lists(st.permutations(range(SQUAD_SIZE)), min_size=4, max_size=4))
def test_player_order_in_file_does_not_matter(orders):
    data = raw_league()
    for club, order in zip(data["clubs"], orders, strict=True):
        club["players"] = [club["players"][i] for i in order]
    assert parse_league(data) == load_league()


def _drop_a_player(d):
    d["clubs"][0]["players"].pop()


def _add_a_player(d):
    d["clubs"][0]["players"].append(
        {"id": "cor-p19", "name": "Extra", "number": 99, "position": "MF"}
    )


def _duplicate_player_id(d):
    d["clubs"][0]["players"][1]["id"] = d["clubs"][0]["players"][0]["id"]


def _player_id_of_another_club(d):
    d["clubs"][0]["players"][0]["id"] = "vel-p99"


def _player_id_prefix_without_dash(d):
    d["clubs"][0]["players"][0]["id"] = "corx-p01"


def _player_id_prefix_not_at_start(d):
    d["clubs"][0]["players"][0]["id"] = "vel-cor-p01"


def _duplicate_shirt_number(d):
    d["clubs"][0]["players"][1]["number"] = d["clubs"][0]["players"][0]["number"]


def _unknown_position(d):
    d["clubs"][0]["players"][5]["position"] = "WB"


def _shirt_number_zero(d):
    d["clubs"][0]["players"][5]["number"] = 0


def _shirt_number_100(d):
    d["clubs"][0]["players"][5]["number"] = 100


def _shirt_number_bool(d):
    d["clubs"][0]["players"][5]["number"] = True


def _shirt_number_float(d):
    d["clubs"][0]["players"][5]["number"] = 7.0


def _one_goalkeeper(d):
    for p in d["clubs"][0]["players"]:
        if p["position"] == "GK":
            p["position"] = "DF"
            break


def _bad_colour(d):
    d["clubs"][0]["colours"]["primary"] = "navy"


def _bad_secondary_colour(d):
    d["clubs"][0]["colours"]["secondary"] = "#FFF"


def _colour_with_trailing_text(d):
    d["clubs"][0]["colours"]["primary"] = "#1F4E79zz"


def _lower_case_short_name(d):
    d["clubs"][0]["short_name"] = "cor"


def _short_name_too_long(d):
    d["clubs"][0]["short_name"] = "CORE"


def _short_name_too_short(d):
    d["clubs"][0]["short_name"] = "CO"


def _short_name_with_digit(d):
    d["clubs"][0]["short_name"] = "C0R"


def _one_club(d):
    d["clubs"] = d["clubs"][:1]


def _duplicate_club_id(d):
    club = d["clubs"][1]
    club["id"] = d["clubs"][0]["id"]
    # keep the players' id prefix valid, so only the club id rule is broken
    for i, p in enumerate(club["players"]):
        p["id"] = f"{club['id']}-dup{i:02d}"


def _duplicate_club_short_name(d):
    d["clubs"][1]["short_name"] = d["clubs"][0]["short_name"]


BROKEN_RULES = [
    (_drop_a_player, "squad has 17 players"),
    (_add_a_player, "squad has 19 players"),
    (_duplicate_player_id, "duplicate player id"),
    (_player_id_of_another_club, "does not start with its club id"),
    (_player_id_prefix_without_dash, "does not start with its club id"),
    (_player_id_prefix_not_at_start, "does not start with its club id"),
    (_duplicate_shirt_number, "duplicate cor shirt number"),
    (_unknown_position, "unknown position"),
    (_shirt_number_zero, "is not an int in 1-99"),
    (_shirt_number_100, "is not an int in 1-99"),
    (_shirt_number_bool, "is not an int in 1-99"),
    (_shirt_number_float, "is not an int in 1-99"),
    (_one_goalkeeper, "1 goalkeepers"),
    (_bad_colour, "is not #RRGGBB"),
    (_bad_secondary_colour, "is not #RRGGBB"),
    (_colour_with_trailing_text, "is not #RRGGBB"),
    (_lower_case_short_name, "is not three capitals"),
    (_short_name_too_long, "is not three capitals"),
    (_short_name_too_short, "is not three capitals"),
    (_short_name_with_digit, "is not three capitals"),
    (_one_club, "league has 1 clubs"),
    (_duplicate_club_id, "duplicate club id"),
    (_duplicate_club_short_name, "duplicate club short name"),
]


@pytest.mark.parametrize(
    ("break_rule", "message"), BROKEN_RULES, ids=[rule.__name__ for rule, _ in BROKEN_RULES]
)
def test_broken_squad_rule_is_rejected(break_rule, message):
    data = raw_league()
    break_rule(data)
    with pytest.raises(ValueError, match=message):
        parse_league(data)


def test_unbroken_data_parses():
    assert parse_league(raw_league()) == load_league()


def _two_clubs(d):
    d["clubs"] = d["clubs"][:2]


def _lower_case_hex_colour(d):
    d["clubs"][0]["colours"]["primary"] = "#1f4e79"


def _shirt_number_99(d):
    d["clubs"][0]["players"][5]["number"] = 99


# the edges of each rule, which must still pass
ACCEPTED_EDGES = [_two_clubs, _lower_case_hex_colour, _shirt_number_99]


@pytest.mark.parametrize("vary", ACCEPTED_EDGES, ids=[vary.__name__ for vary in ACCEPTED_EDGES])
def test_edge_of_a_rule_is_accepted(vary):
    data = raw_league()
    vary(data)
    parse_league(data)
