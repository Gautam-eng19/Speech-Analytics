"""Tests for scripts/dataset/check_recordings.py (recording-protocol.md section 11).

Synthetic takes with known level, room noise, silences and defects are written as WAV files and judged. Covers normal input, every gate
(pass / warn / fail), unreadable or wrongly formatted files, the length expectation (group median, passage estimate, skipped), the CLI,
and repeated-run determinism.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Optional

import numpy as np
import pytest
import scipy.io.wavfile as wavfile

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "dataset"))

import check_recordings as cr  # noqa: E402

SR = 48_000


def synth(speech_s: float = 20.0, lead: float = 1.0, tail: float = 1.0, peak_db: float = -12.0, noise_db: float = -68.0,
          hum_hz: Optional[float] = None, hum_db: float = -60.0, seed: int = 0, steady: bool = False, rate: int = SR) -> np.ndarray:
    """A speech-like take: a harmonic tone modulated at syllable rate between two stretches of room noise."""
    rng = np.random.default_rng(seed)
    n = int(speech_s * rate)
    t = np.arange(n) / rate
    envelope = np.ones(n) if steady else 0.5 * (1.0 + np.sin(2 * np.pi * 3.5 * t))
    tone = sum(np.sin(2 * np.pi * 140.0 * k * t) / k for k in range(1, 6)) * envelope
    tone *= 10 ** (peak_db / 20) / np.max(np.abs(tone))
    x = np.concatenate([np.zeros(int(lead * rate)), tone, np.zeros(int(tail * rate))])
    x = x + rng.normal(0.0, 10 ** (noise_db / 20), len(x))
    if hum_hz:
        x = x + np.sqrt(2) * 10 ** (hum_db / 20) * np.sin(2 * np.pi * hum_hz * np.arange(len(x)) / rate)
    return x


def write(path: Path, x: np.ndarray, rate: int = SR, dtype: str = "int16") -> Path:
    if dtype == "int16":
        data = np.clip(np.round(x * 32768.0), -32768, 32767).astype(np.int16)
    elif dtype == "float32":
        data = x.astype(np.float32)
    elif dtype == "uint8":
        data = np.clip(np.round(x * 128.0 + 128.0), 0, 255).astype(np.uint8)
    else:
        raise ValueError(dtype)
    wavfile.write(str(path), rate, data)
    return path


def report(path: Path, **kwargs) -> cr.FileReport:
    return cr.check_files([path], **kwargs)[0]


def status(rep: cr.FileReport, name: str) -> str:
    return next(c.status for c in rep.checks if c.name == name)


def message(rep: cr.FileReport, name: str) -> str:
    return next(c.message for c in rep.checks if c.name == name)


@pytest.fixture
def clean(tmp_path) -> Path:
    return write(tmp_path / "rec_p001_spk_dev_01_base_01.wav", synth())


# ---------------------------------------------------------------------------------------------------------------------------------
# A good take
# ---------------------------------------------------------------------------------------------------------------------------------

class TestGoodTake:
    def test_a_clean_take_passes_every_check(self, clean):
        rep = report(clean)
        assert rep.status == cr.PASS, [(c.name, c.status, c.message) for c in rep.checks]
        assert {c.name for c in rep.checks} >= {"format", "size", "clipping", "peak level", "room noise", "start and end", "length", "hum"}

    def test_measurements_match_what_was_synthesised(self, clean):
        m = report(clean).measurements
        assert m["sample_rate"] == SR and m["channels"] == 1 and m["format"] == "16-bit PCM"
        assert m["peak_db"] == pytest.approx(-12.0, abs=0.3)
        assert m["noise_floor_db"] == pytest.approx(-68.0, abs=1.5)
        assert m["lead_s"] == pytest.approx(1.0, abs=0.1)
        assert m["tail_s"] == pytest.approx(1.0, abs=0.15)
        assert m["duration_s"] == pytest.approx(22.0, abs=0.01)
        assert m["clip_runs"] == 0

    def test_frame_levels_of_a_known_sine(self):
        x = np.sin(2 * np.pi * 1000 * np.arange(SR) / SR)  # amplitude 1: RMS 0.707 = -3.01 dBFS
        levels, frame, hop = cr.frame_levels_db(x, SR, 0.032, 0.010)
        assert frame == 1536 and hop == 480
        assert levels.mean() == pytest.approx(-3.01, abs=0.05)
        assert cr.frame_levels_db(np.zeros(100), SR, 0.032, 0.010)[0].size == 0

    def test_a_16_khz_file_is_accepted(self, tmp_path):
        rep = report(write(tmp_path / "t.wav", synth(rate=16_000), rate=16_000))
        assert status(rep, "format") == cr.PASS


# ---------------------------------------------------------------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------------------------------------------------------------

class TestClippingAndLevel:
    def test_clipped_take_fails_with_a_position_and_a_fix(self, tmp_path):
        x = synth(peak_db=-1.0)
        x[SR * 5:SR * 5 + 40] = 1.0  # 40 samples at full scale
        rep = report(write(tmp_path / "t.wav", x))
        assert rep.status == cr.FAIL and status(rep, "clipping") == cr.FAIL
        assert "5.00 s" in message(rep, "clipping") and "Lower the input volume" in message(rep, "clipping")

    def test_a_single_click_at_full_scale_is_not_reported_as_clipping(self, tmp_path):
        x = synth(peak_db=-12.0)
        x[SR * 5] = 1.0                 # one stray full-scale sample
        x[SR * 6:SR * 6 + 2] = -1.0     # and a two-sample run
        rep = report(write(tmp_path / "t.wav", x))
        assert status(rep, "clipping") == cr.PASS and rep.measurements["clip_runs"] == 0

    def test_runs_shorter_than_three_samples_are_not_clipping(self):
        x = np.zeros(1000)
        x[10:12] = 1.0
        x[100:103] = -1.0
        assert cr.clipping_runs(x, 0.999, 3) == [100]
        assert cr.clipping_runs(np.zeros(5), 0.999, 3) == []

    @pytest.mark.parametrize("name, peak, expected", [
        ("rec_p001_spk_dev_01_base_01.wav", -12.0, cr.PASS),
        ("rec_p001_spk_dev_01_base_01.wav", -3.0, cr.WARN),    # louder than the usual range
        ("rec_p001_spk_dev_01_base_01.wav", -22.0, cr.WARN),   # quieter than the usual range
        ("rec_p001_spk_dev_01_base_01.wav", -35.0, cr.FAIL),   # unusably quiet
        ("rec_p001_spk_dev_01_flaw_loud_02.wav", -3.0, cr.PASS),   # loud takes may go up to -2
        ("rec_p001_spk_dev_01_flaw_loud_02.wav", -1.5, cr.WARN),
        ("rec_p001_spk_dev_01_flaw_loud_02.wav", -0.3, cr.FAIL),   # at full scale
    ])
    def test_peak_level_gates(self, tmp_path, name, peak, expected):
        rep = report(write(tmp_path / name, synth(peak_db=peak)))
        assert status(rep, "peak level") == expected, message(rep, "peak level")

    def test_a_file_that_is_nearly_silent_is_not_usable(self, tmp_path):
        rep = report(write(tmp_path / "t.wav", synth(peak_db=-60.0, noise_db=-80.0)))
        assert rep.status == cr.FAIL and status(rep, "peak level") == cr.FAIL


class TestRoomNoise:
    @pytest.mark.parametrize("noise_db, expected", [(-68.0, cr.PASS), (-53.0, cr.WARN), (-45.0, cr.FAIL)])
    def test_noise_floor_gates(self, tmp_path, noise_db, expected):
        rep = report(write(tmp_path / "t.wav", synth(noise_db=noise_db, peak_db=-12.0)))
        assert status(rep, "room noise") == expected, message(rep, "room noise")

    def test_mains_hum_is_found_with_its_frequency(self, tmp_path):
        for hz in (50, 60):
            rep = report(write(tmp_path / f"hum{hz}.wav", synth(hum_hz=hz, hum_db=-60.0)))
            assert status(rep, "hum") == cr.WARN and f"{hz} Hz" in message(rep, "hum"), (hz, message(rep, "hum"))

    def test_no_hum_in_clean_noise(self, clean):
        assert status(report(clean), "hum") == cr.PASS

    def test_hum_is_skipped_when_there_is_not_enough_quiet_audio(self, tmp_path):
        rep = report(write(tmp_path / "t.wav", synth(lead=0.4, tail=0.4, steady=True)))
        assert status(rep, "hum") == cr.SKIP


class TestStartAndEnd:
    def test_speech_at_the_very_edge_fails(self, tmp_path):
        rep = report(write(tmp_path / "t.wav", synth(lead=0.02)))
        assert status(rep, "start and end") == cr.FAIL and "very start" in message(rep, "start and end")
        rep = report(write(tmp_path / "u.wav", synth(tail=0.01)))
        assert status(rep, "start and end") == cr.FAIL and "very end" in message(rep, "start and end")

    @pytest.mark.parametrize("lead, tail, expected", [(1.0, 1.0, cr.PASS), (0.15, 1.0, cr.WARN), (1.0, 3.5, cr.WARN)])
    def test_silence_before_and_after_the_speech(self, tmp_path, lead, tail, expected):
        rep = report(write(tmp_path / "t.wav", synth(lead=lead, tail=tail)))
        assert status(rep, "start and end") == expected, message(rep, "start and end")

    def test_a_file_without_any_silence_explains_why_the_noise_cannot_be_measured(self, tmp_path):
        rep = report(write(tmp_path / "t.wav", synth(lead=0.0, tail=0.0, steady=True)))
        assert status(rep, "start and end") == cr.FAIL and status(rep, "room noise") == cr.FAIL
        assert "stay silent for 1 second" in message(rep, "room noise")

    def test_a_silent_file_has_no_speech(self, tmp_path):
        rng = np.random.default_rng(1)
        rep = report(write(tmp_path / "t.wav", rng.normal(0, 10 ** (-70 / 20), SR * 15)))
        assert rep.status == cr.FAIL


class TestFormat:
    def test_stereo_is_a_warning_and_is_still_measured(self, tmp_path):
        x = synth()
        mono = report(write(tmp_path / "m.wav", x))
        path = tmp_path / "s.wav"
        wavfile.write(str(path), SR, np.stack([np.round(x * 32768).astype(np.int16)] * 2, axis=1))
        rep = report(path)
        assert status(rep, "format") == cr.WARN and "2 channels" in message(rep, "format")
        assert rep.measurements["peak_db"] == pytest.approx(mono.measurements["peak_db"], abs=0.05)

    @pytest.mark.parametrize("dtype, fragment", [("float32", "float"), ("uint8", "8-bit")])
    def test_other_sample_formats_warn_but_are_analysed(self, tmp_path, dtype, fragment):
        rep = report(write(tmp_path / "t.wav", synth(), dtype=dtype))
        assert status(rep, "format") == cr.WARN and fragment in message(rep, "format")
        assert rep.measurements["peak_db"] == pytest.approx(-12.0, abs=0.7)

    def test_an_unusual_sample_rate_warns(self, tmp_path):
        rep = report(write(tmp_path / "t.wav", synth(rate=22_050), rate=22_050))
        assert status(rep, "format") == cr.WARN and "22050 Hz" in message(rep, "format")

    def test_a_constant_offset_warns(self, tmp_path):
        rep = report(write(tmp_path / "t.wav", synth() + 0.05))
        assert status(rep, "signal offset") == cr.WARN


class TestSizeAndLength:
    def test_size_limit_uses_the_api_limit(self, tmp_path):
        path = write(tmp_path / "t.wav", synth())
        rep = report(path, gates=replace(cr.GATES, max_upload_bytes=path.stat().st_size - 1))
        assert status(rep, "size") == cr.FAIL and "10 MB" in message(rep, "size")

    def test_too_short_and_too_long(self, tmp_path):
        assert status(report(write(tmp_path / "s.wav", synth(speech_s=4.0))), "size") == cr.FAIL
        rep = report(write(tmp_path / "l.wav", synth(speech_s=20.0)), gates=replace(cr.GATES, max_duration_s=15.0))
        assert status(rep, "size") == cr.FAIL and "limit" in message(rep, "size")

    def test_length_is_compared_with_the_median_of_the_same_speakers_takes(self, tmp_path):
        for i, seconds in enumerate((20.0, 20.5, 19.5), start=1):
            write(tmp_path / f"rec_p001_spk_dev_01_base_{i:02d}.wav", synth(speech_s=seconds, seed=i))
        write(tmp_path / "rec_p001_spk_dev_01_clean_01.wav", synth(speech_s=28.0, seed=9))     # +33 % of the median
        write(tmp_path / "rec_p001_spk_dev_01_clean_02.wav", synth(speech_s=36.0, seed=10))    # +69 % of the median
        write(tmp_path / "rec_p001_spk_dev_02_base_01.wav", synth(speech_s=40.0, seed=11))     # another speaker: not compared
        reports = {r.file: r for r in cr.check_files(cr.collect([tmp_path]))}
        assert status(reports["rec_p001_spk_dev_01_base_01.wav"], "length") == cr.PASS
        assert status(reports["rec_p001_spk_dev_01_clean_01.wav"], "length") == cr.WARN
        failed = reports["rec_p001_spk_dev_01_clean_02.wav"]
        assert status(failed, "length") == cr.FAIL and "Words are probably missing or added" in message(failed, "length")
        assert status(reports["rec_p001_spk_dev_02_base_01.wav"], "length") == cr.SKIP

    def test_without_enough_takes_the_passage_gives_an_estimate(self, tmp_path):
        write(tmp_path / "rec_p001_spk_dev_01_base_01.wav", synth(speech_s=49.0))
        write(tmp_path / "rec_p001_spk_dev_01_base_02.wav", synth(speech_s=20.0, seed=3))
        passages = Path(__file__).parent.parent / "data" / "plan" / "passages_v1.json"
        reports = {r.file: r for r in cr.check_files(cr.collect([tmp_path]), cr.load_passage_sizes(passages))}
        ok = reports["rec_p001_spk_dev_01_base_01.wav"]
        assert status(ok, "length") == cr.PASS and "123 passage words" in message(ok, "length")
        assert status(reports["rec_p001_spk_dev_01_base_02.wav"], "length") == cr.FAIL  # 20 s for a 123-word passage

    def test_a_file_that_does_not_follow_the_naming_has_no_expectation(self, tmp_path):
        rep = report(write(tmp_path / "myvoice.wav", synth()))
        assert status(rep, "length") == cr.SKIP


class TestUnusableFiles:
    def test_not_a_wav_file(self, tmp_path):
        bad = tmp_path / "t.wav"
        bad.write_text("this is not audio", encoding="utf-8")
        rep = report(bad)
        assert rep.status == cr.FAIL and "cannot be checked" in message(rep, "file") and "Audacity" in message(rep, "file")

    def test_other_audio_formats_are_pointed_to_wav(self, tmp_path):
        rep = report(tmp_path / "voice.m4a") if (tmp_path / "voice.m4a").write_bytes(b"x") else None
        assert rep.status == cr.FAIL and ".m4a" in message(rep, "file")

    def test_an_almost_empty_file(self, tmp_path):
        rep = report(write(tmp_path / "t.wav", np.zeros(100)))
        assert rep.status == cr.FAIL and "almost empty" in message(rep, "file")

    def test_a_truncated_file(self, tmp_path):
        path = write(tmp_path / "t.wav", synth())
        path.write_bytes(path.read_bytes()[:30])
        assert report(path).status == cr.FAIL


# ---------------------------------------------------------------------------------------------------------------------------------
# Names, determinism, command line
# ---------------------------------------------------------------------------------------------------------------------------------

class TestNamesAndRepeatability:
    def test_names_are_parsed_by_the_protocol_pattern(self):
        assert cr.parse_name(Path("rec_p002_spk_test_03_flaw_loud_02.wav")) == {"passage": "p002", "speaker": "spk_test_03", "kind": "flaw_loud", "number": "02"}
        assert cr.parse_name(Path("something_else.wav")) == {}

    def test_same_files_give_identical_reports(self, tmp_path):
        write(tmp_path / "rec_p001_spk_dev_01_base_01.wav", synth(seed=1))
        write(tmp_path / "rec_p001_spk_dev_01_base_02.wav", synth(seed=2, noise_db=-52.0))
        files = cr.collect([tmp_path])
        first = json.dumps([asdict(r) for r in cr.check_files(files)], sort_keys=True)
        second = json.dumps([asdict(r) for r in cr.check_files(files)], sort_keys=True)
        assert first == second

    def test_collect_takes_wav_like_files_in_name_order_and_ignores_the_rest(self, tmp_path):
        for name in ("b.wav", "a.wav", "c.m4a", "notes.txt", "D.WAV"):
            (tmp_path / name).write_bytes(b"x")
        assert [p.name for p in cr.collect([tmp_path])] == ["D.WAV", "a.wav", "b.wav", "c.m4a"]


class TestCommandLine:
    def test_all_good_exits_zero_and_writes_json(self, clean, tmp_path, capsys):
        out = tmp_path / "report.json"
        assert cr.main([str(clean), "--json", str(out)]) == 0
        printed = capsys.readouterr().out
        assert "PASS  rec_p001_spk_dev_01_base_01.wav" in printed and "1 file(s): 1 ok, 0 with warnings, 0 to record again." in printed
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data[0]["file"] == clean.name and data[0]["status"] == "pass"

    def test_a_failing_file_exits_one_and_tells_what_to_do(self, tmp_path, capsys):
        write(tmp_path / "good.wav", synth())
        write(tmp_path / "noisy.wav", synth(noise_db=-45.0))
        assert cr.main([str(tmp_path)]) == 1
        printed = capsys.readouterr().out
        assert "FAIL  noisy.wav" in printed and "PASS  good.wav" in printed
        assert "room noise" in printed and "record that take again" in printed

    def test_strict_turns_warnings_into_failures(self, tmp_path):
        path = write(tmp_path / "t.wav", synth(peak_db=-3.0))
        assert cr.main([str(path)]) == 0
        assert cr.main([str(path), "--strict"]) == 1

    def test_nothing_to_check_exits_two(self, tmp_path, capsys):
        assert cr.main([str(tmp_path)]) == 2
        assert "No audio files" in capsys.readouterr().err

    def test_bad_passages_file_stops_with_a_message(self, clean, tmp_path):
        bad = tmp_path / "p.json"
        bad.write_text("{not json", encoding="utf-8")
        with pytest.raises(SystemExit, match="Cannot read the passages file"):
            cr.main([str(clean), "--passages", str(bad)])
