#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "integrations" / "upstreams.lock.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

def fail(msg: str) -> None:
    raise SystemExit(f"ERROR: {msg}")

def main() -> int:
    data = json.loads(LOCK.read_text(encoding="utf-8"))
    if data.get("schema") != "philthyparleys.upstreams.v2":
        fail("unexpected lock schema")

    repos = data.get("repositories")
    if not isinstance(repos, list) or not repos:
        fail("repositories must be a non-empty list")

    names: set[str] = set()
    repositories: set[str] = set()
    sports_indexes: list[int] = []

    for item in repos:
        if not isinstance(item, dict):
            fail("every repository entry must be an object")
        name = item.get("name")
        repository = item.get("repository")
        url = item.get("url")
        commit = item.get("commit")
        group = item.get("clone_group")

        if not isinstance(name, str) or not NAME.fullmatch(name):
            fail(f"invalid clone name: {name!r}")
        if name in names:
            fail(f"duplicate clone name: {name}")
        names.add(name)

        if not isinstance(repository, str) or repository.count("/") != 1:
            fail(f"invalid repository slug for {name}: {repository!r}")
        if repository in repositories:
            fail(f"duplicate repository slug: {repository}")
        repositories.add(repository)

        expected_url = f"https://github.com/{repository}.git"
        if url != expected_url:
            fail(f"{name}: url must exactly match {expected_url}")

        if not isinstance(commit, str) or not SHA40.fullmatch(commit):
            fail(f"{name}: commit must be a 40-character lowercase SHA")

        if group not in {"sports", "analysis"}:
            fail(f"{name}: unsupported clone_group {group!r}")

        if item.get("artifact_execution") != "disabled":
            fail(f"{name}: external clone execution must remain disabled")
        if item.get("production_authority") is not False:
            fail(f"{name}: external clones cannot be production authority")

        if group == "sports":
            index = item.get("source_index")
            if not isinstance(index, int):
                fail(f"{name}: sports clones require integer source_index")
            sports_indexes.append(index)

    expected = list(range(3, 28))
    if sorted(sports_indexes) != expected:
        fail(f"sports source_index set must be exactly {expected}; got {sorted(sports_indexes)}")

    print(f"validated {len(repos)} locked repositories; sports indexes 3-27 complete")
    return 0

if __name__ == "__main__":
    sys.exit(main())
