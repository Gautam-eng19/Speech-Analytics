"""Tests for the word profile: tokens, matching to the passage, measuring a reading, the run statistics, building the profile, and its place in the
baseline record.

Expected values are worked out here from the raw numbers, not by calling the code under test: the geometric mean of the baseline slots, the level
profile after each reading's own offset is removed, the slot of a word after a long silence, the median of runs. Covers normal input, edge cases
(words without a time, too few active frames, a reading that does not match the passage, words seen once), invalid input, determinism, the
independence of the order of the readings, the recovery of a known spread, and that a baseline file written before profiles existed still verifies.
"""
from __future__ import annotations

import json
import math
from types import SimpleNamespace

import numpy as np
import pytest
from app.schemas.common import AlignmentMethod
from app.schemas.contracts import AlignedTranscript, AlignedWord, BaselineStatsRecord, NoiseModel, WordProfile
from app.services.grounding.profile import (
    MIN_ACTIVE_FRAMES,
    MIN_SLOT_S,
    NOISE_GRID,
    PROFILE_MIN_TAKES,
    TEMPO_WINDOW_WORDS,
    WordObservations,
    build_word_profile,
    clean_token,
    map_to_passage,
    measure_words,
    noise_sigma,
    overall_tempo,
    passage_tokens,
    window_log_ratio,
    window_mean,
)
from profile_helpers import (
    ACTIVE_DBFS,
    GAP_CAP_S,
    N_WORDS,
    base_levels,
    base_slots,
    baseline_readings,
    baseline_record as record,
    make_profile,
    make_tokens,
    observations,
    reading,
)
from pydantic import ValidationError


# ------------------------------------------------------------------------------------------------------------------------------
# Words and the passage
# ------------------------------------------------------------------------------------------------------------------------------
def test_a_token_keeps_letters_and_apostrophes_only():
    assert clean_token("Morning,") == "morning"
    assert clean_token("O'Clock.") == "o'clock"
    assert clean_token("don’t") == "don't"                       # the typographic apostrophe is the same letter
    assert clean_token("HELLO!!") == "hello"
    assert clean_token("--") == "" and clean_token("") == "" and clean_token("123") == ""


def test_the_passage_is_its_cleaned_words_without_the_ones_that_have_no_letter():
    assert passage_tokens("Good morning, my 3 friends.  -- ok") == ["good", "morning", "my", "friends", "ok"]
    assert passage_tokens("") == []


def test_a_reading_of_exactly_the_passage_maps_word_to_word():
    tokens = make_tokens(20)
    assert list(map_to_passage(tokens, tokens)) == list(range(20))


def test_a_dropped_a_added_and_a_wrong_word_leave_only_themselves_unmatched():
    passage = make_tokens(12)
    said = passage[:3] + ["extra"] + passage[4:8] + ["wrong"] + passage[9:]          # word 3 dropped, "extra" added, word 8 wrong
    mapped = list(map_to_passage(said, passage))
    assert mapped[:3] == [0, 1, 2] and mapped[3] == -1 and mapped[4:8] == [4, 5, 6, 7] and mapped[8] == -1 and mapped[9:] == [9, 10, 11]


def test_empty_tokens_are_unmatched_and_do_not_shift_the_others():
    passage = make_tokens(5)
    assert list(map_to_passage(["", passage[0], "", passage[1]], passage)) == [-1, 0, -1, 1]


def test_nothing_in_common_or_nothing_to_match_gives_all_unmatched():
    assert list(map_to_passage(["zzz", "yyy"], make_tokens(5))) == [-1, -1]
    assert list(map_to_passage(make_tokens(3), [])) == [-1, -1, -1]
    assert list(map_to_passage([], make_tokens(3))) == []


def test_repeated_words_map_in_order_and_each_passage_word_is_used_once():
    passage = ["the", "cat", "saw", "the", "dog", "and", "the", "bird"]
    said = ["the", "saw", "the", "dog", "and", "the", "bird"]                  # "cat" dropped
    mapped = [m for m in map_to_passage(said, passage) if m >= 0]
    assert mapped == sorted(set(mapped)) and len(mapped) == len(said)


