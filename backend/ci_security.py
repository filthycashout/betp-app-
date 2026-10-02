from __future__ import annotations

import base64
import hashlib
import json
import os
from functools import lru_cache
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

GITHUB_ISSUER = "https://token.actions.githubusercontent.com"
GITHUB_AUDIENCE = "philthysports-ci"
GITHUB_JWKS = f"{GITHUB_ISSUER}/.well-known/jwks"
TRUSTED_REPOSITORY = "filthycashout/betp-app-"
TRUSTED_REF = "refs/heads/main"
TRUSTED_WORKFLOWS = {
    "filthycashout/betp-app-/.github/workflows/build-apk.yml@refs/heads/main",
    "filthycashout/betp-app-/.github/workflows/philthysports-full-ci.yml@refs/heads/main",
    "filthycashout/betp-app-/.github/workflows/v8-train-promote.yml@refs/heads/main",
}
P256_ORDER = int(
    "FFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551", 16
)
ANDROID_KEY_CONTEXT = b"philthysports-android-release-v1"


@lru_cache(maxsize=1)
def _jwk_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(GITHUB_JWKS, cache_keys=True)


def verify_github_oidc(authorization: str | None) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise PermissionError("missing bearer token")
    token = authorization[7:].strip()
    if not token:
        raise PermissionError("empty bearer token")

    signing_key = _jwk_client().get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=GITHUB_AUDIENCE,
        issuer=GITHUB_ISSUER,
        options={"require": ["exp", "iat", "iss", "aud", "repository", "ref"]},
    )
    if claims.get("repository") != TRUSTED_REPOSITORY:
        raise PermissionError("untrusted repository")
    if claims.get("ref") != TRUSTED_REF:
        raise PermissionError("untrusted ref")
    workflow_ref = str(claims.get("workflow_ref") or "")
    if workflow_ref not in TRUSTED_WORKFLOWS:
        raise PermissionError("untrusted workflow")
    return claims


def _root_seed() -> bytes:
    encoded = os.getenv("MODEL_SIGNING_PRIVATE_KEY_B64", "").strip()
    if not encoded:
        raise RuntimeError("MODEL_SIGNING_PRIVATE_KEY_B64 is not configured")
    seed = base64.b64decode(encoded, validate=True)
    if len(seed) != 32:
        raise RuntimeError("MODEL_SIGNING_PRIVATE_KEY_B64 must decode to 32 bytes")
    return seed


def model_public_key_b64() -> str:
    private = ed25519.Ed25519PrivateKey.from_private_bytes(_root_seed())
    public = private.public_key().public_bytes_raw()
    return base64.b64encode(public).decode("ascii")


def model_key_id() -> str:
    public = base64.b64decode(model_public_key_b64())
    return hashlib.sha256(public).hexdigest()[:16]


def sign_model_artifact(artifact: dict[str, Any]) -> dict[str, str]:
    canonical = json.dumps(
        artifact, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    private = ed25519.Ed25519PrivateKey.from_private_bytes(_root_seed())
    signature = private.sign(canonical)
    return {
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "signature_b64": base64.b64encode(signature).decode("ascii"),
        "public_key_b64": model_public_key_b64(),
        "key_id": model_key_id(),
        "canonicalization": "RFC8785_LIKE_SORTED_UTF8_JSON_V1",
    }


def _android_private_key() -> ec.EllipticCurvePrivateKey:
    seed = _root_seed()
    digest = hashlib.sha256(seed + ANDROID_KEY_CONTEXT).digest()
    scalar = (int.from_bytes(digest, "big") % (P256_ORDER - 1)) + 1
    return ec.derive_private_key(scalar, ec.SECP256R1())


def android_private_pkcs8_b64() -> str:
    key = _android_private_key()
    payload = key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return base64.b64encode(payload).decode("ascii")


def android_public_spki_sha256() -> str:
    key = _android_private_key()
    spki = key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(spki).hexdigest()
