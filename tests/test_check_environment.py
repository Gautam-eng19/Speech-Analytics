"""Tests for scripts/check_environment.py: what it reports for a missing package, a broken package, an old Python, Node.js, and the model download.

The real libraries are replaced by fake modules so that every branch can be reached on any machine.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import check_environment as ce  # noqa: E402


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    ce.problems.clear()
    monkeypatch.setattr(ce, "check_project", lambda: ce.ok("project loads"))
    monkeypatch.setattr(ce, "check_project_state", lambda: ce.note("state"))
    monkeypatch.setattr(ce, "check_node", lambda: ce.ok("node"))
    yield
    ce.problems.clear()


def test_everything_in_place_exits_zero_and_points_to_the_model_download(monkeypatch, capsys):
    monkeypatch.setattr(ce, "PACKAGES", (("json", "json-lib", "reading data"),))
    assert ce.main([]) == 0
    out = capsys.readouterr().out
    assert "[OK     ] json-lib" in out and "Everything required is in place." in out and "--download-models" in out
    assert ce.problems == []


def test_a_missing_package_is_a_problem_with_the_install_line(monkeypatch, capsys):
    monkeypatch.setattr(ce, "PACKAGES", (("not_a_real_module_xyz", "not-a-real-package", "nothing"),))
    assert ce.main([]) == 1
    out = capsys.readouterr().out
    assert "[PROBLEM] not-a-real-package is not installed (nothing)" in out and "-> python -m pip install -r requirements.txt" in out
    assert "1 problem(s)" in out


def test_a_package_that_needs_another_missing_one_names_it(monkeypatch, capsys):
    def import_fails(name):
        raise ModuleNotFoundError("No module named 'other_dep'", name="other_dep")

    monkeypatch.setattr(ce.importlib, "import_module", import_fails)
    monkeypatch.setattr(ce, "PACKAGES", (("needs_other", "needs-other", "x"),))
    assert ce.main([]) == 1
    out = capsys.readouterr().out
    assert "needs 'other_dep', which is not installed" in out and "pip install other_dep" in out


def test_a_package_that_is_installed_but_broken_is_reported_with_the_error(monkeypatch, capsys):
    def broken(name):
        raise OSError("[WinError 126] The specified module could not be found: c10.dll")

    monkeypatch.setattr(ce.importlib, "import_module", broken)
    monkeypatch.setattr(ce, "PACKAGES", (("torch", "torch", "the speech models"),))
    assert ce.main([]) == 1
    out = capsys.readouterr().out
    assert "torch is installed but cannot be used (OSError: [WinError 126]" in out and "vc_redist x64" in out


def test_other_import_failures_suggest_a_reinstall(monkeypatch, capsys):
    def clash(name):
        raise ImportError("cannot import name 'x' from 'y' (version clash)")

    monkeypatch.setattr(ce.importlib, "import_module", clash)
    monkeypatch.setattr(ce, "PACKAGES", (("pandas", "pandas", "tables"),))
    assert ce.main([]) == 1
    out = capsys.readouterr().out
    assert "pandas is installed but cannot be used (ImportError: cannot import name 'x'" in out and "--force-reinstall" in out and "vc_redist" not in out


@pytest.mark.parametrize("version,expected", [((3, 9, 7), "too old"), ((3, 14, 0), "newer than the speech libraries support"), ((3, 12, 1), None), ((3, 10, 0), None), ((3, 13, 5), None)])
def test_python_version_range(monkeypatch, capsys, version, expected):
    monkeypatch.setattr(sys, "version_info", version + ("final", 0))
    ce.check_python()
    out = capsys.readouterr().out
    if expected:
        assert expected in out and "[PROBLEM]" in out and len(ce.problems) == 1
    else:
        assert "[OK     ] Python" in out and ce.problems == []


def test_virtual_environment_is_mentioned_either_way(monkeypatch, capsys):
    monkeypatch.setattr(sys, "prefix", "/somewhere/venv")
    monkeypatch.setattr(sys, "base_prefix", "/usr")
    ce.check_python()
    assert "working inside the virtual environment /somewhere/venv" in capsys.readouterr().out
    monkeypatch.setattr(sys, "base_prefix", "/somewhere/venv")
    ce.check_python()
    assert "not in a virtual environment" in capsys.readouterr().out


class FakeRun:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout


def test_node_is_optional_but_must_be_new_enough(monkeypatch, capsys):
    monkeypatch.undo()                                    # use the real check_node, not the fixture's stand-in
    ce.problems.clear()
    monkeypatch.setattr(ce.shutil, "which", lambda name: None)
    ce.check_node()
    out = capsys.readouterr().out
    assert "Node.js was not found" in out and ce.problems == []
    monkeypatch.setattr(ce.shutil, "which", lambda name: "/usr/bin/node")
    for text, good in (("v22.1.0\n", True), ("v20.19.0\n", True), ("v20.18.9\n", False), ("v18.0.0\n", False)):
        ce.problems.clear()
        monkeypatch.setattr(ce.subprocess, "run", lambda *a, _t=text, **k: FakeRun(_t))
        ce.check_node()
        out = capsys.readouterr().out
        assert ("[OK     ] Node.js" in out) is good and (len(ce.problems) == 0) is good, text
    ce.problems.clear()
    monkeypatch.setattr(ce.subprocess, "run", lambda *a, **k: FakeRun("garbage"))
    ce.check_node()
    assert "version could not be read" in capsys.readouterr().out and ce.problems == []
    monkeypatch.setattr(ce.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("node", 20)))
    ce.check_node()
    assert "version could not be read" in capsys.readouterr().out


def test_models_are_not_downloaded_while_problems_remain(monkeypatch, capsys):
    called = []
    monkeypatch.setattr(ce, "PACKAGES", (("not_a_real_module_xyz", "not-a-real-package", "nothing"),))
    monkeypatch.setattr(ce, "download_models", lambda skip: called.append(skip))
    assert ce.main(["--download-models"]) == 1
    assert called == [] and "not downloaded yet, because the problems above come first" in capsys.readouterr().out


def test_models_are_downloaded_when_everything_else_is_fine(monkeypatch, capsys):
    called = []
    monkeypatch.setattr(ce, "PACKAGES", (("json", "json-lib", "reading data"),))
    monkeypatch.setattr(ce, "download_models", lambda skip: called.append(skip))
    assert ce.main(["--download-models", "--skip-whisper"]) == 0
    assert called == [True]
    assert "Next:" not in capsys.readouterr().out


def test_a_failed_model_download_is_a_problem_with_a_hint(capsys):
    def fail():
        raise ConnectionError("connection reset by peer")

    assert ce.timed("the big model", fail, "check the internet") is False
    out = capsys.readouterr().out
    assert "[PROBLEM] the big model failed (ConnectionError: connection reset by peer)" in out and "-> check the internet" in out
    assert ce.timed("the small model", lambda: None, "x") is True
    assert "[OK     ] the small model ready" in capsys.readouterr().out


def test_download_models_runs_each_step_and_skips_recognition_on_request(monkeypatch, capsys):
    steps = []
    monkeypatch.setattr(ce, "timed", lambda label, action, hint: steps.append(label) or True)
    ce.download_models(skip_whisper=False)
    assert len(steps) == 3 and "nltk" in steps[0] and "alignment" in steps[1] and "recognition" in steps[2]
    steps.clear()
    ce.download_models(skip_whisper=True)
    assert len(steps) == 2 and "skipped" in capsys.readouterr().out


def test_the_output_is_plain_ascii(monkeypatch, capsys):
    monkeypatch.setattr(ce, "PACKAGES", (("json", "json-lib", "reading data"), ("not_a_real_module_xyz", "x", "y")))
    ce.main([])
    capsys.readouterr().out.encode("ascii")
