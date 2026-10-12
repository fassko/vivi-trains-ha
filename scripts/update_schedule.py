"""Regenerate the bundled fallback schedule from Vivi's GTFS ZIP.

Usage: python3 scripts/update_schedule.py /path/to/GTFS.zip
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components/vivi_trains"))

from gtfs import build_schedule  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 scripts/update_schedule.py /path/to/GTFS.zip")
    data = build_schedule(Path(sys.argv[1]).read_bytes())
    output = ROOT / "custom_components/vivi_trains/vivi_schedule.json"
    output.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {len(data['stops'])} stations and "
        f"{sum(map(len, data['schedule'].values()))} departures to {output}"
    )


if __name__ == "__main__":
    main()