# ------------------------------------------------------------------------------------------------------------------------------
# Measuring a reading
# ------------------------------------------------------------------------------------------------------------------------------
def aligned_of(*words) -> AlignedTranscript:
    return AlignedTranscript(
        text=" ".join(w[0] for w in words),
        words=[AlignedWord(word=w, start_s=s, end_s=e, confidence=0.9 if s is not None else None) for w, s, e in words],
        alignment_method=AlignmentMethod.WHISPERX, total_coverage_pct=0.9,
    )


def energy_of(values, hop: float = 0.01):
    return SimpleNamespace(times_s=np.arange(len(values)) * hop, values_db=np.asarray(values, dtype=float))


def test_a_slot_runs_from_one_word_start_to_the_next_and_a_long_silence_counts_only_up_to_the_cap():
    aligned = aligned_of(("A", 1.0, 1.3), ("B", 1.4, 1.8), ("C", 3.0, 3.4))
    obs = measure_words(aligned, energy_of([-30.0] * 400), max_gap_s=0.25, active_threshold_dbfs=-50.0)
    # A: 1.4 - 1.0 = 0.4 (its 0.1 s gap is under the cap); B: 3.0 - 1.4 = 1.6, minus the silence beyond the cap, (3.0 - 1.8) - 0.25 = 0.95 -> 0.65;
    # C is the last word: its own length.
    assert obs.slot_s == pytest.approx([0.4, 0.65, 0.4])
    assert list(obs.tokens) == ["a", "b", "c"] and obs.max_gap_s == 0.25 and obs.n_timed == 3 and obs.n_words == 3


def test_a_word_without_a_time_has_no_slot_and_neither_has_the_word_before_it():
    aligned = aligned_of(("a", 1.0, 1.3), ("b", None, None), ("c", 2.0, 2.3), ("d", 2.5, 2.9))
    obs = measure_words(aligned, energy_of([-30.0] * 400), max_gap_s=0.25, active_threshold_dbfs=-50.0)
    assert np.isnan(obs.slot_s[0]) and np.isnan(obs.slot_s[1]) and obs.slot_s[2] == pytest.approx(0.5) and obs.slot_s[3] == pytest.approx(0.4)
    assert np.isnan(obs.start_s[1]) and obs.n_timed == 3


def test_a_slot_shorter_than_five_frames_is_an_alignment_artefact_and_is_not_used():
    aligned = aligned_of(("a", 1.0, 1.3), ("b", 1.04, 1.5), ("c", 2.0, 2.4))
    obs = measure_words(aligned, energy_of([-30.0] * 400), max_gap_s=0.25, active_threshold_dbfs=-50.0)
    # "a" starts 0.04 s before "b": too short to be a measurement. "b": 2.0 - 1.04 = 0.96, minus the silence beyond the cap, (2.0 - 1.5) - 0.25 = 0.25.
    assert 0.04 < MIN_SLOT_S and np.isnan(obs.slot_s[0]) and obs.slot_s[1] == pytest.approx(0.71)


def test_the_level_of_a_word_is_the_median_of_its_active_frames_only():
    values = np.full(300, -70.0)                              # silence
    values[100:120] = [-20, -22, -24, -26, -28, -30, -32, -34, -36, -38, -40, -42, -44, -46, -48, -49, -51, -60, -60, -60]   # one word; 3 frames inactive
    aligned = aligned_of(("a", 1.0, 1.2), ("b", 2.0, 2.4))
    obs = measure_words(aligned, energy_of(values), max_gap_s=0.25, active_threshold_dbfs=-50.0)
    active = [-20, -22, -24, -26, -28, -30, -32, -34, -36, -38, -40, -42, -44, -46, -48, -49]
    assert obs.level_db[0] == pytest.approx(float(np.median(active)))
    assert np.isnan(obs.level_db[1])                          # the second word spans only silence: no active frame, no level


