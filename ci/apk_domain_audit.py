#!/usr/bin/env python3
"""Static release-APK domain audit using a pinned external .ag corpus.

The external corpus is reference data only. A match is not automatically proof of
malware. For PhilthySports release CI, any embedded .ag hostname is unexpected and
therefore fails the release gate unless it is explicitly reviewed and allowlisted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import BinaryIO

DOMAIN_RE = re.compile(
    rb"(?i)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:[a-z]{2,63})"
)
CHUNK = 1024 * 1024
OVERLAP = 300


def git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def download(url: str, attempts: int = 4) -> bytes:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PhilthySports-APK-Domain-Audit/1"})
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.read()
        except Exception as exc:  # network failure should not silently weaken the gate
            last = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"unable to fetch pinned domain corpus after {attempts} attempts: {type(last).__name__}")


def normalize_domain(raw: bytes) -> str:
    return raw.decode("ascii", errors="ignore").lower().rstrip(".")


def scan_stream(stream: BinaryIO, label: str, found: dict[str, set[str]]) -> None:
    tail = b""
    while True:
        chunk = stream.read(CHUNK)
        if not chunk:
            break
        data = tail + chunk
        for match in DOMAIN_RE.finditer(data):
            host = normalize_domain(match.group(0))
            if host:
                found[host].add(label)
        tail = data[-OVERLAP:]


def corpus_match(host: str, corpus: set[str]) -> str | None:
    current = host
    while "." in current:
        if current in corpus:
            return current
        current = current.split(".", 1)[1]
    return host if host in corpus else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=Path("apk-domain-audit.json"))
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("integrations/domain-intel/johnkavin123-233.json"),
    )
    parser.add_argument("--allow-ag", action="append", default=[], help="Reviewed .ag hostname allowed in this APK")
    parser.add_argument("--fail-on-ag", action="store_true")
    parser.add_argument("--fail-on-corpus-match", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    corpus_bytes = download(manifest["source_url"])
    actual_blob = git_blob_sha1(corpus_bytes)
    expected_blob = manifest["source_git_blob_sha1"]
    if actual_blob != expected_blob:
        raise SystemExit(
            f"pinned domain corpus integrity failure: got {actual_blob}, expected {expected_blob}"
        )

    corpus = {
        line.strip().lower().rstrip(".")
        for line in corpus_bytes.decode("utf-8", errors="strict").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    allow_ag = {x.strip().lower().rstrip(".") for x in args.allow_ag if x.strip()}

    found: dict[str, set[str]] = defaultdict(set)
    scan_errors: list[dict[str, str]] = []
    apk_sha256 = hashlib.sha256(args.apk.read_bytes()).hexdigest()

    with zipfile.ZipFile(args.apk) as zf:
        for info in zf.infolist():
            # Scan entry names too; then scan decompressed contents without loading the
            # entire entry into memory.
            for match in DOMAIN_RE.finditer(info.filename.encode("utf-8", errors="ignore")):
                found[normalize_domain(match.group(0))].add(f"zip-name:{info.filename}")
            if info.is_dir():
                continue
            try:
                with zf.open(info, "r") as stream:
                    scan_stream(stream, info.filename, found)
            except Exception as exc:
                scan_errors.append({"entry": info.filename, "error": type(exc).__name__})

    ag_hosts = sorted(h for h in found if h.endswith(".ag") and h not in allow_ag)
    matches = []
    for host in sorted(found):
        matched = corpus_match(host, corpus)
        if matched and host not in allow_ag:
            matches.append({
                "host": host,
                "corpus_entry": matched,
                "locations": sorted(found[host])[:20],
            })

    report = {
        "schema_version": 1,
        "apk": str(args.apk),
        "apk_sha256": apk_sha256,
        "source": {
            "repository": manifest["source_repository"],
            "path": manifest["source_path"],
            "commit": manifest["source_commit"],
            "git_blob_sha1_expected": expected_blob,
            "git_blob_sha1_verified": actual_blob,
            "entries": len(corpus),
            "trust": manifest.get("trust"),
            "role": manifest.get("role"),
        },
        "domain_literals_found": len(found),
        "ag_hosts": [
            {"host": host, "locations": sorted(found[host])[:20]} for host in ag_hosts
        ],
        "corpus_matches": matches,
        "allowlisted_ag_hosts": sorted(allow_ag),
        "scan_errors": scan_errors,
    }

    failures = []
    if args.fail_on_ag and ag_hosts:
        failures.append(f"unexpected .ag domain literals: {len(ag_hosts)}")
    if args.fail_on_corpus_match and matches:
        failures.append(f"pinned corpus matches: {len(matches)}")
    if scan_errors:
        failures.append(f"APK entries not scanned successfully: {len(scan_errors)}")

    report["passed"] = not failures
    report["failures"] = failures
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
