"""Print only sanitized read-only Foundry compatibility diagnostics."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from backend.foundry_preflight import run_foundry_preflight

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """Run safe project/identity diagnostics and print no configured values."""

    load_dotenv(ROOT / ".env", override=True)
    result = asyncio.run(run_foundry_preflight(os.environ))
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
