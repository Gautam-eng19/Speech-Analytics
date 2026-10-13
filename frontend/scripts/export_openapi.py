"""Write the API's OpenAPI document to frontend/openapi.json (the source of the dashboard's TypeScript types).

Usage (from the repository root):
    python scripts/export_openapi.py            # rewrite frontend/openapi.json
    python scripts/export_openapi.py --check    # exit 1 if the committed file is out of date

The frontend never hand-writes API types: `npm run gen:types` (in frontend/) turns this file into src/api/schema.d.ts.
A backend test fails when the committed snapshot no longer matches the running API, so the two cannot drift apart silently.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.main import create_app  # noqa: E402

SNAPSHOT = ROOT / "frontend" / "openapi.json"


def current_document() -> str:
    # A fresh app without the dashboard mounted, so the document never depends on whether frontend/dist exists.
    schema = create_app(frontend_dist=ROOT / "__no_dashboard__").openapi()
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only verify that the committed snapshot is current")
    args = parser.parse_args()
    document = current_document()
    if args.check:
        if not SNAPSHOT.is_file() or SNAPSHOT.read_text(encoding="utf-8") != document:
            print(f"{SNAPSHOT} is out of date; run: python scripts/export_openapi.py", file=sys.stderr)
            return 1
        print("openapi snapshot is current")
        return 0
    SNAPSHOT.write_text(document, encoding="utf-8")
    print(f"wrote {SNAPSHOT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
