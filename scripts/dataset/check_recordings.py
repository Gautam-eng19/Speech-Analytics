"""Recording quality checker (TASK-122, docs/methodology/recording-protocol.md section 11).

Run it on a folder of freshly recorded WAV files, right after a session, to learn which takes are usable and, for the others, what to
change before recording again:

    python scripts/dataset/check_recordings.py path/to/folder
    python scripts/dataset/check_recordings.py take1.wav take2.wav --passages data/plan/passages_v1.json --json report.json

It looks only at the SIGNAL (format, clipping, level, room noise, silence at the ends, length, mains hum). It never judges the delivery
and never changes a file. Same files in, same report out. A file that fails is re-recorded, not repaired.

Exit code: 0 when no file fails, 1 when at least one fails (or warns with --strict), 2 when there is nothing to check.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import scipy.io.wavfile as wavfile
from scipy import signal

import passage_text as pt

PASS, WARN, FAIL, SKIP = "pass", "warn", "fail", "skip"
_RANK = {PASS: 0, SKIP: 0, WARN: 1, FAIL: 2}
AUDIO_SUFFIXES = {".wav", ".m4a", ".mp3", ".flac", ".aac", ".ogg", ".mp4", ".wma", ".aiff", ".aif"}


@dataclass(frozen=True)
class Gates:
    """Every threshold in one place (AGENTS.md section 20). Values come from the recording protocol, section 11."""

    max_upload_bytes: int = 10_485_760          # the API's default MAX_UPLOAD_BYTES
    max_duration_s: float = 300.0               # the API's default MAX_DURATION_S
    min_duration_s: float = 10.0                # shorter than this cannot be the whole passage
    good_sample_rates: Tuple[int, ...] = (16_000, 44_100, 48_000)
    clip_level: float = 0.999                   # |sample| at or above this counts as full scale
    clip_run: int = 3                           # this many full-scale samples in a row = clipping
    peak_normal_db: Tuple[float, float] = (-18.0, -6.0)   # expected loudest point of a normal take, dBFS (warn outside)
    peak_loud_max_db: float = -2.0              # loud takes may go up to here (warn above)
    peak_fail_db: float = -1.0                  # above this the take is at full scale (fail)
    peak_too_quiet_db: float = -30.0            # below this the take is unusably quiet (fail)
    noise_warn_db: float = -55.0                # room noise above this: warn
    noise_fail_db: float = -50.0                # room noise above this: fail (pauses cannot be told from silence)
    lead_tail_s: Tuple[float, float] = (0.3, 2.0)   # asked-for silence before and after the speech
    lead_tail_cut_s: float = 0.05               # less than this: speech starts or ends at the very edge of the file (fail)
    duration_warn_pct: float = 25.0             # length differs from the expected length by more than this: warn
    duration_fail_pct: float = 50.0             # ... fail
    group_min_takes: int = 3                    # takes needed to use the group's median length as the expectation
    hum_warn_db: float = 15.0                   # a mains-hum line this far above its surroundings: warn
    dc_warn: float = 0.01                       # constant offset of the signal: warn
    frame_s: float = 0.032                      # analysis frames as in the feature extraction
    hop_s: float = 0.010
    noise_percentile: float = 2.0               # room noise = this percentile of the frame levels (works with as little as ~2 % silence)
    speech_above_noise_db: float = 15.0         # a frame is speech when it is this far above the room noise ...
    speech_below_peak_db: float = 40.0          # ... and not more than this below the loudest point
    speech_cap_below_peak_db: float = 20.0      # the speech threshold never rises above this far below the loudest point
    words_per_second: float = pt.ESTIMATE_WORDS_PER_SECOND
    silence_allowance_s: float = 2.0            # lead + tail silence added to the passage-based length estimate


GATES = Gates()

_NAME = re.compile(r"^rec_(?P<passage>p\d+)_(?P<speaker>spk_(?:dev|test)_\d+)_(?P<kind>base|clean|flaw_[a-z]+)_(?P<number>\d+)$")


@dataclass
class Check:
    name: str
    status: str
    message: str
    value: Optional[Any] = None


@dataclass
class FileReport:
    file: str
    status: str
    checks: List[Check]
    measurements: Dict[str, Any]


def parse_name(path: Path) -> Dict[str, str]:
    """passage, speaker and kind from a file named by the protocol (7.3); empty when the name does not follow it."""
    match = _NAME.match(path.stem)
    return match.groupdict() if match else {}


# ---------------------------------------------------------------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------------------------------------------------------------

def to_float(data: np.ndarray) -> Tuple[np.ndarray, str]:
    """Samples scaled to -1..1 and a description of the sample format."""
    if data.dtype == np.int16:
        return data.astype(np.float64) / 32768.0, "16-bit PCM"
    if data.dtype == np.int32:
        return data.astype(np.float64) / 2147483648.0, "24/32-bit PCM"
    if data.dtype == np.uint8:
        return (data.astype(np.float64) - 128.0) / 128.0, "8-bit PCM"
    if np.issubdtype(data.dtype, np.floating):
        return data.astype(np.float64), f"{data.dtype.itemsize * 8}-bit float"
    raise ValueError(f"unsupported sample type {data.dtype}")


def frame_levels_db(x: np.ndarray, rate: int, frame_s: float, hop_s: float) -> Tuple[np.ndarray, int, int]:
    """RMS level (dBFS) of every analysis frame, plus the frame and hop size in samples."""
    frame, hop = int(round(frame_s * rate)), int(round(hop_s * rate))
    if len(x) < frame:
        return np.array([]), frame, hop
    cumulative = np.concatenate(([0.0], np.cumsum(x * x)))
    starts = np.arange(0, len(x) - frame + 1, hop)
    mean_square = (cumulative[starts + frame] - cumulative[starts]) / frame
    return 10.0 * np.log10(mean_square + 1e-12), frame, hop


def clipping_runs(x: np.ndarray, level: float, run: int) -> List[int]:
    """Start sample of every run of at least `run` consecutive full-scale samples."""
    full = (np.abs(x) >= level).astype(np.int8)
    if not full.any():
        return []
    edges = np.diff(np.concatenate(([0], full, [0])))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    return [int(s) for s, e in zip(starts, ends) if e - s >= run]


def hum_db(x: np.ndarray, rate: int, levels: np.ndarray, noise_db: float, frame: int, hop: int) -> Optional[Tuple[float, int]]:
    """Strength (dB above its surroundings) and frequency of the strongest mains-hum line (50/60 Hz and harmonics) in the quietest
    parts of the take, or None when there is not enough quiet audio (1 s) to measure."""
    quiet = np.flatnonzero(levels <= noise_db + 6.0)
    pieces, total = [], 0
    for i in quiet:
        pieces.append(x[i * hop:i * hop + hop])  # non-overlapping hop-sized pieces of the quiet frames
        total += hop
        if total >= 8 * rate:
            break
    if total < rate:
        return None
    segment = np.concatenate(pieces)
    freqs, power = signal.welch(segment, fs=rate, nperseg=min(len(segment), rate), noverlap=0)
    best: Optional[Tuple[float, int]] = None
    for f in (50, 60, 100, 120, 150, 180):
        line = power[(freqs >= f - 1.5) & (freqs <= f + 1.5)]
        around = power[((freqs >= f - 12) & (freqs <= f - 4)) | ((freqs >= f + 4) & (freqs <= f + 12))]
        if line.size == 0 or around.size == 0 or np.median(around) <= 0:
            continue
        strength = 10.0 * np.log10(line.max() / np.median(around))
        if best is None or strength > best[0]:
            best = (float(strength), f)
    return best


def measure(path: Path, gates: Gates = GATES) -> Dict[str, Any]:
    """Everything measured about one file. Raises ValueError with a plain message when the file cannot be read."""
    size = path.stat().st_size
    try:
        rate, raw = wavfile.read(str(path))
    except Exception as exc:  # the reader raises many types for damaged or non-WAV files; all mean "cannot be used"
        raise ValueError(f"not a readable WAV file ({type(exc).__name__}: {str(exc)[:80]})") from exc
    channels = 1 if raw.ndim == 1 else int(raw.shape[1])
    x, fmt = to_float(raw)
    if channels > 1:
        x = x.mean(axis=1)
    out: Dict[str, Any] = {"size_bytes": size, "sample_rate": int(rate), "channels": channels, "format": fmt,
                           "duration_s": len(x) / rate if rate else 0.0}
    if len(x) < int(0.5 * rate):
        raise ValueError("the file is almost empty (under half a second)")
    peak = float(np.max(np.abs(x)))
    out["peak_db"] = 20.0 * np.log10(peak) if peak > 0 else -120.0
    out["dc_offset"] = float(abs(np.mean(x)))
    out["clip_runs"] = clipping_runs(x, gates.clip_level, gates.clip_run)
    out["first_clip_s"] = out["clip_runs"][0] / rate if out["clip_runs"] else None
    levels, frame, hop = frame_levels_db(x, rate, gates.frame_s, gates.hop_s)
    out["noise_floor_db"] = float(np.percentile(levels, gates.noise_percentile))
    # A frame is speech when it is clearly above the room noise and not absurdly far below the loudest point; the cap keeps the
    # threshold below the speech itself when a take has no silence to measure the noise from.
    threshold = min(max(out["noise_floor_db"] + gates.speech_above_noise_db, out["peak_db"] - gates.speech_below_peak_db),
                    out["peak_db"] - gates.speech_cap_below_peak_db)
    speech = np.flatnonzero(levels > threshold)
    if speech.size == 0:
        out["lead_s"] = out["tail_s"] = None
    else:
        out["lead_s"] = float(speech[0] * hop / rate)
        out["tail_s"] = float(out["duration_s"] - (speech[-1] * hop + frame) / rate)
    out["hum"] = hum_db(x, rate, levels, out["noise_floor_db"], frame, hop)
    return out


# ---------------------------------------------------------------------------------------------------------------------------------
# Judging
# ---------------------------------------------------------------------------------------------------------------------------------

def _check(name: str, status: str, message: str, value: Any = None) -> Check:
    return Check(name, status, message, None if value is None else (round(value, 2) if isinstance(value, float) else value))


def expected_duration(name: Dict[str, str], group: Sequence[float], passages: Dict[str, int], gates: Gates) -> Tuple[Optional[float], str]:
    """(expected length in seconds, where it comes from) or (None, reason)."""
    if len(group) >= gates.group_min_takes:
        return float(median(group)), f"the median of {len(group)} takes of this speaker and passage"
    words = passages.get(name.get("passage", ""))
    if words:
        return words / gates.words_per_second + gates.silence_allowance_s, f"an estimate from the {words} passage words"
    return None, "needs at least 3 takes of the same speaker and passage, or --passages"


def judge(path: Path, m: Dict[str, Any], expected: Tuple[Optional[float], str], gates: Gates = GATES) -> FileReport:
    name = parse_name(path)
    kind = name.get("kind", "")
    checks: List[Check] = []

    # format -------------------------------------------------------------------------------------------------------------------
    problems = []
    if m["channels"] != 1:
        problems.append(f"{m['channels']} channels (record mono)")
    if m["format"] != "16-bit PCM":
        problems.append(f"{m['format']} (export as Signed 16-bit PCM)")
    if m["sample_rate"] not in gates.good_sample_rates:
        problems.append(f"{m['sample_rate']} Hz (use 44100 or 48000, the same for every file)")
    if problems:
        checks.append(_check("format", WARN, "Not the asked-for format: " + "; ".join(problems) + ". It can still be used, but export it the agreed way next time.",
                             f"{m['sample_rate']} Hz, {m['channels']} ch, {m['format']}"))
    else:
        checks.append(_check("format", PASS, f"{m['sample_rate']} Hz, mono, 16-bit PCM", f"{m['sample_rate']} Hz"))

    # size and length ----------------------------------------------------------------------------------------------------------
    d = m["duration_s"]
    if m["size_bytes"] > gates.max_upload_bytes:
        checks.append(_check("size", FAIL, f"{m['size_bytes'] / 1_048_576:.1f} MB is over the 10 MB the analysis accepts. Record in mono at 44100 or 48000 Hz, 16-bit.", m["size_bytes"] / 1_048_576))
    elif d > gates.max_duration_s:
        checks.append(_check("size", FAIL, f"{d:.0f} s is longer than the {gates.max_duration_s:.0f} s limit.", d))
    elif d < gates.min_duration_s:
        checks.append(_check("size", FAIL, f"Only {d:.1f} s long: too short to be the whole passage.", d))
    else:
        checks.append(_check("size", PASS, f"{d:.1f} s, {m['size_bytes'] / 1_048_576:.1f} MB", d))

    # clipping and peak --------------------------------------------------------------------------------------------------------
    if m["clip_runs"]:
        checks.append(_check("clipping", FAIL, f"Clipping: {len(m['clip_runs'])} stretch(es) of full-scale samples, the first at {m['first_clip_s']:.2f} s. "
                             "Clipped audio cannot be repaired. Lower the input volume by about 3 dB and record again.", len(m["clip_runs"])))
    else:
        checks.append(_check("clipping", PASS, "no clipping"))
    p = m["peak_db"]
    low, high = gates.peak_normal_db
    loud_take = kind == "flaw_loud"
    if p > gates.peak_fail_db:
        checks.append(_check("peak level", FAIL, f"The loudest point is {p:.1f} dBFS, at full scale. Lower the input volume by about 3 dB and record again.", p))
    elif p < gates.peak_too_quiet_db:
        checks.append(_check("peak level", FAIL, f"The loudest point is only {p:.1f} dBFS: far too quiet. Raise the input volume (or move closer to the microphone) and record again.", p))
    elif loud_take and p > gates.peak_loud_max_db:
        checks.append(_check("peak level", WARN, f"The loudest point is {p:.1f} dBFS; a loud take should stay at or below {gates.peak_loud_max_db:.0f} dBFS.", p))
    elif not loud_take and p > high:
        checks.append(_check("peak level", WARN, f"The loudest point is {p:.1f} dBFS, louder than the usual {low:.0f} to {high:.0f}. Lower the input volume a little so the loud takes have headroom.", p))
    elif not loud_take and p < low:
        checks.append(_check("peak level", WARN, f"The loudest point is {p:.1f} dBFS, quieter than the usual {low:.0f} to {high:.0f}. Raise the input volume a little.", p))
    else:
        checks.append(_check("peak level", PASS, f"loudest point {p:.1f} dBFS", p))

    # room noise ---------------------------------------------------------------------------------------------------------------
    n = m["noise_floor_db"]
    no_silence = m["lead_s"] is not None and min(m["lead_s"], m["tail_s"]) < gates.lead_tail_cut_s
    hint = " If the file has no stretch of silence the noise cannot be measured: stay silent for 1 second before and after reading." if no_silence else ""
    if n > gates.noise_fail_db:
        checks.append(_check("room noise", FAIL, f"The quiet parts are at {n:.1f} dBFS: too noisy, pauses cannot be told from silence. Switch off fans, turn mic boost down, "
                             "move to a quieter room, or use a headset." + hint, n))
    elif n > gates.noise_warn_db:
        checks.append(_check("room noise", WARN, f"The quiet parts are at {n:.1f} dBFS; about {gates.noise_warn_db:.0f} or lower is wanted. Check for fans, mic boost and background noise." + hint, n))
    else:
        checks.append(_check("room noise", PASS, f"quiet parts at {n:.1f} dBFS", n))

    # silence at the ends ------------------------------------------------------------------------------------------------------
    lead, tail = m["lead_s"], m["tail_s"]
    if lead is None:
        checks.append(_check("start and end", FAIL, "No speech found: the file looks silent."))
    else:
        edge_low, edge_high = gates.lead_tail_s
        if min(lead, tail) < gates.lead_tail_cut_s:
            side = "start" if lead < gates.lead_tail_cut_s else "end"
            checks.append(_check("start and end", FAIL, f"Speech reaches the very {side} of the file ({lead:.2f} s before, {tail:.2f} s after): it may be cut off. "
                                 "Stay silent for about 1 second before and after reading.", min(lead, tail)))
        elif min(lead, tail) < edge_low or max(lead, tail) > edge_high:
            checks.append(_check("start and end", WARN, f"Silence before the speech {lead:.2f} s, after it {tail:.2f} s; about {edge_low:g} to {edge_high:g} s each is wanted. "
                                 "Do not edit the file; start reading about 1 second after pressing Record.", min(lead, tail)))
        else:
            checks.append(_check("start and end", PASS, f"{lead:.2f} s before, {tail:.2f} s after", lead))

    # length against expectation -----------------------------------------------------------------------------------------------
    target, source = expected
    if target is None:
        checks.append(_check("length", SKIP, f"not checked ({source})"))
    else:
        off = 100.0 * (d - target) / target
        text = f"{d:.1f} s against about {target:.1f} s expected ({source}): {off:+.0f}%"
        if abs(off) > gates.duration_fail_pct:
            checks.append(_check("length", FAIL, text + ". Words are probably missing or added. Check the take against the passage and record again.", off))
        elif abs(off) > gates.duration_warn_pct:
            checks.append(_check("length", WARN, text + ". Listen to the take: is every word of the passage there?", off))
        else:
            checks.append(_check("length", PASS, text, off))

    # hum and offset -----------------------------------------------------------------------------------------------------------
    hum = m["hum"]
    if hum is None:
        checks.append(_check("hum", SKIP, "not checked (less than 1 s of quiet audio to measure)"))
    elif hum[0] >= gates.hum_warn_db:
        checks.append(_check("hum", WARN, f"A steady {hum[1]} Hz tone (mains hum) stands {hum[0]:.0f} dB above its surroundings. Try another USB port, unplug chargers, "
                             "move away from power cables.", hum[0]))
    else:
        checks.append(_check("hum", PASS, "no mains hum", hum[0]))
    if m["dc_offset"] > gates.dc_warn:
        checks.append(_check("signal offset", WARN, f"The signal sits {m['dc_offset']:.3f} away from zero (a faulty input). It does not stop the analysis.", m["dc_offset"]))

    worst = max((c.status for c in checks), key=lambda s: _RANK[s])
    measurements = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in m.items() if k not in ("clip_runs", "hum")}
    measurements["clip_runs"] = len(m["clip_runs"])
    measurements["hum_db"] = None if hum is None else round(hum[0], 1)
    return FileReport(path.name, worst, checks, measurements)


def unreadable(path: Path, reason: str) -> FileReport:
    return FileReport(path.name, FAIL, [Check("file", FAIL, reason + " Export the take from Audacity as WAV (Signed 16-bit PCM) and check that again.")], {})


def collect(inputs: Sequence[Path]) -> List[Path]:
    files: List[Path] = []
    for item in inputs:
        if item.is_dir():
            files += [p for p in item.iterdir() if p.suffix.lower() in AUDIO_SUFFIXES and p.is_file()]
        elif item.is_file():
            files.append(item)
    return sorted(set(files), key=lambda p: (p.name, str(p)))


def check_files(files: Sequence[Path], passages: Optional[Dict[str, int]] = None, gates: Gates = GATES) -> List[FileReport]:
    passages = passages or {}
    measured: Dict[Path, Dict[str, Any]] = {}
    errors: Dict[Path, str] = {}
    for path in files:
        if path.suffix.lower() != ".wav":
            errors[path] = f"This is a {path.suffix.lower()} file, not a WAV file."
            continue
        try:
            measured[path] = measure(path, gates)
        except ValueError as exc:
            errors[path] = f"The file cannot be checked: {exc}."
    groups: Dict[Tuple[str, str], List[float]] = {}
    for path, m in measured.items():
        n = parse_name(path)
        if n:
            groups.setdefault((n["passage"], n["speaker"]), []).append(m["duration_s"])
    reports = []
    for path in files:
        if path in errors:
            reports.append(unreadable(path, errors[path]))
            continue
        n = parse_name(path)
        group = groups.get((n.get("passage", ""), n.get("speaker", "")), []) if n else []
        reports.append(judge(path, measured[path], expected_duration(n, group, passages, gates), gates))
    return reports


def load_passage_sizes(path: Optional[Path]) -> Dict[str, int]:
    if path is None:
        return {}
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
        return {e["passage_id"]: pt.word_count(e["text"]) for e in entries}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f"Cannot read the passages file {path}: {exc}")


# ---------------------------------------------------------------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------------------------------------------------------------

SYMBOL = {PASS: "PASS", WARN: "WARN", FAIL: "FAIL", SKIP: "skip"}


def render(reports: Sequence[FileReport]) -> str:
    lines: List[str] = []
    for r in reports:
        lines.append(f"{SYMBOL[r.status]}  {r.file}")
        for c in r.checks:
            if c.status in (WARN, FAIL):
                lines.append(f"      {'x' if c.status == FAIL else '!'} {c.name}: {c.message}")
    counts = {s: sum(1 for r in reports if r.status == s) for s in (PASS, WARN, FAIL)}
    lines.append("")
    lines.append(f"{len(reports)} file(s): {counts[PASS]} ok, {counts[WARN]} with warnings, {counts[FAIL]} to record again.")
    if counts[FAIL]:
        lines.append("Fix the cause named under each FAIL, then record that take again. Do not edit or repair the audio.")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check recordings against the quality gates of the recording protocol.")
    parser.add_argument("inputs", nargs="+", type=Path, help="WAV files and/or folders that contain them")
    parser.add_argument("--passages", type=Path, default=None, help="passages file (data/plan/passages_v1.json): lets the length check work with few takes")
    parser.add_argument("--json", type=Path, default=None, dest="json_out", help="also write the full report as JSON")
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures (exit code 1)")
    args = parser.parse_args(argv)
    files = collect(args.inputs)
    if not files:
        print("No audio files found in the given paths.", file=sys.stderr)
        return 2
    reports = check_files(files, load_passage_sizes(args.passages))
    print(render(reports))
    if args.json_out:
        args.json_out.write_text(json.dumps([asdict(r) for r in reports], indent=1, sort_keys=True) + "\n", encoding="utf-8")
    failed = any(r.status == FAIL for r in reports) or (args.strict and any(r.status == WARN for r in reports))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
