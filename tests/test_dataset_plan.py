"""Tests for scripts/dataset/make_plan.py and passage_text.py (recording-protocol.md sections 4, 5 and 7).

Covers: the take counts promised by the protocol, nested tiers, naming, where flaws are placed, the pause positions, determinism, input
validation (plain-language errors, no overwriting of a plan that may hold progress), and the generated on-screen prompter.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "dataset"))

import make_plan as mp  # noqa: E402
import passage_text as pt  # noqa: E402
from app.schemas.request import ID_PATTERN  # noqa: E402

PASSAGES_FILE = Path(__file__).parent.parent / "data" / "plan" / "passages_v1.json"
TAKE_ID = re.compile(r"^rec_p\d+_spk_(dev|test)_\d{2}_(base|clean|flaw_(fast|slow|pause|quiet|loud))_\d{2}$")


@pytest.fixture(scope="module")
def passages() -> List[mp.Passage]:
    return mp.load_passages(PASSAGES_FILE)


def plan(passages, dev=2, test=2, tier="recommended", seed=7):
    return mp.make_plan(passages, dev, test, tier, seed)


def by(rows, **match):
    return [r for r in rows if all(r[k] == v for k, v in match.items())]


def sentence_of_word(passage: mp.Passage, global_word: int) -> int:
    starts = passage.sentence_starts
    return max(i for i, s in enumerate(starts, start=1) if s <= global_word)


# ---------------------------------------------------------------------------------------------------------------------------------
# Passages
# ---------------------------------------------------------------------------------------------------------------------------------

class TestPassages:
    def test_committed_passages_are_valid_and_match_their_declared_size(self):
        for entry in json.loads(PASSAGES_FILE.read_text(encoding="utf-8")):
            errors, warnings = pt.validate_passage(entry)
            assert errors == [] and warnings == [], entry["passage_id"]
            assert 8 <= len(pt.split_sentences(entry["text"])) <= 10
            assert entry["target_word_count"] == pt.word_count(entry["text"])

    def test_sentences_and_words(self):
        text = "One two three. Four five? Six!"
        assert pt.split_sentences(text) == ["One two three.", "Four five?", "Six!"]
        assert pt.passage_words(text) == [["One", "two", "three."], ["Four", "five?"], ["Six!"]]
        assert pt.word_count(text) == 6

    @pytest.mark.parametrize("text, fragment", [
        ("Call me at seven 7 now. " * 6, "digits"),
        ("Fish & chips are good. " * 6, "'&'"),
        ("The USB cable is here. " * 6, "acronym"),
        ("Dr. Smith is here. " * 6, "abbreviation"),
        ("Only two sentences here. Really only two.", "sentences"),
        ("First one. Second one. Third one. Fourth one. Fifth one. Sixth one without a stop", "does not end"),
    ])
    def test_unusable_text_is_rejected_with_a_plain_message(self, text, fragment):
        errors, _ = pt.validate_passage({"passage_id": "x", "text": text})
        assert any(fragment in e for e in errors), errors

    def test_missing_text_and_size_warnings(self):
        assert pt.validate_passage({"passage_id": "x"})[0]
        _, warnings = pt.validate_passage({"passage_id": "x", "text": "A b c. D e f. G h i. J k l. M n o. P q r.", "target_word_count": 99})
        assert any("recommended" in w for w in warnings) and any("target_word_count" in w for w in warnings)

    def test_loading_rejects_bad_files_and_unknown_ids(self, tmp_path):
        with pytest.raises(mp.PlanError, match="Cannot read"):
            mp.load_passages(tmp_path / "missing.json")
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps([{"passage_id": "p9", "text": "Only one sentence 5."}]), encoding="utf-8")
        with pytest.raises(mp.PlanError, match="cannot be used"):
            mp.load_passages(bad)
        with pytest.raises(mp.PlanError, match="Unknown passage id"):
            mp.load_passages(PASSAGES_FILE, ["nope"])
        assert [p.passage_id for p in mp.load_passages(PASSAGES_FILE, ["p002", "p001"])] == ["p002", "p001"]


# ---------------------------------------------------------------------------------------------------------------------------------
# Counts, tiers, names
# ---------------------------------------------------------------------------------------------------------------------------------

class TestCounts:
    @pytest.mark.parametrize("dev, test, tier, total", [
        (1, 0, "pilot", 9), (2, 2, "pilot", 9),
        (2, 2, "minimum", 36), (2, 1, "minimum", 28),
        (2, 2, "recommended", 112), (2, 1, "recommended", 86),
    ])
    def test_totals_match_the_protocol(self, passages, dev, test, tier, total):
        assert len(plan(passages, dev, test, tier)) == total

    def test_recommended_composition(self, passages):
        rows = plan(passages, 2, 2, "recommended")
        count = lambda c: len(by(rows, category=c))
        assert (count("flawed_human_controlled"), count("clean_control"), count("baseline_effective")) == (80, 20, 12)
        rows = plan(passages, 2, 1, "recommended")
        assert (len(by(rows, category="flawed_human_controlled")), len(by(rows, category="clean_control"))) == (60, 14)

    def test_pilot_is_nine_takes_of_one_dev_speaker_with_strong_flaws_only(self, passages):
        rows = plan(passages, 3, 2, "pilot")
        assert {r["speaker_id"] for r in rows} == {"spk_dev_01"} and {r["passage_id"] for r in rows} == {"p001"}
        assert len(by(rows, category="baseline_effective")) == 3 and len(by(rows, category="clean_control")) == 1
        flawed = by(rows, category="flawed_human_controlled")
        assert {r["flaw_type"] for r in flawed} == set(mp.FLAW_TYPES) and {r["intensity"] for r in flawed} == {"strong"}

    def test_tiers_are_nested_so_a_pilot_is_never_wasted(self, passages):
        ids = {t: {r["take_id"] for r in plan(passages, 2, 2, t)} for t in mp.TIERS}
        assert ids["pilot"] <= ids["minimum"] <= ids["recommended"]

    def test_baseline_takes_come_only_from_dev_speakers(self, passages):
        rows = plan(passages, 2, 2, "recommended")
        assert {r["split"] for r in by(rows, category="baseline_effective")} == {"dev"}
        for r in rows:
            assert r["split"] == ("dev" if "_dev_" in r["speaker_id"] else "test")

    def test_ids_are_unique_well_formed_and_valid_for_the_api(self, passages):
        rows = plan(passages, 2, 2, "recommended")
        ids = [r["take_id"] for r in rows]
        assert len(set(ids)) == len(ids)
        for take_id in ids:
            assert TAKE_ID.match(take_id), take_id
            assert re.match(ID_PATTERN, take_id)

    def test_take_numbers_follow_intensity(self, passages):
        for r in by(plan(passages), category="flawed_human_controlled"):
            number = int(r["take_id"][-2:])
            assert (r["intensity"], r["severity_label"]) == {1: ("moderate", "medium"), 2: ("strong", "high")}[number]

    def test_order_is_a_running_number_per_speaker_with_baseline_first(self, passages):
        rows = plan(passages)
        for speaker in {r["speaker_id"] for r in rows}:
            mine = by(rows, speaker_id=speaker)
            assert [r["order"] for r in mine] == list(range(1, len(mine) + 1))
        first = by(rows, speaker_id="spk_dev_01", passage_id="p001")
        assert [r["category"] for r in first[:5]] == ["baseline_effective"] * 3 + ["clean_control"] * 2

    def test_plan_csv_is_plain_ascii_so_spreadsheets_show_it_correctly(self, passages, tmp_path):
        mp.write_plan(tmp_path, plan(passages), passages, "recommended", False)
        raw = (tmp_path / "plan.csv").read_bytes()
        assert raw.isascii(), [c for c in raw.decode("utf-8") if ord(c) > 127]

    def test_instruction_and_status_columns_are_filled(self, passages):
        for r in plan(passages):
            assert len(r["instruction"]) > 40
            assert (r["status"], r["attempts"]) == ("todo", 0)


# ---------------------------------------------------------------------------------------------------------------------------------
# Where the flaws go
# ---------------------------------------------------------------------------------------------------------------------------------

class TestPlacement:
    def test_no_flaw_type_is_recorded_twice_in_a_row(self, passages):
        rows = plan(passages)
        for speaker in {r["speaker_id"] for r in rows}:
            for pid in ("p001", "p002"):
                flawed = by(rows, speaker_id=speaker, passage_id=pid, category="flawed_human_controlled")
                assert all(a["flaw_type"] != b["flaw_type"] for a, b in zip(flawed, flawed[1:])), (speaker, pid)

    def test_flaws_sit_in_sentences_three_to_six_and_a_pair_never_shares_a_sentence(self, passages):
        by_id = {p.passage_id: p for p in passages}
        rows = plan(passages)
        for speaker in ("spk_dev_01", "spk_test_02"):
            for pid, passage in by_id.items():
                used: Dict[str, List[int]] = {}
                for r in by(rows, speaker_id=speaker, passage_id=pid, category="flawed_human_controlled"):
                    sentence = sentence_of_word(passage, r["pause_after_word"] if r["flaw_type"] == "excessive_pause" else r["stretch_first_word"])
                    assert 3 <= sentence <= 6, r["take_id"]
                    if r["flaw_type"] == "excessive_pause" and int(r["take_id"][-2:]) == 2:
                        assert sentence <= 5  # the silence is AFTER this sentence, and sentence 7 is never reached
                    used.setdefault(r["flaw_type"], []).append(sentence)
                for flaw, sentences in used.items():
                    assert len(set(sentences)) == len(sentences), (speaker, pid, flaw, sentences)

    def test_speed_and_energy_stretches_are_whole_sentences_long_enough_for_the_flaw(self, passages):
        by_id = {p.passage_id: p for p in passages}
        for r in by(plan(passages), category="flawed_human_controlled"):
            if r["flaw_type"] == "excessive_pause":
                continue
            passage = by_id[r["passage_id"]]
            sentence = sentence_of_word(passage, r["stretch_first_word"])
            words = passage.sentences[sentence - 1]
            assert r["stretch_first_word"] == passage.sentence_starts[sentence - 1]
            assert r["stretch_last_word"] == r["stretch_first_word"] + len(words) - 1
            assert len(words) >= mp.MIN_WORDS[r["flaw_type"]], r["take_id"]

    def test_a_too_short_sentence_is_never_chosen(self, passages):
        p002 = {p.passage_id: p for p in passages}["p002"]
        assert len(p002.sentences[5]) == 6  # sentence 6 of "Morning market" is too short to carry any flaw
        for r in by(plan(passages), passage_id="p002", category="flawed_human_controlled"):
            if r["flaw_type"] != "excessive_pause":
                assert r["stretch"] != "S6", r["take_id"]

    def test_default_table_is_used_when_every_sentence_is_long_enough(self, passages):
        p001 = {p.passage_id: p for p in passages}["p001"]
        assert mp.choose_sentences(p001, "too_fast") == {1: 3, 2: 5}
        assert mp.choose_sentences(p001, "too_slow") == {1: 4, 2: 6}
        assert mp.choose_sentences(p001, "excessive_pause") == {1: 4, 2: 5}

    def test_phrase_pause_is_inside_a_phrase_and_the_boundary_pause_follows_a_sentence_end(self, passages):
        by_id = {p.passage_id: p for p in passages}
        for r in by(plan(passages), flaw_type="excessive_pause"):
            words = by_id[r["passage_id"]].all_words
            after = r["pause_after_word"]
            if r["take_id"].endswith("_01"):
                assert not re.search(r"[,.;:?!]$", words[after - 1]), r["take_id"]
                assert words[after - 1].lower() not in mp.FUNCTION_WORDS
                sentence = sentence_of_word(by_id[r["passage_id"]], after)
                inside = after - by_id[r["passage_id"]].sentence_starts[sentence - 1] + 1
                assert inside >= 3 and len(by_id[r["passage_id"]].sentences[sentence - 1]) - inside >= 3
            else:
                assert words[after - 1][-1] in ".?!", r["take_id"]
                assert (r["stretch_first_word"], r["stretch_last_word"]) == (after, after + 1)

    def test_phrase_pause_position_rules(self):
        assert mp.phrase_pause_position("a b".split()) is None
        assert mp.phrase_pause_position("one two three four five six seven eight".split()) == 4  # nearest the middle, ties go to the earlier word
        assert mp.phrase_pause_position("we are in the on it so or by it".split()) is None  # only function words: a pause there would be unnatural
        assert mp.phrase_pause_position("we are in the end of it so by it".split()) == 5  # "end" is the only content word
        position = mp.phrase_pause_position("first, second, third, fourth, fifth, sixth, seventh".split())
        assert position is None  # every word carries a comma
        assert mp.phrase_pause_position("Alpha beta gamma delta epsilon zeta eta theta".split()) in (4, 5)

    def test_a_passage_without_a_suitable_sentence_gives_a_clear_error(self):
        short = mp.Passage("px", "Short", tuple(tuple(f"w{i}" for i in range(5)) for _ in range(8)))
        with pytest.raises(mp.PlanError, match="no sentence among 3 to 6"):
            mp.choose_sentences(short, "too_fast")

    def test_instructions_name_the_planned_sentence_and_the_numbers(self, passages):
        rows = {r["take_id"]: r for r in plan(passages)}
        fast = rows["rec_p001_spk_dev_01_flaw_fast_02"]
        assert "sentence 5" in fast["instruction"] and "1.8 times faster" in fast["instruction"]
        assert float(fast["target_duration_s_est"]) < float(fast["normal_duration_s_est"])
        slow = rows["rec_p001_spk_dev_01_flaw_slow_02"]
        assert float(slow["target_duration_s_est"]) > float(slow["normal_duration_s_est"])
        assert "14 dB" in rows["rec_p001_spk_dev_01_flaw_loud_02"]["instruction"] and "clipping" in rows["rec_p001_spk_dev_01_flaw_loud_02"]["instruction"]
        assert "8 dB lower" in rows["rec_p001_spk_dev_01_flaw_quiet_01"]["instruction"]
        assert "3 to 4 seconds" in rows["rec_p001_spk_dev_01_flaw_pause_02"]["instruction"]
        assert "1.5 to 2 seconds" in rows["rec_p001_spk_dev_01_flaw_pause_01"]["instruction"]


# ---------------------------------------------------------------------------------------------------------------------------------
# Determinism and stability
# ---------------------------------------------------------------------------------------------------------------------------------

class TestDeterminism:
    def test_same_arguments_give_byte_identical_files(self, passages, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        rows = plan(passages, seed=11)
        mp.write_plan(a, rows, passages, "recommended", False)
        mp.write_plan(b, plan(passages, seed=11), passages, "recommended", False)
        names = sorted(p.name for p in a.iterdir())
        assert names == sorted(p.name for p in b.iterdir()) and len(names) == 6  # plan, log, 4 prompters
        for name in names:
            assert (a / name).read_bytes() == (b / name).read_bytes(), name

    def test_another_seed_changes_the_order_only(self, passages):
        one, two = plan(passages, seed=1), plan(passages, seed=2)
        assert {r["take_id"] for r in one} == {r["take_id"] for r in two}
        assert [r["take_id"] for r in one] != [r["take_id"] for r in two]

    def test_adding_a_speaker_does_not_change_anyone_else(self, passages):
        small, large = plan(passages, 2, 1), plan(passages, 2, 2)
        for speaker in ("spk_dev_01", "spk_dev_02", "spk_test_01"):
            assert by(small, speaker_id=speaker) == by(large, speaker_id=speaker)


# ---------------------------------------------------------------------------------------------------------------------------------
# Invalid input and files
# ---------------------------------------------------------------------------------------------------------------------------------

class TestInputsAndFiles:
    @pytest.mark.parametrize("dev, test, tier, message", [
        (0, 2, "minimum", "dev speaker"), (1, -1, "minimum", "between 1 and 20"), (15, 6, "minimum", "between 1 and 20"), (2, 2, "huge", "Unknown tier"),
    ])
    def test_bad_arguments_are_refused(self, passages, dev, test, tier, message):
        with pytest.raises(mp.PlanError, match=message):
            mp.make_plan(passages, dev, test, tier, 1)

    def test_a_plan_that_may_hold_progress_is_not_overwritten(self, passages, tmp_path):
        rows = plan(passages)
        mp.write_plan(tmp_path, rows, passages, "recommended", False)
        (tmp_path / "plan.csv").write_text("my progress", encoding="utf-8")
        with pytest.raises(mp.PlanError, match="already exists"):
            mp.write_plan(tmp_path, rows, passages, "recommended", False)
        assert (tmp_path / "plan.csv").read_text(encoding="utf-8") == "my progress"
        mp.write_plan(tmp_path, rows, passages, "recommended", True)
        assert (tmp_path / "plan.csv").read_text(encoding="utf-8").startswith("order,take_id")

    def test_csv_has_the_protocol_columns_and_one_row_per_take(self, passages, tmp_path):
        rows = plan(passages)
        mp.write_plan(tmp_path, rows, passages, "recommended", False)
        with (tmp_path / "plan.csv").open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            written = list(reader)
        assert reader.fieldnames == mp.CSV_COLUMNS
        assert len(written) == len(rows) == 112
        assert (tmp_path / "session_log.csv").read_text(encoding="utf-8").strip() == ",".join(mp.SESSION_LOG_COLUMNS)

    def test_cli_exit_codes_and_messages(self, tmp_path, capsys):
        out = tmp_path / "plan"
        assert mp.main(["--dev", "1", "--test", "0", "--tier", "pilot", "--passages", str(PASSAGES_FILE), "--out", str(out)]) == 0
        printed = capsys.readouterr().out
        assert "9 takes" in printed and "prompter_spk_dev_01.html" in printed
        assert mp.main(["--dev", "1", "--test", "0", "--tier", "pilot", "--passages", str(PASSAGES_FILE), "--out", str(out)]) == 2
        assert "already exists" in capsys.readouterr().err
        assert mp.main(["--dev", "0", "--test", "1", "--passages", str(PASSAGES_FILE), "--out", str(tmp_path / "x")]) == 2
        assert mp.main(["--dev", "2", "--test", "0", "--tier", "minimum", "--passages", str(PASSAGES_FILE), "--out", str(tmp_path / "y")]) == 0
        assert "no test speakers" in capsys.readouterr().out


class TestPrompter:
    def _data(self, html: str) -> dict:
        match = re.search(r'<script id="plan-data" type="application/json">(.*?)</script>', html, re.S)
        assert match, "plan data block missing"
        return json.loads(match.group(1))

    def test_each_speaker_gets_a_page_with_exactly_their_takes(self, passages, tmp_path):
        rows = plan(passages)
        mp.write_plan(tmp_path, rows, passages, "recommended", False)
        for speaker in ("spk_dev_01", "spk_dev_02", "spk_test_01", "spk_test_02"):
            html = (tmp_path / f"prompter_{speaker}.html").read_text(encoding="utf-8")
            data = self._data(html)
            assert data["speaker_id"] == speaker
            assert [t["take_id"] for t in data["takes"]] == [r["take_id"] for r in by(rows, speaker_id=speaker)]
            assert len(data["checklist"]) == 9 and {p["passage_id"] for p in data["passages"]} == {"p001", "p002"}
            assert f"<title>Recording prompter - {speaker}</title>" in html
            assert "__DATA__" not in html and "__SPEAKER__" not in html

    def test_data_block_cannot_break_out_of_its_script_tag(self, passages, tmp_path):
        mp.write_plan(tmp_path, plan(passages), passages, "recommended", False)
        html = (tmp_path / "prompter_spk_dev_01.html").read_text(encoding="utf-8")
        blob = re.search(r'<script id="plan-data" type="application/json">(.*?)</script>', html, re.S).group(1)
        assert "<" not in blob

    def test_a_hostile_passage_title_cannot_break_the_page(self, passages):
        """The title is free text from the passages file: it must not be able to close the data block and inject script."""
        evil = mp.Passage("p001", "</script><script>alert(1)</script><!--", passages[0].sentences)
        rows = [r for r in plan(passages, 1, 0, "pilot")]
        html = mp.prompter_html("spk_dev_01", rows, [evil], "pilot")
        blob = re.search(r'<script id="plan-data" type="application/json">(.*?)</script>', html, re.S).group(1)
        assert "<" not in blob and html.count("<script") == 2
        assert json.loads(blob)["passages"][0]["title"] == "</script><script>alert(1)</script><!--"

    def test_the_page_carries_the_passage_text_word_for_word(self, passages, tmp_path):
        mp.write_plan(tmp_path, plan(passages, 1, 0, "minimum"), passages, "minimum", False)
        data = self._data((tmp_path / "prompter_spk_dev_01.html").read_text(encoding="utf-8"))
        p001 = json.loads(PASSAGES_FILE.read_text(encoding="utf-8"))[0]["text"]
        assert " ".join(w for s in data["passages"][0]["sentences"] for w in s) == p001


class TestContinueAfterThePilot:
    """make_plan --done: takes that already have a recording are marked accepted so the bigger plan skips them."""

    def _pilot_folder(self, tmp_path, passages) -> Path:
        folder = tmp_path / "pilot_wavs"
        folder.mkdir()
        for row in plan(passages, 1, 0, "pilot"):
            (folder / f"{row['take_id']}.wav").write_bytes(b"x")
        (folder / "notes.txt").write_text("not audio", encoding="utf-8")
        (folder / "rec_p009_spk_dev_09_base_01.wav").write_bytes(b"x")   # matches no take of any plan
        return folder

    def test_recorded_take_ids_come_from_wav_names_in_folders_and_files(self, tmp_path, passages):
        folder = self._pilot_folder(tmp_path, passages)
        ids = mp.recorded_take_ids([folder])
        assert len(ids) == 10 and "notes" not in ids and ids == sorted(ids)
        assert mp.recorded_take_ids([folder / "rec_p009_spk_dev_09_base_01.wav"]) == ["rec_p009_spk_dev_09_base_01"]
        (tmp_path / "UPPER.WAV").write_bytes(b"x")
        assert mp.recorded_take_ids([tmp_path / "UPPER.WAV"]) == ["UPPER"]
        (tmp_path / "empty").mkdir()
        assert mp.recorded_take_ids([tmp_path / "empty"]) == []

    def test_mark_done_marks_only_matching_takes_and_reports_the_rest(self, passages):
        rows = plan(passages, 2, 2, "recommended")
        marked, unmatched = mp.mark_done(rows, ["rec_p001_spk_dev_01_base_01", "rec_p001_spk_dev_01_flaw_fast_02", "rec_p404_spk_dev_01_base_01"])
        assert marked == 2 and unmatched == ["rec_p404_spk_dev_01_base_01"]
        assert {r["take_id"] for r in rows if r["status"] == "accepted"} == {"rec_p001_spk_dev_01_base_01", "rec_p001_spk_dev_01_flaw_fast_02"}
        assert mp.mark_done(rows, []) == (0, [])
        assert mp.mark_done(rows, ["rec_p001_spk_dev_01_base_01"])[0] == 1   # marking twice changes nothing
        assert len(by(rows, status="accepted")) == 2

    def test_the_pilot_covers_exactly_nine_takes_of_the_recommended_plan(self, passages, tmp_path):
        recorded = [r["take_id"] for r in plan(passages, 1, 0, "pilot")]
        rows = plan(passages, 2, 2, "recommended")
        marked, unmatched = mp.mark_done(rows, recorded)
        assert (marked, unmatched) == (9, [])

    def test_cli_marks_the_pilot_in_the_csv_and_in_the_prompter(self, passages, tmp_path, capsys):
        folder = self._pilot_folder(tmp_path, passages)
        out = tmp_path / "plan"
        code = mp.main(["--dev", "2", "--test", "2", "--tier", "recommended", "--passages", str(PASSAGES_FILE), "--out", str(out), "--done", str(folder)])
        assert code == 0
        printed = capsys.readouterr().out
        assert "9 take(s) already recorded are marked accepted." in printed and "rec_p009_spk_dev_09_base_01" in printed
        with (out / "plan.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len([r for r in rows if r["status"] == "accepted"]) == 9 and len(rows) == 112
        data = json.loads(re.search(r'<script id="plan-data" type="application/json">(.*?)</script>',
                                    (out / "prompter_spk_dev_01.html").read_text(encoding="utf-8"), re.S).group(1))
        assert sum(1 for t in data["takes"] if t["status"] == "accepted") == 9
        other = json.loads(re.search(r'<script id="plan-data" type="application/json">(.*?)</script>',
                                     (out / "prompter_spk_test_01.html").read_text(encoding="utf-8"), re.S).group(1))
        assert {t["status"] for t in other["takes"]} == {"todo"}

    def test_without_done_everything_is_todo_and_the_page_data_has_a_status(self, passages, tmp_path):
        mp.write_plan(tmp_path, plan(passages), passages, "recommended", False)
        data = json.loads(re.search(r'<script id="plan-data" type="application/json">(.*?)</script>',
                                    (tmp_path / "prompter_spk_dev_01.html").read_text(encoding="utf-8"), re.S).group(1))
        assert {t["status"] for t in data["takes"]} == {"todo"}

    def test_the_same_recordings_give_byte_identical_plans(self, passages, tmp_path):
        folder = self._pilot_folder(tmp_path, passages)
        for name in ("a", "b"):
            assert mp.main(["--dev", "2", "--test", "2", "--passages", str(PASSAGES_FILE), "--out", str(tmp_path / name), "--done", str(folder)]) == 0
        for file in sorted(p.name for p in (tmp_path / "a").iterdir()):
            assert (tmp_path / "a" / file).read_bytes() == (tmp_path / "b" / file).read_bytes(), file
