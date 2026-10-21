"""CLI: python -m sports_ai.crawling.cli --config spider.json --output data.jsonl."""
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from .engine import SpiderRunner, USER_AGENT
from .spec import SpiderSpec


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a configurable, policy-aware HTML spider")
    parser.add_argument("--config", required=True, type=Path, help="JSON spider definition")
    parser.add_argument("--output", required=True, type=Path, help="Output path")
    parser.add_argument("--format", choices=("jsonl", "json", "csv"), default="jsonl")
    parser.add_argument("--user-agent", default=USER_AGENT, help="Identify your spider to site operators")
    args = parser.parse_args()
    spec = SpiderSpec.from_dict(json.loads(args.config.read_text(encoding="utf-8")))
    stats = asyncio.run(SpiderRunner(spec, user_agent=args.user_agent).run(args.output, args.format))
    print(json.dumps({"output": str(args.output), **asdict(stats)}, indent=2))


if __name__ == "__main__":
    main()
