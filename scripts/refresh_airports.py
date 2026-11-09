"""Regenerate the vendored airport snapshot.

Usage:
    uv run python scripts/refresh_airports.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flight_search.refresh import refresh_airports  # noqa: E402


def main() -> int:
    stats = refresh_airports()
    print(
        f"Wrote {stats['total']} airports "
        f"({stats['medium_large']} medium/large, {stats['small']} small)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