def test_a_word_with_fewer_than_three_active_frames_has_no_level():
    values = np.full(300, -70.0)
    values[100:102] = -20.0
    values[200:203] = -20.0
    aligned = aligned_of(("a", 1.0, 1.1), ("b", 2.0, 2.1))
    obs = measure_words(aligned, energy_of(values), max_gap_s=0.25, active_threshold_dbfs=-50.0)
    assert MIN_ACTIVE_FRAMES == 3 and np.isnan(obs.level_db[0]) and obs.level_db[1] == pytest.approx(-20.0)


def test_a_frame_exactly_at_the_end_of_a_word_belongs_to_it():
    values = np.full(40, -70.0)
    values[8:11] = -20.0                                      # frames at 2.00, 2.25 and 2.50 s (a hop of a quarter of a second, exact in binary)
    aligned = aligned_of(("a", 2.0, 2.5), ("b", 5.0, 5.5))
    obs = measure_words(aligned, energy_of(values, hop=0.25), max_gap_s=0.25, active_threshold_dbfs=-50.0)
    assert obs.level_db[0] == pytest.approx(-20.0)           # three active frames, the last one exactly on the word's end


@pytest.mark.parametrize("bad,error", [
    (dict(aligned=object()), TypeError),
    (dict(energy=SimpleNamespace(times_s=np.arange(5.0), values_db=np.zeros(4))), ValueError),
    (dict(energy=SimpleNamespace(times_s=np.zeros((2, 2)), values_db=np.zeros((2, 2)))), ValueError),
    (dict(max_gap_s=0.0), ValueError),
    (dict(max_gap_s=float("nan")), ValueError),
    (dict(active_threshold_dbfs=float("inf")), ValueError),
])
def test_measuring_refuses_unusable_input(bad, error):
    args = dict(aligned=aligned_of(("a", 1.0, 1.3)), energy=energy_of([-30.0] * 200), max_gap_s=0.25, active_threshold_dbfs=-50.0)
    args.update(bad)
    with pytest.raises(error):
        measure_words(args["aligned"], args["energy"], max_gap_s=args["max_gap_s"], active_threshold_dbfs=args["active_threshold_dbfs"])


# ------------------------------------------------------------------------------------------------------------------------------
# Run statistics
# ------------------------------------------------------------------------------------------------------------------------------
def test_the_log_ratio_of_a_run_compares_total_times():
    observed = np.array([2.0, 2.0, 4.0, 1.0])
    expected = np.array([1.0, 1.0, 1.0, 1.0])
    assert window_log_ratio(observed, expected, 2) == pytest.approx([math.log(4 / 2), math.log(6 / 2), math.log(5 / 2)])
    assert window_log_ratio(observed, expected, 4) == pytest.approx([math.log(9 / 4)])
    assert len(window_log_ratio(observed, expected, 5)) == 0 and len(window_log_ratio(observed, expected, 0)) == 0


def test_the_mean_of_a_run_is_the_mean_of_its_entries():
    assert window_mean(np.array([1.0, 2.0, 6.0, 3.0]), 2) == pytest.approx([1.5, 4.0, 4.5])
    assert len(window_mean(np.array([1.0, 2.0]), 3)) == 0


def test_the_overall_pace_is_the_median_run_so_a_stretch_of_the_reading_does_not_move_it():
    expected = np.ones(60)
    steady = np.full(60, 1.0)
    assert overall_tempo(steady, expected) == pytest.approx(0.0, abs=1e-12)
    odd = steady.copy()
    odd[20:26] = 3.0                                         # six words three times slower: 15 of the 51 runs of ten touch them
    assert overall_tempo(odd, expected) == pytest.approx(0.0, abs=1e-12)
    assert overall_tempo(np.full(60, 2.0), expected) == pytest.approx(math.log(2.0))      # the whole reading twice as slow
    assert overall_tempo(np.array([]), np.array([])) == 0.0


