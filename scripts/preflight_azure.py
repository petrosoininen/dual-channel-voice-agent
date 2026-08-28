"""Print sanitized local keyless preflight status."""

from __future__ import annotations

import json
import os

from backend.azure_preflight import run_azure_preflight


def main() -> None:
    """Run preflight and print only its safe result contract."""

    result = run_azure_preflight(os.environ)
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
