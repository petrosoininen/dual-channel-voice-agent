"""Start the local backend in an explicit browser-reference mode."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--agent-provider",
        choices=("deterministic", "foundry"),
        default="foundry",
    )
    parser.add_argument(
        "--voice-provider",
        choices=("off", "azure-voice-live"),
        default="azure-voice-live",
    )
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--port", type=int, choices=range(1024, 65536), default=8100)
    args = parser.parse_args()

    if args.env_file.is_file():
        load_dotenv(args.env_file, override=True)
    os.environ["AGENT_PROVIDER"] = args.agent_provider
    os.environ["VOICE_PROVIDER"] = args.voice_provider

    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
