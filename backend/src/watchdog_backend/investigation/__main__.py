"""Showcase runs: export them from one database, import them into another.

uv run python -m watchdog_backend.investigation showcase-export [--file PATH]
uv run python -m watchdog_backend.investigation showcase-import [--file PATH] [--force]

Default file: showcase/showcase_runs.json at the repository root (committed, so a deployment
gets the runs with the code). See investigation/showcase.py for the safeguards.
"""

import argparse
import sys
from pathlib import Path

from watchdog_backend.db import get_engine
from watchdog_backend.investigation.showcase import (
    DEFAULT_FILE,
    ShowcaseError,
    read_import,
    write_export,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    exp = sub.add_parser("showcase-export", help="write every showcase run to a JSON file")
    exp.add_argument("--file", type=Path, default=DEFAULT_FILE)
    imp = sub.add_parser("showcase-import", help="load showcase runs from a JSON file")
    imp.add_argument("--file", type=Path, default=DEFAULT_FILE)
    imp.add_argument(
        "--force", action="store_true", help="import even if this database's data differs"
    )
    args = parser.parse_args()

    if args.cmd == "showcase-export":
        with get_engine().connect() as conn:
            counts = write_export(conn, args.file)
        size = args.file.stat().st_size / 1024
        print(f"exported {counts or 'no showcase runs'} to {args.file} ({size:,.0f} KB)")
        return
    if not args.file.is_file():
        sys.exit(f"no file at {args.file} (run showcase-export first)")
    try:
        with get_engine().begin() as conn:
            counts = read_import(conn, args.file, force=args.force)
    except ShowcaseError as exc:
        sys.exit(f"nothing imported: {exc}")
    print(f"imported {counts} from {args.file}")


if __name__ == "__main__":
    main()
