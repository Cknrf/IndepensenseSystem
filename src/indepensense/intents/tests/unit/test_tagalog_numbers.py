"""Native Tagalog numeral spelling.

These are grammar assertions, not behaviour assertions: every expected
string here is a claim about Tagalog that a speaker can check, which is
the point. The numbers chosen are the ones the system can actually
produce — `round_speech_distance` only ever emits multiples of 10, 50 and
100 under a kilometre, and object counts are single digits — plus the
boundaries where the spelling rules change.
"""
import pytest

from indepensense.intents import messages


@pytest.mark.parametrize("n,expected", [
    (0, "sero"),
    (1, "isa"),
    (5, "lima"),
    (9, "siyam"),
    (10, "sampu"),
])
def test_units_and_ten(n, expected):
    assert messages.tagalog_number(n) == expected


@pytest.mark.parametrize("n,expected", [
    (11, "labing-isa"),
    (12, "labindalawa"),
    (13, "labintatlo"),
    (14, "labing-apat"),
    (15, "labinlima"),
    (16, "labing-anim"),
    (17, "labimpito"),
    (18, "labingwalo"),
    (19, "labinsiyam"),
])
def test_teens_assimilate_the_labing_prefix(n, expected):
    """The final -ng of "labing" changes with the following consonant:
    labin- before d/t/l/s, labim- before p, labing- before vowels and w.
    Getting this wrong produces words that do not exist."""
    assert messages.tagalog_number(n) == expected


@pytest.mark.parametrize("n,expected", [
    (20, "dalawampu"),
    (30, "tatlumpu"),
    (40, "apatnapu"),
    (50, "limampu"),
    (60, "animnapu"),
    (70, "pitumpu"),
    (80, "walumpu"),
    (90, "siyamnapu"),
])
def test_tens_use_irregular_stems(n, expected):
    """tatlo -> tatlum, pito -> pitum, walo -> walum. Not derivable by
    suffixing, which is why the table exists."""
    assert messages.tagalog_number(n) == expected


def test_tens_join_units_with_the_enclitic():
    assert messages.tagalog_number(21) == "dalawampu't isa"
    assert messages.tagalog_number(95) == "siyamnapu't lima"


def test_one_hundred_and_one_thousand_are_fused_words():
    """"sandaan", not "isang daan" — a lexical irregularity."""
    assert messages.tagalog_number(100) == "sandaan"
    assert messages.tagalog_number(1000) == "sanlibo"


@pytest.mark.parametrize("n,expected", [
    (200, "dalawang daan"),
    (300, "tatlong daan"),
    (400, "apat na raan"),
    (500, "limang daan"),
    (600, "anim na raan"),
    (700, "pitong daan"),
    (800, "walong daan"),
    (900, "siyam na raan"),
])
def test_daan_lenites_to_raan_after_the_na_linker(n, expected):
    """Tagalog softens d to r between vowels, so the hundreds whose
    multiplier ends in a consonant (apat, anim, siyam) take "raan"."""
    assert messages.tagalog_number(n) == expected


def test_hundreds_join_their_remainder_with_at():
    assert messages.tagalog_number(150) == "sandaan at limampu"
    assert messages.tagalog_number(450) == "apat na raan at limampu"
    assert messages.tagalog_number(514) == "limang daan at labing-apat"


@pytest.mark.parametrize("word,expected", [
    ("dalawa", "dalawang"),      # vowel -> -ng
    ("sampu", "sampung"),
    ("sandaan", "sandaang"),     # final -n -> -g
    ("apat", "apat na"),         # other consonant -> separate word
    ("siyam", "siyam na"),
])
def test_ligature_picks_its_form_from_the_final_sound(word, expected):
    assert messages.tagalog_ligature(word) == expected


def test_counter_links_the_number_to_the_noun():
    """A bare numeral cannot sit next to a noun in Tagalog — "dalawa
    upuan" is ungrammatical. This is the form templates interpolate."""
    assert messages.tagalog_counter(2) == "dalawang"
    assert messages.tagalog_counter(90) == "siyamnapung"
    assert messages.tagalog_counter(400) == "apat na raang"


def test_counter_reads_a_decimal_as_a_sequence():
    """8.2 is "walo punto dalawa", not "walong punto": a decimal is two
    numbers read in order, so only the last one links to the noun."""
    assert messages.tagalog_counter(8.2) == "walo punto dalawang"
    assert messages.tagalog_counter(1.5) == "isa punto limang"


def test_whole_floats_do_not_take_the_decimal_path():
    assert messages.tagalog_counter(2.0) == "dalawang"


def test_out_of_range_falls_back_to_digits_rather_than_raising():
    """Nothing in the system can reach this — distances switch to
    kilometres at 1000 m — but going silent mid-sentence is the one
    failure the voice pipeline must never have."""
    assert messages.tagalog_number(10_000) == "10000"
    assert messages.tagalog_number(-1) == "-1"


def test_no_digits_survive_into_tagalog_speech():
    """The whole point of the module: whatever the engine is handed for
    Tagalog must contain no characters it would expand in another
    language's number rules."""
    for metres in range(1, 20_000, 37):
        assert not any(c.isdigit() for c in messages.speak_distance(metres, "tl"))
    for count in range(1, 100):
        assert not any(c.isdigit() for c in messages.count_label("chair", count, "tl"))
