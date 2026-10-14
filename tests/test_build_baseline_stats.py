"""Tests for scripts/dataset/build_baseline_stats.py.

Covers:
- Aggregation maths against hand-computed values (pooling, ddof=1, percentiles, rounding)
- Energy frame selection (active vs. all), pause-type handling, optional cross-sentence std
- Explicit BaselineBuildError for every statistic that cannot be computed (nothing invented)
- Determinism and input-order independence
- End-to-end build from a synthetic dataset (real preprocessing, F0, energy, rate, pauses),
  provenance checks (placeholder / mismatching hashes), split selection, overwrite protection,
  CLI exit codes, and a round trip through BaselineProvider
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pytest
import scipy.io.wavfile as wavfile

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "dataset"))

import build_baseline_stats as bbs  # noqa: E402
from app.core.baseline import BaselineProvider  # noqa: E402
from app.schemas.common import (  # noqa: E402
    AlignmentMethod,
    PauseBoundaryType,
    PauseDetectionSource,
)
from app.schemas.contracts import AlignedTranscript, AlignedWord  # noqa: E402
from app.schemas.response import PauseEvent  # noqa: E402

SR = 16000


def _pause(duration: float, kind: PauseBoundaryType) -> PauseEvent:
    return PauseEvent(
        start_s=1.0,
        end_s=1.0 + duration,
        duration_s=duration,
        detection_source=PauseDetectionSource.BOTH,
        boundary_type=kind,
    )


W, C, U = PauseBoundaryType.WITHIN_PHRASE, PauseBoundaryType.CROSS_SENTENCE, PauseBoundaryType.UNKNOWN


def _rec1() -> bbs.RecordingFeatures:
    return bbs.RecordingFeatures(
        recording_id="rec_a",
        f0_voiced_hz=np.array([100.0, 110.0, 120.0]),
        energy_db=np.array([-20.0, -30.0, -60.0]),
        rate_wpm=np.array([100.0, 120.0]),
        pauses=[_pause(0.3, W), _pause(0.5, W), _pause(0.8, C), _pause(0.25, U)],
    )


def _rec2() -> bbs.RecordingFeatures:
    return bbs.RecordingFeatures(
        recording_id="rec_b",
        f0_voiced_hz=np.array([130.0, 140.0]),
        energy_db=np.array([-25.0, -70.0]),
        rate_wpm=np.array([140.0]),
        pauses=[_pause(0.4, W), _pause(1.0, C)],
    )


def _aggregate(recordings=None, **kwargs):
    return bbs.aggregate_baseline_stats("p001", "1.0.0", recordings or [_rec1(), _rec2()], **kwargs)


# ------------------------------------------------------------- aggregation maths
def test_pooled_statistics_match_hand_computation():
    rec = _aggregate()
    # F0 pooled [100,110,120,130,140]: mean 120, sample std sqrt(250); linear percentiles 102 / 138.
    assert rec.f0_voiced_hz_mean == 120.0
    assert rec.f0_voiced_hz_std == pytest.approx(np.sqrt(250.0), abs=1e-6)
    assert rec.f0_voiced_hz_p05 == pytest.approx(102.0)
    assert rec.f0_voiced_hz_p95 == pytest.approx(138.0)
    assert rec.n_f0_voiced_frames == 5
    # Energy, active frames (>= -50 dBFS): [-20,-30,-25] -> mean -25, sample std 5.
    assert rec.energy_db_mean == -25.0 and rec.energy_db_std == 5.0
    assert rec.n_energy_frames == 3
    # Rate windows [100,120,140] -> mean 120, std 20.
    assert rec.rate_wpm_mean == 120.0 and rec.rate_wpm_std == 20.0 and rec.n_rate_windows == 3
    # Pauses: within [0.3,0.5,0.4] -> 0.4 / 0.1; cross [0.8,1.0] -> 0.9 / sqrt(0.02); 1 unknown ignored.
    assert rec.pause_within_phrase_mean_s == pytest.approx(0.4)
    assert rec.pause_within_phrase_std_s == pytest.approx(0.1)
    assert rec.pause_cross_sentence_mean_s == pytest.approx(0.9)
    assert rec.pause_cross_sentence_std_s == pytest.approx(0.141421, abs=1e-6)
    assert (rec.n_pauses_within_phrase, rec.n_pauses_cross_sentence, rec.n_pauses_unknown_boundary) == (3, 2, 1)
    assert rec.baseline_recording_ids == ["rec_a", "rec_b"]
    assert rec.verify_sha256()


def test_energy_all_frames_selection():
    rec = _aggregate(config=bbs.BaselineBuildConfig(energy_frame_selection="all"))
    assert rec.energy_db_mean == pytest.approx(-41.0)  # (-20-30-60-25-70)/5
    assert rec.n_energy_frames == 5
    assert rec.config_snapshot["energy_frame_selection"] == "all"


def test_energy_threshold_is_inclusive():
    rec = _aggregate(config=bbs.BaselineBuildConfig(energy_active_threshold_dbfs=-30.0))
    assert rec.n_energy_frames == 3  # -20, -30, -25 (the -30 frame is kept)


def test_single_cross_sentence_pause_leaves_std_unset():
    rec1 = _rec1()
    rec = bbs.aggregate_baseline_stats("p001", "1.0.0", [rec1])
    assert rec.n_pauses_cross_sentence == 1
    assert rec.pause_cross_sentence_mean_s == pytest.approx(0.8)
    assert rec.pause_cross_sentence_std_s is None  # not 0.0: one observation has no spread


def test_values_are_rounded_and_snapshot_documents_conventions():
    rec = _aggregate()
    for name in ("f0_voiced_hz_std", "pause_cross_sentence_std_s"):
        value = getattr(rec, name)
        assert value == round(value, 6)
    snap = rec.config_snapshot
    assert snap["std_ddof"] == 1 and snap["round_decimals"] == 6
    assert snap["energy_frame_selection"] == "active" and snap["energy_active_threshold_dbfs"] == -50.0


def test_aggregation_is_deterministic_and_order_independent():
    a = _aggregate([_rec1(), _rec2()])
    b = _aggregate([_rec2(), _rec1()])
    c = _aggregate([_rec1(), _rec2()])
    assert a.sha256 == b.sha256 == c.sha256
    assert a == b


def test_extra_snapshot_is_recorded_and_changes_hash():
    plain = _aggregate()
    extra = _aggregate(extra_snapshot={"splits": "dev"})
    assert extra.config_snapshot["splits"] == "dev"
    assert extra.sha256 != plain.sha256


def test_inputs_not_mutated():
    r = _rec1()
    before = (r.f0_voiced_hz.copy(), r.energy_db.copy(), r.rate_wpm.copy())
    bbs.aggregate_baseline_stats("p001", "1.0.0", [r])
    assert all(np.array_equal(x, y) for x, y in zip(before, (r.f0_voiced_hz, r.energy_db, r.rate_wpm)))


# ----------------------------------------------------- explicit failures (no invention)
def _with(rec: bbs.RecordingFeatures, **changes) -> bbs.RecordingFeatures:
    data = dict(
        recording_id=rec.recording_id, f0_voiced_hz=rec.f0_voiced_hz, energy_db=rec.energy_db,
        rate_wpm=rec.rate_wpm, pauses=rec.pauses,
    )
    data.update(changes)
    return bbs.RecordingFeatures(**data)


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"f0_voiced_hz": np.array([120.0])}, "F0"),
        ({"f0_voiced_hz": np.array([])}, "F0"),
        ({"energy_db": np.array([-20.0, -70.0])}, "energy"),          # only 1 active frame
        ({"energy_db": np.array([-80.0, -70.0, -90.0])}, "energy"),    # no active frames
        ({"rate_wpm": np.array([100.0])}, "speech rate"),
        ({"rate_wpm": np.array([])}, "speech rate"),
        ({"pauses": [_pause(0.3, W), _pause(0.8, C)]}, "within-phrase"),   # 1 within pause: no std
        ({"pauses": [_pause(0.3, W), _pause(0.5, W)]}, "cross-sentence"),  # no cross pause
        ({"f0_voiced_hz": np.array([100.0, np.nan, 120.0])}, "non-finite"),
        ({"energy_db": np.array([-20.0, np.inf, -30.0])}, "non-finite"),
    ],
)
def test_uncomputable_statistics_raise_explicit_error(changes, match):
    with pytest.raises(bbs.BaselineBuildError, match=match):
        bbs.aggregate_baseline_stats("p001", "1.0.0", [_with(_rec1(), **changes)])


def test_no_recordings_and_duplicate_ids_rejected():
    with pytest.raises(bbs.BaselineBuildError, match="at least one"):
        bbs.aggregate_baseline_stats("p001", "1.0.0", [])
    with pytest.raises(bbs.BaselineBuildError, match="duplicate"):
        bbs.aggregate_baseline_stats("p001", "1.0.0", [_rec1(), _rec1()])


@pytest.mark.parametrize(
    "kwargs",
    [{"energy_frame_selection": "loud"}, {"energy_active_threshold_dbfs": float("nan")}, {"decimals": -1}, {"decimals": 13}],
)
def test_invalid_build_config_rejected(kwargs):
    with pytest.raises(ValueError):
        bbs.BaselineBuildConfig(**kwargs)


# =============================================================== end-to-end dataset
def _tone(freq: float, n: int) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / SR
    return 0.5 * np.sin(2 * np.pi * freq * t)


def _synthetic_recording(freq: float) -> Tuple[np.ndarray, AlignedTranscript]:
    """24 tone 'words' (0.4 s) with 0.1 s gaps, plus three real pauses:
    0.4 s after w5 and 0.3 s after w17 (within phrase), 0.6 s after w11 (cross sentence)."""
    special_gap = {5: 0.4, 11: 0.6, 17: 0.3}
    chunks: List[np.ndarray] = []
    words: List[AlignedWord] = []
    cursor = 0
    for i in range(24):
        n_word = int(0.4 * SR)
        text = f"w{i}." if i == 11 else f"w{i}"
        words.append(AlignedWord(word=text, start_s=cursor / SR, end_s=(cursor + n_word) / SR, confidence=0.9))
        chunks.append(_tone(freq, n_word))
        cursor += n_word
        if i < 23:
            n_gap = int(special_gap.get(i, 0.1) * SR)
            chunks.append(np.zeros(n_gap))
            cursor += n_gap
    audio = np.concatenate(chunks)
    transcript = AlignedTranscript(
        text=" ".join(w.word for w in words),
        words=words,
        alignment_method=AlignmentMethod.WHISPERX,
        total_coverage_pct=0.8,
    )
    return audio, transcript


def _write_recording(root: Path, rec_id: str, freq: float, split: str, **overrides) -> dict:
    audio, transcript = _synthetic_recording(freq)
    raw = root / "data" / "raw"
    aligned_dir = root / "data" / "processed" / "alignments"
    raw.mkdir(parents=True, exist_ok=True)
    aligned_dir.mkdir(parents=True, exist_ok=True)
    wav_path = raw / f"{rec_id}.wav"
    wavfile.write(wav_path, SR, (audio * 32767).astype(np.int16))
    align_path = aligned_dir / f"{rec_id}.alignment.json"
    align_path.write_text(transcript.model_dump_json(), encoding="utf-8")
    entry = {
        "recording_id": rec_id,
        "passage_id": "p001",
        "speaker_id": f"spk_{split}_01",
        "category": "baseline_effective",
        "split": split,
        "audio_file": f"data/raw/{rec_id}.wav",
        "sha256_audio": hashlib.sha256(wav_path.read_bytes()).hexdigest(),
        "alignment_file": f"data/processed/alignments/{rec_id}.alignment.json",
        "sha256_alignment": hashlib.sha256(align_path.read_bytes()).hexdigest(),
        "dataset_version": "1.0.0",
    }
    entry.update(overrides)
    return entry


def _write_manifest(root: Path, entries: List[dict]) -> Path:
    meta = root / "data" / "metadata"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "manifest.json").write_text(json.dumps(entries), encoding="utf-8")
    return root / "data"


@pytest.fixture(scope="module")
def two_recording_dataset(tmp_path_factory):
    root = tmp_path_factory.mktemp("dataset")
    entries = [
        _write_recording(root, "rec_p001_dev_base_01", 150.0, "dev"),
        _write_recording(root, "rec_p001_test_base_01", 200.0, "test"),
    ]
    return _write_manifest(root, entries)


def test_end_to_end_build_from_synthetic_dataset(two_recording_dataset):
    rec = bbs.build_for_passage(two_recording_dataset, "p001", ["dev"])
    assert rec.baseline_recording_ids == ["rec_p001_dev_base_01"]
    assert rec.dataset_version == "1.0.0"
    assert 145.0 < rec.f0_voiced_hz_mean < 155.0            # a 150 Hz tone
    assert rec.f0_voiced_hz_p05 <= rec.f0_voiced_hz_mean <= rec.f0_voiced_hz_p95
    # Preprocessing scales the typical speech level to -26 dBFS, which for a steady sine is its frame level;
    # partially filled frames at word edges pull the active-frame mean slightly below that.
    assert -27.5 < rec.energy_db_mean < -25.9
    assert rec.n_rate_windows >= 2 and rec.rate_wpm_mean > 0
    assert (rec.n_pauses_within_phrase, rec.n_pauses_cross_sentence) == (2, 1)
    assert rec.pause_within_phrase_mean_s == pytest.approx(0.35, abs=0.01)   # 0.4 s and 0.3 s
    assert rec.pause_cross_sentence_mean_s == pytest.approx(0.6, abs=0.01)
    assert rec.pause_cross_sentence_std_s is None
    assert rec.config_snapshot["splits"] == "dev"
    assert rec.config_snapshot["preprocess.target_sample_rate"] == 16000
    assert "f0.fmin" in rec.config_snapshot and "pause.align_min_gap_s" in rec.config_snapshot
    assert rec.verify_sha256()


def test_end_to_end_build_is_deterministic(two_recording_dataset):
    a = bbs.build_for_passage(two_recording_dataset, "p001", ["dev"])
    b = bbs.build_for_passage(two_recording_dataset, "p001", ["dev"])
    assert a.sha256 == b.sha256 and a == b


def test_splits_control_which_recordings_contribute(two_recording_dataset):
    dev_only = bbs.build_for_passage(two_recording_dataset, "p001", ["dev"])
    both = bbs.build_for_passage(two_recording_dataset, "p001", ["dev", "test"])
    assert both.baseline_recording_ids == ["rec_p001_dev_base_01", "rec_p001_test_base_01"]
    assert both.f0_voiced_hz_mean > dev_only.f0_voiced_hz_mean + 10.0  # 200 Hz recording pooled in
    assert both.n_f0_voiced_frames > dev_only.n_f0_voiced_frames
    assert both.sha256 != dev_only.sha256


def test_unknown_passage_or_split_without_baselines_fails(two_recording_dataset):
    with pytest.raises(bbs.BaselineBuildError, match="no baseline_effective"):
        bbs.build_for_passage(two_recording_dataset, "p404", ["dev"])
    with pytest.raises(bbs.BaselineBuildError, match="no baseline_effective"):
        bbs.build_for_passage(two_recording_dataset, "p001", [])


def test_placeholder_and_mismatching_hashes_rejected(tmp_path):
    placeholder = _write_recording(tmp_path, "rec_x", 150.0, "dev", sha256_audio="0" * 64)
    data_dir = _write_manifest(tmp_path, [placeholder])
    with pytest.raises(bbs.BaselineBuildError, match="placeholder"):
        bbs.build_for_passage(data_dir, "p001", ["dev"])

    wrong = _write_recording(tmp_path, "rec_x", 150.0, "dev", sha256_audio="a" * 64)
    data_dir = _write_manifest(tmp_path, [wrong])
    with pytest.raises(bbs.BaselineBuildError, match="mismatch"):
        bbs.build_for_passage(data_dir, "p001", ["dev"])


def test_missing_files_and_manifest_rejected(tmp_path):
    with pytest.raises(bbs.BaselineBuildError, match="manifest not found"):
        bbs.build_for_passage(tmp_path / "data", "p001", ["dev"])

    entry = _write_recording(tmp_path, "rec_x", 150.0, "dev", audio_file="data/raw/absent.wav")
    data_dir = _write_manifest(tmp_path, [entry])
    with pytest.raises(bbs.BaselineBuildError, match="not found"):
        bbs.build_for_passage(data_dir, "p001", ["dev"])


def test_alignment_outside_audio_is_rejected(tmp_path):
    entry = _write_recording(tmp_path, "rec_x", 150.0, "dev")
    align_path = tmp_path / entry["alignment_file"]
    transcript = AlignedTranscript.model_validate_json(align_path.read_text(encoding="utf-8"))
    shifted = transcript.model_copy(update={"words": [
        AlignedWord(word=w.word, start_s=w.start_s + 60.0, end_s=w.end_s + 60.0, confidence=0.9)
        for w in transcript.words
    ]})
    align_path.write_text(shifted.model_dump_json(), encoding="utf-8")
    entry["sha256_alignment"] = hashlib.sha256(align_path.read_bytes()).hexdigest()
    data_dir = _write_manifest(tmp_path, [entry])
    with pytest.raises(bbs.BaselineBuildError, match="invalid alignment"):
        bbs.build_for_passage(data_dir, "p001", ["dev"])


def test_silent_recording_rejected(tmp_path):
    entry = _write_recording(tmp_path, "rec_x", 150.0, "dev")
    wav_path = tmp_path / entry["audio_file"]
    wavfile.write(wav_path, SR, np.zeros(SR * 5, dtype=np.int16))
    entry["sha256_audio"] = hashlib.sha256(wav_path.read_bytes()).hexdigest()
    data_dir = _write_manifest(tmp_path, [entry])
    with pytest.raises(bbs.BaselineBuildError, match="silent"):
        bbs.build_for_passage(data_dir, "p001", ["dev"])


def test_write_stats_and_provider_round_trip(two_recording_dataset, tmp_path):
    rec = bbs.build_for_passage(two_recording_dataset, "p001", ["dev"])
    path = bbs.write_stats(rec, tmp_path / "out")
    assert path.name == "p001.json"
    assert BaselineProvider(tmp_path / "out").get("p001") == rec
    with pytest.raises(bbs.BaselineBuildError, match="already exists"):
        bbs.write_stats(rec, tmp_path / "out")
    assert bbs.write_stats(rec, tmp_path / "out", overwrite=True) == path


def test_cli_success_failure_and_no_output_on_failure(two_recording_dataset, tmp_path, capsys):
    out = tmp_path / "cli_out"
    code = bbs.main(["--data-dir", str(two_recording_dataset), "--passage-id", "p001",
                     "--splits", "dev", "--output-dir", str(out)])
    assert code == 0 and (out / "p001.json").is_file()
    assert "[OK] p001" in capsys.readouterr().out
    # Existing file is protected.
    assert bbs.main(["--data-dir", str(two_recording_dataset), "--passage-id", "p001",
                     "--splits", "dev", "--output-dir", str(out)]) == 1
    # One failing passage does not hide the failure and writes nothing for it.
    code = bbs.main(["--data-dir", str(two_recording_dataset), "--passage-id", "p404",
                     "--splits", "dev", "--output-dir", str(out), "--overwrite"])
    assert code == 1 and not (out / "p404.json").exists()
    assert "[FAIL] p404" in capsys.readouterr().err


def test_cli_energy_frames_option_is_recorded(two_recording_dataset, tmp_path):
    out = tmp_path / "all_frames"
    assert bbs.main(["--data-dir", str(two_recording_dataset), "--passage-id", "p001",
                     "--splits", "dev", "--energy-frames", "all", "--output-dir", str(out)]) == 0
    stored = json.loads((out / "p001.json").read_text(encoding="utf-8"))
    assert stored["config_snapshot"]["energy_frame_selection"] == "all"


def test_cli_requires_explicit_splits():
    with pytest.raises(SystemExit):
        bbs.main(["--passage-id", "p001"])


def test_empty_manifest_is_not_buildable(tmp_path):
    """A dataset with no registered recordings (the state of a fresh clone) must fail loudly, never write defaults."""
    data_dir = _write_manifest(tmp_path, [])
    with pytest.raises(bbs.BaselineBuildError, match="no baseline_effective recordings for passage 'p001'"):
        bbs.build_for_passage(data_dir, "p001", ["dev"])


# ================================================================ word profile
sys.path.insert(0, str(Path(__file__).parent.parent / "backend" / "tests"))

from profile_helpers import baseline_readings, make_tokens  # noqa: E402


def _with_words(readings):
    return [
        bbs.RecordingFeatures(
            f"rec_{k}", np.array([100.0, 110.0, 120.0]), np.array([-20.0, -30.0, -60.0]), np.array([100.0, 120.0]),
            [_pause(0.3, W), _pause(0.5, W), _pause(0.8, C)], words=obs,
        )
        for k, obs in enumerate(readings)
    ]


def test_the_profile_is_added_without_changing_any_overall_statistic():
    plain = bbs.aggregate_baseline_stats("p001", "1.0.0", _with_words([None] * 6))
    profiled = bbs.aggregate_baseline_stats("p001", "1.0.0", _with_words(baseline_readings()), passage_text=" ".join(make_tokens()))
    assert plain.word_profile is None and profiled.word_profile is not None
    assert profiled.word_profile.n_takes == 6 and profiled.word_profile.words == make_tokens()
    assert profiled.model_dump(exclude={"word_profile", "sha256"}) == plain.model_dump(exclude={"word_profile", "sha256"})
    assert profiled.sha256 != plain.sha256 and profiled.verify_sha256() and plain.verify_sha256()


def test_the_pitch_part_of_the_profile_is_built_when_the_recordings_have_pitch_movement_and_otherwise_left_out_without_harm():
    text = " ".join(make_tokens())
    with_pitch = bbs.aggregate_baseline_stats("p001", "1.0.0", _with_words(baseline_readings(pitch=True)), passage_text=text)
    without = bbs.aggregate_baseline_stats("p001", "1.0.0", _with_words(baseline_readings()), passage_text=text)
    assert with_pitch.word_profile.pitch is not None and without.word_profile.pitch is None and without.verify_sha256() and with_pitch.verify_sha256()
    assert without.word_profile.model_dump(exclude={"pitch"}) == with_pitch.word_profile.model_dump(exclude={"pitch"})      # pace and loudness are profiled the same
    assert with_pitch.sha256 != without.sha256


def test_the_profile_is_repeatable_and_independent_of_the_order_of_the_recordings():
    text = " ".join(make_tokens())
    readings = baseline_readings()
    one = bbs.aggregate_baseline_stats("p001", "1.0.0", _with_words(readings), passage_text=text)
    two = bbs.aggregate_baseline_stats("p001", "1.0.0", list(reversed(_with_words(readings))), passage_text=text)
    assert one.sha256 == two.sha256 and one == two


def test_there_is_no_profile_without_the_passage_text_or_without_three_recordings_that_have_words():
    text = " ".join(make_tokens())
    assert bbs.aggregate_baseline_stats("p001", "1.0.0", _with_words(baseline_readings())).word_profile is None
    assert bbs.aggregate_baseline_stats("p001", "1.0.0", _with_words(baseline_readings()), passage_text="").word_profile is None
    assert bbs.aggregate_baseline_stats("p001", "1.0.0", _with_words(baseline_readings(2) + [None] * 4), passage_text=text).word_profile is None
    assert bbs.aggregate_baseline_stats("p001", "1.0.0", _with_words(baseline_readings(3) + [None] * 3), passage_text=text).word_profile is not None


def test_a_recording_without_words_defaults_to_none():
    assert bbs.RecordingFeatures("rec_a", np.array([1.0]), np.array([1.0]), np.array([1.0]), []).words is None


def _alphabetic_recording(jitter_seed: int):
    """40 tone words with alphabetic names (so their cleaned tokens differ), 0.25 to 0.4 s long, with gaps that vary a little from reading to reading."""
    rng = np.random.default_rng(jitter_seed)
    names = make_tokens(40)
    chunks: List[np.ndarray] = []
    words: List[AlignedWord] = []
    cursor = 0
    for i, name in enumerate(names):
        n_word = int((0.25 + 0.15 * ((i * 7) % 5) / 4) * SR * float(np.exp(rng.normal(0.0, 0.05))))
        mark = "." if i % 10 == 9 else "," if i % 10 == 4 else ""
        words.append(AlignedWord(word=name + mark, start_s=cursor / SR, end_s=(cursor + n_word) / SR, confidence=0.9))
        chunks.append(_tone(150.0 + 3 * (i % 5), n_word))
        cursor += n_word
        if i < len(names) - 1:
            n_gap = int((0.5 if i % 10 == 9 else 0.3 if i % 10 == 4 else 0.1) * SR * float(np.exp(rng.normal(0.0, 0.05))))
            chunks.append(np.zeros(n_gap))
            cursor += n_gap
    transcript = AlignedTranscript(text=" ".join(w.word for w in words), words=words, alignment_method=AlignmentMethod.WHISPERX, total_coverage_pct=0.8)
    return np.concatenate(chunks), transcript


def _profile_dataset(root: Path, recordings: int, passage_text: bool = True) -> Path:
    raw = root / "data" / "raw"
    aligned_dir = root / "data" / "processed" / "alignments"
    raw.mkdir(parents=True, exist_ok=True)
    aligned_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for k in range(recordings):
        audio, transcript = _alphabetic_recording(k)
        rec_id = f"rec_p001_spk_dev_01_base_{k + 1:02d}"
        wav_path = raw / f"{rec_id}.wav"
        wavfile.write(wav_path, SR, (audio * 32767).astype(np.int16))
        align_path = aligned_dir / f"{rec_id}.alignment.json"
        align_path.write_text(transcript.model_dump_json(), encoding="utf-8")
        entries.append({
            "recording_id": rec_id, "passage_id": "p001", "speaker_id": "spk_dev_01", "category": "baseline_effective", "split": "dev",
            "audio_file": f"data/raw/{rec_id}.wav", "sha256_audio": hashlib.sha256(wav_path.read_bytes()).hexdigest(),
            "alignment_file": f"data/processed/alignments/{rec_id}.alignment.json", "sha256_alignment": hashlib.sha256(align_path.read_bytes()).hexdigest(),
            "dataset_version": "1.0.0",
        })
    data = _write_manifest(root, entries)
    if passage_text:
        text = _alphabetic_recording(0)[1].text
        (data / "metadata" / "passages.json").write_text(json.dumps([{"passage_id": "p001", "title": "t", "text": text}]), encoding="utf-8")
    return data


def test_building_from_a_dataset_reads_the_passage_text_and_builds_the_profile(tmp_path):
    data = _profile_dataset(tmp_path, recordings=3)
    record = bbs.build_for_passage(data, "p001", ["dev"])
    profile = record.word_profile
    assert profile is not None and profile.n_takes == 3 and profile.words == make_tokens(40)
    assert profile.max_gap_s == 0.25 and profile.active_threshold_dbfs == -50.0
    assert all(slot is not None and 0.25 < slot < 0.8 for slot in profile.slot_s)           # a word plus the silence after it, capped
    assert all(level is not None and -35.0 < level < -20.0 for level in profile.level_db)   # scaled to a speech level of -26 dBFS
    assert record.verify_sha256() and bbs.build_for_passage(data, "p001", ["dev"]).sha256 == record.sha256


def test_without_the_passage_text_or_with_two_recordings_the_baseline_is_built_without_a_profile(tmp_path):
    assert bbs.build_for_passage(_profile_dataset(tmp_path / "a", 3, passage_text=False), "p001", ["dev"]).word_profile is None
    assert bbs.build_for_passage(_profile_dataset(tmp_path / "b", 2), "p001", ["dev"]).word_profile is None


def test_the_command_line_says_whether_a_profile_was_built(tmp_path, capsys):
    data = _profile_dataset(tmp_path / "with", 3)
    assert bbs.main(["--data-dir", str(data), "--passage-id", "p001", "--splits", "dev"]) == 0
    out = capsys.readouterr().out
    assert "word profile built" in out and "pitch part" in out                                  # built, or said not to be (the synthetic voice has pitch)
    bare = _profile_dataset(tmp_path / "without", 3, passage_text=False)
    assert bbs.main(["--data-dir", str(bare), "--passage-id", "p001", "--splits", "dev"]) == 0
    assert "NO word profile" in capsys.readouterr().out
