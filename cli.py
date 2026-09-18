from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from anime_watcher.organizer import organize_files, scan_video_files


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely organize anime episodes into a local library")
    parser.add_argument("sources", nargs="+", help="Files or folders to import")
    parser.add_argument("--library", required=True, help="Destination library root (required)")
    parser.add_argument("--execute", action="store_true", help="Perform moves (default is a dry run)")
    parser.add_argument("--json", action="store_true", help="Print machine-readable results")
    args = parser.parse_args()
    paths = []
    for source_value in args.sources:
        source = Path(source_value)
        paths.extend(scan_video_files(source) if source.is_dir() else [source])
    results = organize_files(paths, args.library, dry_run=not args.execute)
    if args.json:
        print(json.dumps([{"source": str(r.source), "destination": str(r.destination) if r.destination else None,
                           "status": r.status, "message": r.message} for r in results], indent=2))
    else:
        for result in results:
            print(f"{result.status.upper():10} {result.source} -> {result.destination or '-'}")
        counts = {status: sum(r.status == status for r in results) for status in {r.status for r in results}}
        print("\n" + ", ".join(f"{key}: {value}" for key, value in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