def test_the_spread_of_a_run_shrinks_with_its_length_down_to_the_drift_and_the_floors_are_respected():
    model = NoiseModel(drift=0.03, word=0.2)
    assert noise_sigma(model, 16) == pytest.approx(math.sqrt(0.03 ** 2 + 0.2 ** 2 / 16))
    assert noise_sigma(model, 1_000_000) == pytest.approx(0.03, abs=1e-4)
    assert noise_sigma(model, 16, drift_floor=0.05, word_floor=0.3) == pytest.approx(math.sqrt(0.05 ** 2 + 0.3 ** 2 / 16))
    many = noise_sigma(model, np.array([4, 16]))
    assert many == pytest.approx([math.sqrt(0.03 ** 2 + 0.2 ** 2 / 4), math.sqrt(0.03 ** 2 + 0.2 ** 2 / 16)])


# ------------------------------------------------------------------------------------------------------------------------------
# Building the profile
# ------------------------------------------------------------------------------------------------------------------------------
def test_the_expected_slot_is_the_geometric_mean_of_the_baseline_slots_and_the_level_has_each_readings_offset_removed():
    takes = baseline_readings()
    profile = make_profile()
    slots = np.array([t.slot_s for t in takes])
    assert profile.slot_s == pytest.approx(list(np.exp(np.mean(np.log(slots), axis=0))), abs=1e-6)
    levels = np.array([t.level_db for t in takes])
    first = levels.mean(axis=0)
    offsets = np.median(levels - first, axis=1)
    assert profile.level_db == pytest.approx(list((levels - offsets[:, None]).mean(axis=0)), abs=1e-6)
    assert profile.words == make_tokens() and profile.n_takes == 6 and len(profile.slot_s) == len(profile.level_db) == N_WORDS
    assert profile.max_gap_s == GAP_CAP_S and profile.active_threshold_dbfs == ACTIVE_DBFS and profile.tempo_window_words == TEMPO_WINDOW_WORDS


def test_the_pattern_of_levels_is_the_same_whatever_overall_level_each_baseline_reading_had():
    plain = make_profile()
    shifted = [reading(1000 + k, tempo=0.95 if k % 2 == 0 else 1.05, level_offset=(-6.0, 0.0, 4.0, 9.0, -2.0, 1.0)[k]) for k in range(6)]
    other = build_word_profile(shifted, make_tokens(), max_gap_s=GAP_CAP_S, active_threshold_dbfs=ACTIVE_DBFS)
    a, b = np.array(plain.level_db), np.array(other.level_db)
    assert (a - a.mean()) == pytest.approx(b - b.mean(), abs=1e-5)


def test_a_known_spread_is_recovered_from_the_baseline_readings():
    for jitter in (0.05, 0.12, 0.25):
        profile = make_profile(jitter=jitter)
        assert profile.rate_noise.word == pytest.approx(jitter, rel=0.15)
    for level_jitter in (0.5, 1.2, 3.0):
        profile = make_profile(level_jitter=level_jitter)
        assert profile.level_noise.word == pytest.approx(level_jitter, rel=0.15)
    assert make_profile().tempo_sd == pytest.approx(0.065, abs=0.03)           # the two speakers differ by 10 % in pace


def test_the_spread_describes_a_reading_that_was_not_used_to_build_the_expectation():
    # With three baseline readings each is compared with the average of the other two, whose own chance variation adds to the difference (a factor
    # of about 1.22); a spread measured against an expectation that contains the reading itself would come out smaller than the chance variation (0.82).
    pace = make_profile(count=3, jitter=0.25).rate_noise.word
    level = make_profile(count=3, level_jitter=2.0).level_noise.word
    assert pace > 0.25 * 1.05 and level > 2.0 * 1.05


