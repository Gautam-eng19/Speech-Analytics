"""Custom passages (DEC-044): a user's own passage text and 2 to 6 of their own baseline recordings become a baseline the ordinary analysis uses.

Synthetic readings of the real passage p001 (tests/dataset_takes.human_layout) stand in for the user's recordings, the stand-in aligner finds the word
bursts, and a stand-in recogniser says what was "heard". Everything else is real: the service, the baseline builder shared with the dataset tool, the
file store, the providers that find custom ids, the analysis pipeline and the HTTP routes. The checks are the ones that matter to a user: a baseline is
made and the analysis finds a flaw in a reading against it; a recording that is not a reading of the passage, a passage too short, too few recordings
and duplicate files are refused with a clear reason; nothing but statistics is stored; the same input gives the same id and nothing is recomputed;
a custom id never reaches a project baseline and the other way round; deleting removes it.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "dataset"))
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "backend" / "tests"))

import dataset_takes as dt  # noqa: E402
from api_helpers import asgi_get  # noqa: E402
from app.api.deps import get_custom_service, get_pipeline  # noqa: E402
from app.core.baseline import BaselineNotFoundError, BaselineProvider  # noqa: E402
from app.core.cache import ResultCache  # noqa: E402
from app.core.passages import PassageCatalog  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.common import ErrorCode, FlawType  # noqa: E402
from app.schemas.contracts import BaselineStatsRecord  # noqa: E402
from app.schemas.request import AnalyzeRequest  # noqa: E402
from app.services.custom import CustomBaselineService, CustomError, CustomStore, custom_id_for  # noqa: E402
from app.services.pipeline import AnalysisPipeline, PipelineError  # noqa: E402
from test_profile_e2e import ENTRY, S3, WORDS  # noqa: E402

PASSAGE = ENTRY["text"]


class Recogniser:
    """Stand-in for Whisper: says what it is told, or fails."""

    def __init__(self, text: Optional[str] = PASSAGE, fail: bool = False) -> None:
        self.text, self.fail, self.calls = text, fail, 0

    def transcribe(self, audio):
        self.calls += 1
        if self.fail:
            raise RuntimeError("the model could not be loaded")
        return SimpleNamespace(text=self.text)


def wav_bytes(tmp: Path, name: str, layout: dt.Layout, seed: int) -> bytes:
    return dt.write_take(tmp, name, layout, seed).read_bytes()


def make_service(root: Path, aligner=None, recogniser="default") -> Tuple[CustomBaselineService, CustomStore, dt.BurstAligner]:
    aligner = aligner or dt.BurstAligner()
    store = CustomStore(root / "data")
    getter = None if recogniser is None else (lambda: Recogniser() if recogniser == "default" else recogniser)
    return CustomBaselineService(store, get_aligner=lambda: aligner, get_transcriber=getter), store, aligner


def pipeline_for(root: Path, store: CustomStore) -> AnalysisPipeline:
    return AnalysisPipeline(
        transcriber=Recogniser(), aligner=dt.BurstAligner(), baseline_provider=store.provider(), cache=ResultCache(root / "cache"),
        passages=PassageCatalog(root / "none.json", custom_path=store.passages_file),
    )


@pytest.fixture(scope="module")
def audio(tmp_path_factory) -> Dict[str, bytes]:
    tmp = tmp_path_factory.mktemp("custom_audio")
    files = {f"base_{n}": wav_bytes(tmp, f"base_{n}", dt.human_layout(WORDS, 100 + n, tempo=0.95 if n % 2 else 1.05, amplitude=0.1), n) for n in range(1, 5)}
    files["clean"] = wav_bytes(tmp, "clean", dt.human_layout(WORDS, 201, amplitude=0.1), 11)
    files["fast"] = wav_bytes(tmp, "fast", dt.speed_stretch(dt.human_layout(WORDS, 301, amplitude=0.1), *S3, 0.55), 21)
    return files


def three(audio) -> List[Tuple[str, bytes]]:
    return [(f"take{n}.wav", audio[f"base_{n}"]) for n in (1, 2, 3)]


@pytest.fixture(scope="module")
def made(tmp_path_factory, audio):
    root = tmp_path_factory.mktemp("custom_made")
    service, store, aligner = make_service(root)
    return root, service, store, aligner, service.create(PASSAGE, "My talk", three(audio))


# ------------------------------------------------------------------------------------------------------------------------------
def test_a_baseline_is_made_from_the_passage_and_three_recordings(made):
    root, service, store, aligner, result = made
    assert result.baseline_id == result.passage_id and result.baseline_id.startswith("custom-") and len(result.baseline_id) == 19
    assert (result.title, result.n_recordings, result.passage_word_count) == ("My talk", 3, len(WORDS))
    assert result.already_existed is False and result.word_profile_built and result.pitch_profile_built
    assert [t.filename for t in result.takes] == ["take1.wav", "take2.wav", "take3.wav"]
    assert all(t.timed_word_share == 1.0 and t.content_match == 1.0 and t.words_per_min > 60 and t.duration_s > 10 for t in result.takes)
    record = BaselineStatsRecord.model_validate_json(store.baseline_path(result.baseline_id).read_text(encoding="utf-8"))
    assert record.verify_sha256() and record.passage_id == result.baseline_id and record.word_profile is not None and record.word_profile.pitch is not None
    assert aligner.calls == 3 and set(aligner.texts) == {" ".join(PASSAGE.split())}          # the passage text IS the transcript the recordings are aligned to


def test_only_statistics_and_the_passage_are_stored_never_the_audio(made):
    root, _, store, _, result = made
    stored = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and "cache" not in p.parts)
    assert stored == [f"data/custom/baseline_stats/{result.baseline_id}.json", "data/custom/passages.json"]
    entries = json.loads(store.passages_file.read_text(encoding="utf-8"))
    assert [(e["passage_id"], e["title"], e["domain"]) for e in entries] == [(result.baseline_id, "My talk", "custom")]
    assert entries[0]["text"] == " ".join(PASSAGE.split())


def test_the_same_passage_and_recordings_are_the_same_baseline_and_nothing_is_recomputed(made, audio):
    _, service, store, aligner, first = made
    calls = aligner.calls
    again = service.create(PASSAGE.replace(" ", "  "), "Another title", list(reversed(three(audio))))        # spacing and file order do not matter
    assert again.baseline_id == first.baseline_id and again.already_existed is True and again.takes == []
    assert again.title == "My talk" and aligner.calls == calls and store.count() == 1
    assert custom_id_for(PASSAGE, [b for _, b in three(audio)]) == first.baseline_id
    assert custom_id_for(PASSAGE + " One more sentence.", [b for _, b in three(audio)]) != first.baseline_id


def test_the_analysis_finds_a_flaw_against_the_custom_baseline_and_not_in_a_clean_reading(made, audio):
    root, _, store, _, result = made
    pipeline = pipeline_for(root, store)
    request = AnalyzeRequest(baseline_id=result.baseline_id, passage_id=result.passage_id, manual_transcript=PASSAGE)
    fast = pipeline.analyze(audio["fast"], request)
    assert [f.type for f in fast.flaws if f.type == FlawType.TOO_FAST] and fast.baseline.baseline_id == result.baseline_id
    clean = pipeline.analyze(audio["clean"], request)
    assert clean.flaws == [] and clean.scores.composite_score == 100.0
    assert not any(n.code in ("baseline_without_profile", "pitch_not_judged") for n in clean.notes)


def test_two_recordings_work_but_the_word_by_word_comparison_needs_three(tmp_path, audio):
    service, store, _ = make_service(tmp_path)
    result = service.create(PASSAGE, None, three(audio)[:2])
    assert result.n_recordings == 2 and result.word_profile_built is False and result.pitch_profile_built is False
    assert result.title.endswith("…") and any("third recording" in w for w in result.warnings)
    pipeline = pipeline_for(tmp_path, store)
    out = pipeline.analyze(audio["clean"], AnalyzeRequest(baseline_id=result.baseline_id, passage_id=result.passage_id, manual_transcript=PASSAGE))
    assert any(n.code == "baseline_without_profile" for n in out.notes)                    # the analysis says so


# ------------------------------------------------------------------------------------------------------------------------------
def refused(service, passage, files, code, text):
    with pytest.raises(CustomError) as info:
        service.create(passage, None, files)
    assert info.value.code == code and text in info.value.detail, info.value.detail


def test_a_passage_that_is_too_short_or_has_one_sentence_or_is_blank_is_refused(tmp_path, audio):
    service, store, aligner = make_service(tmp_path)
    refused(service, "Too short to measure anything. Really.", three(audio), ErrorCode.VALIDATION_ERROR, "at least 30 are needed")
    one = " ".join(WORDS[:60]).replace(".", "").replace("!", "").replace("?", "")
    refused(service, one + ".", three(audio), ErrorCode.VALIDATION_ERROR, "at least two sentences")
    refused(service, "   ", three(audio), ErrorCode.VALIDATION_ERROR, "Enter the passage text")
    refused(service, "word. " * 500, three(audio), ErrorCode.VALIDATION_ERROR, "at most 400")
    assert aligner.calls == 0 and store.count() == 0                                         # refused before any work


def test_the_number_and_kind_of_recordings_are_checked(tmp_path, audio):
    service, store, aligner = make_service(tmp_path)
    refused(service, PASSAGE, three(audio)[:1], ErrorCode.VALIDATION_ERROR, "between 2 and 6")
    refused(service, PASSAGE, [(f"t{n}.wav", audio["base_1"] + bytes([n])) for n in range(7)], ErrorCode.VALIDATION_ERROR, "between 2 and 6")
    refused(service, PASSAGE, [("a.wav", audio["base_1"]), ("b.txt", audio["base_2"])], ErrorCode.UNSUPPORTED_AUDIO_FORMAT, "not a WAV or MP3")
    refused(service, PASSAGE, [("a.wav", audio["base_1"]), ("b.wav", b"")], ErrorCode.VALIDATION_ERROR, "is empty")
    refused(service, PASSAGE, [("a.wav", audio["base_1"]), ("b.wav", audio["base_1"])], ErrorCode.VALIDATION_ERROR, "same recording")
    refused(service, PASSAGE, [("a.wav", audio["base_1"]), ("../../etc/b.wav", b"not audio at all")], ErrorCode.UNSUPPORTED_AUDIO_FORMAT, "could not be decoded")
    assert aligner.calls <= 1 and store.count() == 0


def test_a_recording_that_does_not_read_the_passage_is_refused_and_a_doubtful_one_is_warned_about(tmp_path, audio):
    wrong = make_service(tmp_path / "wrong", recogniser=Recogniser("Something else entirely was said here today in this room."))[0]
    refused(wrong, PASSAGE, three(audio), ErrorCode.VALIDATION_ERROR, "does not seem to be a reading of this passage")
    words = PASSAGE.split()
    doubtful = Recogniser(" ".join("banana" if i % 3 == 2 else w for i, w in enumerate(words)))        # every third word misheard: about 0.67
    service, store, _ = make_service(tmp_path / "doubtful", recogniser=doubtful)
    result = service.create(PASSAGE, None, three(audio))
    assert result.warnings and "match the passage only" in result.warnings[0] and all(0.5 <= t.content_match < 0.99 for t in result.takes)


def test_without_the_speech_recogniser_the_content_check_is_skipped_not_fatal(tmp_path, audio):
    broken = make_service(tmp_path / "broken", recogniser=Recogniser(fail=True))[0]
    result = broken.create(PASSAGE, None, three(audio))
    assert all(t.content_match is None for t in result.takes) and result.word_profile_built
    none = make_service(tmp_path / "none", recogniser=None)[0]
    assert none.create(PASSAGE, "x", three(audio)).baseline_id == result.baseline_id


def test_a_recording_in_which_too_few_words_can_be_found_is_refused(tmp_path, audio):
    service, store, _ = make_service(tmp_path, aligner=dt.BurstAligner(drop=set(range(1, 30))))
    refused(service, PASSAGE, three(audio), ErrorCode.VALIDATION_ERROR, "of the passage words could be found")
    failing = make_service(tmp_path / "f", aligner=dt.BurstAligner(fail_with=RuntimeError("secret internal text")))[0]
    with pytest.raises(CustomError) as info:
        failing.create(PASSAGE, None, three(audio))
    assert info.value.code == ErrorCode.PROCESSING_ERROR and "secret" not in info.value.detail
    assert store.count() == 0


def test_the_number_of_custom_baselines_is_limited(tmp_path, audio, monkeypatch):
    from app.services import custom

    monkeypatch.setattr(custom.settings, "CUSTOM_MAX_BASELINES", 1)
    service, store, _ = make_service(tmp_path)
    service.create(PASSAGE, None, three(audio)[:2])
    refused(service, PASSAGE, three(audio), ErrorCode.VALIDATION_ERROR, "Delete one")


# ------------------------------------------------------------------------------------------------------------------------------
def test_custom_ids_only_reach_the_custom_directory_and_project_ids_never_do(tmp_path, made):
    _, _, store, _, result = made
    project = tmp_path / "project"
    project.mkdir()
    (project / "custom-aaaaaaaaaaaa.json").write_text("{}", encoding="utf-8")                # a file that must never be served as a project baseline
    mixed = BaselineProvider(project, custom_directory=store.baseline_dir)
    assert mixed.list_baselines() == [result.baseline_id]
    assert mixed.get(result.baseline_id).passage_id == result.baseline_id
    with pytest.raises(BaselineNotFoundError):
        BaselineProvider(project).load(result.baseline_id)                                   # no custom directory: not found
    (store.baseline_dir.parent / "p001.json").write_text("{}", encoding="utf-8")
    assert "p001" not in mixed.list_baselines()
    try:
        with pytest.raises(BaselineNotFoundError):
            mixed.load("custom-../p001")
    finally:
        (store.baseline_dir.parent / "p001.json").unlink()
    catalog = PassageCatalog(tmp_path / "missing.json", custom_path=store.passages_file)
    assert catalog.get_text(result.passage_id) == " ".join(PASSAGE.split()) and catalog.get("p001") is None
    assert PassageCatalog(tmp_path / "missing.json").get_text(result.passage_id) is None


# ------------------------------------------------------------------------------------------------------------------------------
# Over HTTP
# ------------------------------------------------------------------------------------------------------------------------------
def multipart(fields: Dict[str, str], files: List[Tuple[str, str, bytes]]) -> Tuple[List[Tuple[bytes, bytes]], bytes]:
    boundary = "----CustomPassageTestBoundary"
    parts: List[bytes] = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8"))
    for name, filename, content in files:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\nContent-Type: audio/wav\r\n\r\n'.encode() + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    return [(b"content-type", f"multipart/form-data; boundary={boundary}".encode()), (b"content-length", str(len(body)).encode())], body


async def call(method: str, path: str, headers=None, body: bytes = b""):
    scope = {"type": "http", "http_version": "1.1", "method": method, "path": path, "raw_path": path.encode("ascii"), "query_string": b"",
             "headers": headers or [], "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 8000)}
    status, chunks = [0], []

    async def send(msg):
        if msg["type"] == "http.response.start":
            status[0] = msg["status"]
        elif msg["type"] == "http.response.body":
            chunks.append(msg.get("body", b""))

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    await app(scope, receive, send)
    raw = b"".join(chunks).decode("utf-8")
    return status[0], (json.loads(raw) if raw else {})


@pytest.fixture()
def served(tmp_path):
    service, store, _ = make_service(tmp_path)
    pipeline = pipeline_for(tmp_path, store)
    app.dependency_overrides[get_custom_service] = lambda: service
    app.dependency_overrides[get_pipeline] = lambda: pipeline
    try:
        yield service, store, pipeline
    finally:
        app.dependency_overrides.clear()


def post_baseline(fields, files):
    headers, body = multipart(fields, files)
    return asyncio.run(call("POST", "/api/v1/custom/baselines", headers, body))


def test_over_http_the_baseline_is_made_listed_used_and_deleted(served, audio):
    service, store, pipeline = served
    files = [("baseline_audio", f"take{n}.wav", audio[f"base_{n}"]) for n in (1, 2, 3)]
    status, body = post_baseline({"passage_text": PASSAGE, "title": "My talk"}, files)
    assert status == 200 and body["baseline_id"].startswith("custom-") and body["word_profile_built"] is True and len(body["takes"]) == 3
    bid = body["baseline_id"]

    status, listing = asyncio.run(asgi_get("/api/v1/baselines"))
    (entry,) = listing["baselines"]
    assert status == 200 and entry["baseline_id"] == bid and entry["custom"] is True and entry["passage_title"] == "My talk"
    assert entry["passage_text"] == " ".join(PASSAGE.split()) and entry["passage_word_count"] == len(WORDS)

    headers, payload = multipart({"baseline_id": bid, "passage_id": bid, "manual_transcript": PASSAGE}, [("participant_audio", "me.wav", audio["fast"])])
    status, result = asyncio.run(call("POST", "/api/v1/analyze", headers, payload))
    assert status == 200 and any(f["type"] == "too_fast" for f in result["flaws"]) and result["baseline"]["baseline_id"] == bid

    assert asyncio.run(call("DELETE", f"/api/v1/custom/baselines/{bid}")) == (200, {"baseline_id": bid, "deleted": True})
    assert asyncio.run(asgi_get("/api/v1/baselines"))[1]["baselines"] == [] and not store.exists(bid)
    assert asyncio.run(call("DELETE", f"/api/v1/custom/baselines/{bid}"))[0] == 404
    status, error = asyncio.run(call("POST", "/api/v1/analyze", headers, payload))
    assert status == 404 and error["error"] == "BASELINE_NOT_FOUND"


def test_over_http_mistakes_come_back_as_documented_errors_without_internals(served, audio):
    files = [("baseline_audio", f"take{n}.wav", audio[f"base_{n}"]) for n in (1, 2)]
    status, body = post_baseline({"passage_text": "Short."}, files)
    assert status == 422 and body["error"] == "VALIDATION_ERROR" and "at least 30" in body["detail"]
    assert post_baseline({}, files)[1]["error"] == "VALIDATION_ERROR"
    status, body = post_baseline({"passage_text": PASSAGE}, files[:1])
    assert status == 422 and "between 2 and 6" in body["detail"]
    status, body = post_baseline({"passage_text": PASSAGE}, [])
    assert status == 422
    assert asyncio.run(call("DELETE", "/api/v1/custom/baselines/p001"))[0] == 422                 # a project baseline cannot be deleted
    assert asyncio.run(call("DELETE", "/api/v1/custom/baselines/custom-0123456789ab"))[0] == 404
    assert asyncio.run(call("DELETE", "/api/v1/custom/baselines/custom-..%2F..%2Fx"))[0] in (404, 422)


# ------------------------------------------------------------------------------------------------------------------------------
# Details the mutation check showed were not pinned down
# ------------------------------------------------------------------------------------------------------------------------------
def test_recordings_that_differ_a_lot_in_pace_get_a_warning_and_similar_ones_do_not(tmp_path, audio):
    similar = make_service(tmp_path / "similar")[0].create(PASSAGE, None, three(audio))
    assert not any("speaking pace" in w for w in similar.warnings)
    slow = wav_bytes(tmp_path, "slow", dt.human_layout(WORDS, 111, tempo=1.8, amplitude=0.1), 31)
    fast = wav_bytes(tmp_path, "fast2", dt.human_layout(WORDS, 112, tempo=0.6, amplitude=0.1), 32)
    mixed = make_service(tmp_path / "mixed")[0].create(PASSAGE, None, [("slow.wav", slow), ("fast.wav", fast), ("take1.wav", audio["base_1"])])
    assert any("differ a lot in speaking pace" in w for w in mixed.warnings)


def test_a_long_name_is_cut_and_a_blank_one_is_made_from_the_passage(tmp_path, audio):
    service, store, _ = make_service(tmp_path)
    result = service.create(PASSAGE, "N" * 200, three(audio)[:2])
    assert result.title == "N" * 80 and store.title_of(result.baseline_id) == "N" * 80
    assert store.title_of("custom-000000000000") is None


def test_the_id_ignores_spacing_and_saving_the_same_baseline_twice_keeps_one_passage_entry(made, audio):
    root, _, store, _, result = made
    recordings = [b for _, b in three(audio)]
    assert custom_id_for(PASSAGE.replace(" ", "   ") + "\n", recordings) == result.baseline_id
    record = store.provider().get(result.baseline_id, passage_id=result.baseline_id)
    store.save(record, "Renamed", " ".join(PASSAGE.split()))
    store.save(record, "Renamed again", " ".join(PASSAGE.split()))
    entries = json.loads(store.passages_file.read_text(encoding="utf-8"))
    assert [(e["passage_id"], e["title"]) for e in entries] == [(result.baseline_id, "Renamed again")]
    store.save(record, "My talk", " ".join(PASSAGE.split()))                                    # back to what the other tests expect
