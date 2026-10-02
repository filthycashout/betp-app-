from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import requests


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def github_oidc_token(audience: str) -> str:
    request_url = os.getenv("ACTIONS_ID_TOKEN_REQUEST_URL", "").strip()
    request_token = os.getenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "").strip()
    if not request_url or not request_token:
        raise RuntimeError("GitHub Actions OIDC environment is required")
    separator = "&" if "?" in request_url else "?"
    response = requests.get(
        f"{request_url}{separator}audience={audience}",
        headers={"Authorization": f"bearer {request_token}"},
        timeout=20,
    )
    response.raise_for_status()
    token = response.json().get("value")
    if not token:
        raise RuntimeError("GitHub OIDC token response did not contain value")
    return str(token)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sign a strict PhilthySports promotion artifact")
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument(
        "--signer-url",
        default="https://philthysports-powerhouse-v8.onrender.com/v1/ci/sign-model-artifact",
    )
    args = parser.parse_args()

    artifact = json.loads(args.artifact.read_text())
    if artifact.get("status") != "PROMOTION_ELIGIBLE_UNSIGNED":
        raise SystemExit("Artifact is not strict-promotion eligible")

    checks = (
        artifact.get("promotion_evidence", {})
        .get("strict_policy", {})
        .get("checks", {})
    )
    if not checks or not all(bool(value) for value in checks.values()):
        raise SystemExit("Strict promotion checks are not all PASS")

    artifact["status"] = "PROMOTED_TRAINED_MODEL"
    artifact.pop("signature", None)
    artifact["artifact_sha256"] = _sha256(
        _canonical({k: v for k, v in artifact.items() if k != "artifact_sha256"})
    )

    token = github_oidc_token("philthysports-ci")
    response = requests.post(
        args.signer_url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        data=_canonical(artifact),
        timeout=30,
    )
    response.raise_for_status()
    signed = response.json()
    local_core_sha = _sha256(_canonical(artifact))
    if signed.get("sha256") != local_core_sha:
        raise SystemExit("Signer checksum does not match local artifact")
    if not signed.get("signature_b64") or not signed.get("public_key_b64") or not signed.get("key_id"):
        raise SystemExit("Signer response is incomplete")

    artifact["signature"] = {
        "algorithm": "Ed25519",
        "key_id": signed["key_id"],
        "public_key_b64": signed["public_key_b64"],
        "signature_b64": signed["signature_b64"],
        "signed_core_sha256": signed["sha256"],
        "canonicalization": signed.get("canonicalization"),
    }
    args.artifact.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "artifact": str(args.artifact),
                "status": artifact["status"],
                "key_id": signed["key_id"],
                "signed_core_sha256": signed["sha256"],
                "file_sha256": _sha256(args.artifact.read_bytes()),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