def test_the_level_spread_does_not_depend_on_the_overall_level_of_each_baseline_reading():
    offsets = (-6.0, 0.0, 4.0, 9.0, -2.0, 1.0)
    shifted = [reading(1000 + k, tempo=0.95 if k % 2 == 0 else 1.05, level_offset=offsets[k]) for k in range(6)]
    other = build_word_profile(shifted, make_tokens(), max_gap_s=GAP_CAP_S, active_threshold_dbfs=ACTIVE_DBFS)
    assert other.level_noise.word == pytest.approx(make_profile().level_noise.word, rel=0.02)


def test_the_spread_of_the_overall_pace_is_the_sample_standard_deviation_of_the_leave_one_out_paces():
    slots = np.array([t.slot_s for t in baseline_readings()])
    paces = []
    for b in range(len(slots)):
        expected = np.exp(np.log(np.delete(slots, b, axis=0)).mean(axis=0))
        window = np.log(np.convolve(slots[b], np.ones(10), "valid") / np.convolve(expected, np.ones(10), "valid"))
        paces.append(float(np.median(window)))
    assert make_profile().tempo_sd == pytest.approx(float(np.std(paces, ddof=1)), abs=1e-5)


def test_a_passage_so_short_that_only_one_run_length_can_be_measured_still_gets_a_spread():
    profile = make_profile(n=12)
    assert profile is not None and profile.rate_noise.drift == 0.0 and 0.03 < profile.rate_noise.word < 0.3 and profile.level_noise.drift == 0.0


def test_a_wandering_pace_shows_up_as_drift_that_does_not_average_out():
    n = N_WORDS

    def profile_with(wander_scale: float):
        rng = np.random.default_rng(5)
        takes = []
        for _ in range(6):
            wander = np.convolve(rng.normal(0.0, 0.08, n + 30), np.ones(30) / 30, mode="valid")[:n] * wander_scale    # slow variation along the reading
            slots = base_slots(n) * np.exp(wander + rng.normal(0.0, 0.05, n))
            takes.append(observations(slots, base_levels(n) + rng.normal(0.0, 1.0, n)))
        return build_word_profile(takes, make_tokens(n), max_gap_s=GAP_CAP_S, active_threshold_dbfs=ACTIVE_DBFS)

    assert profile_with(0.0).rate_noise.drift < 0.02
    assert profile_with(8.0).rate_noise.drift > 0.04


def test_the_profile_does_not_depend_on_the_order_of_the_readings_and_is_repeatable():
    takes = baseline_readings()
    one = build_word_profile(takes, make_tokens(), max_gap_s=GAP_CAP_S, active_threshold_dbfs=ACTIVE_DBFS)
    two = build_word_profile(list(reversed(takes)), make_tokens(), max_gap_s=GAP_CAP_S, active_threshold_dbfs=ACTIVE_DBFS)
    three = build_word_profile(takes, make_tokens(), max_gap_s=GAP_CAP_S, active_threshold_dbfs=ACTIVE_DBFS)
    assert one.model_dump_json() == two.model_dump_json() == three.model_dump_json()


def test_without_enough_readings_that_match_the_passage_there_is_no_profile():
    tokens = make_tokens()
    kw = dict(max_gap_s=GAP_CAP_S, active_threshold_dbfs=ACTIVE_DBFS)
    assert PROFILE_MIN_TAKES == 3
    assert build_word_profile(baseline_readings(2), tokens, **kw) is None
    assert build_word_profile(baseline_readings(3), tokens, **kw) is not None
    other_passage = [reading(7, tokens=[f"{t}q" for t in tokens]) for _ in range(6)]
    assert build_word_profile(other_passage, tokens, **kw) is None                       # none of the readings match the passage
    two_match = baseline_readings(2) + other_passage[:4]
    assert build_word_profile(two_match, tokens, **kw) is None                           # only two of six match
    assert build_word_profile(baseline_readings(), [], **kw) is None


