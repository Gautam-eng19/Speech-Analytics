"""Check that this computer can run the VAANI project (TASK-126).

    python scripts/check_environment.py                    # what is installed, in plain words
    python scripts/check_environment.py --download-models  # also fetch the speech models once (large downloads)

It changes nothing except, with --download-models, the model cache of the libraries (their own cache folders). It needs only Python itself to
start, so it works before anything is installed: every package is tried with a real import, and a failure is reported with the line to fix
it. Output is plain ASCII so that any console can show it.

Exit code: 0 when everything required is in place (and, with --download-models, the models are downloaded), 1 otherwise.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata as metadata
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
PYTHON_RANGE = ((3, 10), (3, 13))            # whisperx supports 3.10 to 3.13
NODE_MINIMUM = (20, 19)                      # frontend/package.json "engines"

#: (module to import, name on pip, what the project uses it for)
PACKAGES: Sequence[Tuple[str, str, str]] = (
    ("numpy", "numpy", "numbers"),
    ("scipy", "scipy", "reading WAV files"),
    ("av", "av", "decoding audio"),
    ("librosa", "librosa", "pitch and loudness measurements"),
    ("pydantic", "pydantic", "the data contracts"),
    ("fastapi", "fastapi", "the web service"),
    ("uvicorn", "uvicorn", "starting the web service"),
    ("multipart", "python-multipart", "receiving uploaded recordings"),
    ("dotenv", "python-dotenv", "settings"),
    ("torch", "torch", "the speech models"),
    ("torchaudio", "torchaudio", "the word-alignment model"),
    ("whisper", "openai-whisper", "speech recognition"),
    ("whisperx.alignment", "whisperx", "word alignment; it also needs pandas, transformers and nltk"),
)

problems: List[str] = []


def say(status: str, text: str, fix: Optional[str] = None) -> None:
    print(f"  [{status:<7}] {text}")
    if fix:
        print(f"             -> {fix}")


def ok(text: str) -> None:
    say("OK", text)


def problem(text: str, fix: str) -> None:
    problems.append(text)
    say("PROBLEM", text, fix)


def note(text: str) -> None:
    say("note", text)


def version_of(pip_name: str) -> str:
    try:
        return metadata.version(pip_name)
    except metadata.PackageNotFoundError:
        return "version unknown"


def check_python() -> None:
    version = sys.version_info[:2]
    text = f"Python {platform.python_version()}"
    if version < PYTHON_RANGE[0]:
        problem(f"{text} is too old", f"install Python {PYTHON_RANGE[0][0]}.{PYTHON_RANGE[0][1]} to {PYTHON_RANGE[1][0]}.{PYTHON_RANGE[1][1]} from python.org")
    elif version > PYTHON_RANGE[1]:
        problem(f"{text} is newer than the speech libraries support", f"install Python {PYTHON_RANGE[1][0]}.{PYTHON_RANGE[1][1]} from python.org and use it for this project")
    else:
        ok(text)
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        note(f"working inside the virtual environment {sys.prefix}")
    else:
        note("not in a virtual environment (fine, but a virtual environment keeps this project's packages separate)")


def check_packages() -> None:
    for module, pip_name, purpose in PACKAGES:
        try:
            importlib.import_module(module)
        except ModuleNotFoundError as exc:
            missing = exc.name or module
            if missing.split(".")[0] == module.split(".")[0]:
                problem(f"{pip_name} is not installed ({purpose})", "python -m pip install -r requirements.txt")
            else:
                problem(f"{pip_name} needs '{missing}', which is not installed ({purpose})", f"python -m pip install {missing.split('.')[0]}  (or run: python -m pip install -r requirements.txt)")
        except Exception as exc:  # a broken install fails in many ways (DLL load errors, version clashes)
            if ".dll" in str(exc).lower() or "winerror" in str(exc).lower():
                fix = ("on Windows this usually means the 'Microsoft Visual C++ Redistributable' is missing: search for 'vc_redist x64' on "
                       "microsoft.com, install it, then run this script again")
            else:
                fix = "python -m pip install --force-reinstall -r requirements.txt  (if it keeps failing, send this message to the team)"
            problem(f"{pip_name} is installed but cannot be used ({type(exc).__name__}: {str(exc)[:160]})", fix)
        else:
            ok(f"{pip_name} {version_of(pip_name)} ({purpose})")


def check_project() -> None:
    sys.path.insert(0, str(ROOT / "backend"))
    try:
        importlib.import_module("app.main")
    except Exception as exc:
        problem(f"the project's own code cannot start ({type(exc).__name__}: {str(exc)[:160]})", "run this script from the project folder after installing the packages")
    else:
        ok("the project's web service loads (backend/app/main.py)")


def check_node() -> None:
    node = shutil.which("node")
    if node is None:
        note("Node.js was not found. It is only needed to build the dashboard (not for recordings). Tell the team, there is a ready-made dashboard.")
        return
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
        found = tuple(int(x) for x in re.match(r"v(\d+)\.(\d+)", out).groups())  # type: ignore[union-attr]
    except (OSError, subprocess.SubprocessError, AttributeError, ValueError):
        note("Node.js was found but its version could not be read.")
        return
    if found >= NODE_MINIMUM:
        ok(f"Node.js {out} (builds the dashboard)")
    else:
        problem(f"Node.js {out} is too old to build the dashboard", f"install Node.js {NODE_MINIMUM[0]}.{NODE_MINIMUM[1]} or newer (the LTS version) from nodejs.org")


def check_project_state() -> None:
    dist = ROOT / "frontend" / "dist" / "index.html"
    note("the dashboard is built (frontend/dist)" if dist.is_file() else "the dashboard is not built yet (cd frontend, npm ci, npm run build)")
    stats = sorted((ROOT / "data" / "processed" / "baseline_stats").glob("*.json")) if (ROOT / "data" / "processed" / "baseline_stats").is_dir() else []
    note(f"{len(stats)} baseline(s) installed: {', '.join(p.stem for p in stats)}" if stats else "no baseline is installed yet (python scripts/dataset/prepare_recordings.py data/incoming --build-baseline)")


def timed(label: str, action: Callable[[], object], hint: str) -> bool:
    print(f"  ... {label} (the first time this downloads a large file and can take several minutes)")
    started = time.time()
    try:
        action()
    except Exception as exc:
        problem(f"{label} failed ({type(exc).__name__}: {str(exc)[:200]})", hint)
        return False
    ok(f"{label} ready ({time.time() - started:.0f} s)")
    return True


def download_models(skip_whisper: bool) -> None:
    sys.path.insert(0, str(ROOT / "backend"))
    internet = "check the internet connection (and any VPN or proxy), then run this again; a partial download is continued or repeated"

    def punkt() -> None:
        import nltk  # type: ignore[import]

        try:
            nltk.data.find("tokenizers/punkt_tab/english")
        except LookupError:
            if not nltk.download("punkt_tab", quiet=True):
                raise RuntimeError("the sentence-splitting data could not be downloaded")
        # load it the way WhisperX does, so a mismatch between the library and the data shows up here and not in the middle of a run
        splitter = nltk.data.load("tokenizers/punkt_tab/english.pickle")
        if len(list(splitter.span_tokenize("Hello there. How are you?"))) != 2:
            raise RuntimeError("the sentence splitter did not split a test sentence pair")

    def alignment() -> None:
        from app.services.alignment import get_aligner

        get_aligner().load_model()

    def recognition() -> None:
        from app.services.transcription import get_transcriber

        get_transcriber().load_model()

    timed("sentence data for word alignment (nltk punkt_tab)", punkt, internet)
    timed("word-alignment model (wav2vec2, about 360 MB)", alignment, internet)
    if skip_whisper:
        note("speech recognition model skipped (--skip-whisper): paste the passage text as the transcript on the site instead")
    else:
        timed("speech-recognition model (Whisper, about 140 MB)", recognition, internet)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check that this computer can run the VAANI project.")
    parser.add_argument("--download-models", action="store_true", help="also download the speech models once (large, needs internet)")
    parser.add_argument("--skip-whisper", action="store_true", help="with --download-models: skip the speech-recognition model")
    args = parser.parse_args(argv)

    print("Checking this computer for the VAANI project\n")
    print("Python")
    check_python()
    print("\nPackages")
    check_packages()
    print("\nProject")
    check_project()
    check_node()
    check_project_state()
    if args.download_models:
        if problems:
            print("\nModels: not downloaded yet, because the problems above come first.")
        else:
            print("\nModels")
            download_models(args.skip_whisper)
    print()
    if problems:
        print(f"{len(problems)} problem(s). Fix them from the top; the first line under each [PROBLEM] says how. Then run this script again.")
        return 1
    print("Everything required is in place." + ("" if args.download_models else "  Next:  python scripts/check_environment.py --download-models"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