def test_a_reading_that_does_not_match_the_passage_is_left_out_not_averaged_in():
    tokens = make_tokens()
    kw = dict(max_gap_s=GAP_CAP_S, active_threshold_dbfs=ACTIVE_DBFS)
    odd = reading(7, tokens=[f"{t}q" for t in tokens], tempo=3.0)
    profile = build_word_profile(baseline_readings(4) + [odd], tokens, **kw)
    assert profile.n_takes == 4
    assert profile.slot_s == build_word_profile(baseline_readings(4), tokens, **kw).slot_s


def test_a_word_measured_in_fewer_than_two_readings_has_no_expectation():
    takes = baseline_readings(3)
    slots = [np.array(t.slot_s) for t in takes]
    levels = [np.array(t.level_db) for t in takes]
    for k in (0, 1):                                          # word 5 is unmeasurable in two of the three readings
        slots[k][5] = np.nan
        levels[k][5] = np.nan
    broken = [observations(s, l) for s, l in zip(slots, levels)]
    profile = build_word_profile(broken, make_tokens(), max_gap_s=GAP_CAP_S, active_threshold_dbfs=ACTIVE_DBFS)
    assert profile.slot_s[5] is None and profile.level_db[5] is None
    assert profile.slot_s[4] is not None and profile.level_db[6] is not None


def test_a_profile_cannot_be_built_when_the_readings_are_too_short_to_measure_a_spread():
    tokens = make_tokens(8)
    short = [reading(k, n=8) for k in range(5)]
    assert build_word_profile(short, tokens, max_gap_s=GAP_CAP_S, active_threshold_dbfs=ACTIVE_DBFS) is None


def test_the_grid_of_run_lengths_is_fixed():
    assert NOISE_GRID == (6, 10, 16, 26, 40, 60)


# ------------------------------------------------------------------------------------------------------------------------------
# The profile in the baseline record
# ------------------------------------------------------------------------------------------------------------------------------
def test_a_baseline_file_written_before_profiles_existed_still_loads_and_verifies():
    old = record()
    assert old.word_profile is None and '"word_profile"' not in old.canonical_json()
    stored = json.loads(old.model_dump_json())
    stored.pop("word_profile")                                       # what the older builder wrote: no such field at all
    loaded = BaselineStatsRecord.model_validate_json(json.dumps(stored))
    assert loaded.verify_sha256() and loaded.sha256 == old.sha256 and loaded.word_profile is None


def test_a_profile_is_part_of_what_the_hash_covers():
    profile = make_profile()
    with_profile = record(word_profile=profile)
    assert with_profile.verify_sha256() and with_profile.sha256 != record().sha256
    tampered = with_profile.model_copy(update={"word_profile": profile.model_copy(update={"tempo_sd": 0.5})})
    assert not tampered.verify_sha256()
    again = BaselineStatsRecord.model_validate_json(with_profile.model_dump_json())
    assert again == with_profile and again.verify_sha256()


def test_the_public_statistics_do_not_expose_the_profile():
    assert "word_profile" not in record(word_profile=make_profile()).to_response_stats().model_dump()


@pytest.mark.parametrize("change", [
    dict(slot_s=[0.3]),                                                    # shorter than the words
    dict(level_db=[-20.0]),
    dict(words=[""] + make_tokens()[1:]),                                  # an empty word
    dict(n_takes=2),
    dict(tempo_sd=-0.1),
    dict(max_gap_s=0.0),
    dict(rate_noise={"drift": -0.1, "word": 0.1}),
])
def test_an_invalid_profile_is_refused(change):
    data = make_profile().model_dump()
    data.update(change)
    with pytest.raises(ValidationError):
        WordProfile(**data)


def test_slots_must_be_positive_and_levels_finite():
    data = make_profile().model_dump()
    data["slot_s"][3] = 0.0
    with pytest.raises(ValidationError, match="slot_s"):
        WordProfile(**data)
    data = make_profile().model_dump()
    data["level_db"][3] = float("inf")
    with pytest.raises(ValidationError):
        WordProfile(**data)
