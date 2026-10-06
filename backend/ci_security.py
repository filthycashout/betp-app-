from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.request
from contextvars import ContextVar
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
ANDROID_PUBLIC_SPKI_SHA256_PIN = "0b1a418efeef35fdbbb77dfc129aabae2fc43141e3893dc21fd03cac8fa9f469"
DEFAULT_ANDROID_SIGNING_FALLBACK = "https://philthysports-powerhouse-v8.onrender.com"
_SIGNING_BEARER_TOKEN: ContextVar[str | None] = ContextVar(
    "philthy_signing_bearer_token", default=None
)
_SIGNING_FALLBACK_PAYLOAD: ContextVar[dict[str, Any] | None] = ContextVar(
    "philthy_signing_fallback_payload", default=None
)


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

    # Keep the validated token only in this request context. If the primary
    # runtime does not hold the release seed, the Android-only helper below can
    # forward the same trusted OIDC assertion to the dedicated signer service.
    _SIGNING_BEARER_TOKEN.set(token)
    _SIGNING_FALLBACK_PAYLOAD.set(None)
    return claims


def _root_seed() -> bytes:
    encoded = os.getenv("MODEL_SIGNING_PRIVATE_KEY_B64", "").strip()
    if not encoded:
        raise RuntimeError("MODEL_SIGNING_PRIVATE_KEY_B64 is not configured")
    seed = base64.b64decode(encoded, validate=True)
    if len(seed) != 32:
        raise RuntimeError("MODEL_SIGNING_PRIVATE_KEY_B64 must decode to 32 bytes")
    return seed


def _local_root_seed_configured() -> bool:
    return bool(os.getenv("MODEL_SIGNING_PRIVATE_KEY_B64", "").strip())


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


def _android_signing_fallback_payload() -> dict[str, Any]:
    cached = _SIGNING_FALLBACK_PAYLOAD.get()
    if cached is not None:
        return cached

    token = _SIGNING_BEARER_TOKEN.get()
    if not token:
        raise RuntimeError("validated GitHub OIDC token unavailable for signing fallback")

    fallback_base = os.getenv(
        "PHILTHY_SIGNING_FALLBACK_URL", DEFAULT_ANDROID_SIGNING_FALLBACK
    ).strip().rstrip("/")
    if not fallback_base:
        raise RuntimeError("Android signing fallback URL is not configured")

    current_host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip().lower()
    fallback_host = fallback_base.split("://", 1)[-1].split("/", 1)[0].lower()
    if current_host and current_host == fallback_host:
        raise RuntimeError("Android signing seed unavailable on fallback signer")

    request = urllib.request.Request(
        f"{fallback_base}/v1/ci/android-signing-material",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "PhilthySports-signing-failover/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError(f"signing fallback returned HTTP {response.status}")
        payload = json.loads(response.read().decode("utf-8"))

    if payload.get("algorithm") != "EC_P256":
        raise RuntimeError("signing fallback returned unexpected algorithm")
    if payload.get("public_spki_sha256") != ANDROID_PUBLIC_SPKI_SHA256_PIN:
        raise RuntimeError("signing fallback key does not match pinned release identity")

    encoded_private = str(payload.get("private_key_pkcs8_b64") or "")
    if not encoded_private:
        raise RuntimeError("signing fallback omitted private key material")
    private_der = base64.b64decode(encoded_private, validate=True)
    private_key = serialization.load_der_private_key(private_der, password=None)
    if not isinstance(private_key, ec.EllipticCurvePrivateKey):
        raise RuntimeError("signing fallback returned an invalid P-256 private key")
    if getattr(private_key.curve, "name", "") != "secp256r1":
        raise RuntimeError("signing fallback returned an invalid P-256 private key")

    _SIGNING_FALLBACK_PAYLOAD.set(payload)
    return payload


def android_private_pkcs8_b64() -> str:
    if not _local_root_seed_configured():
        return str(_android_signing_fallback_payload()["private_key_pkcs8_b64"])
    key = _android_private_key()
    payload = key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return base64.b64encode(payload).decode("ascii")


def android_public_spki_sha256() -> str:
    if not _local_root_seed_configured():
        return str(_android_signing_fallback_payload()["public_spki_sha256"])
    key = _android_private_key()
    spki = key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(spki).hexdigest()


# app.py imports this module before constructing its FastAPI instance. Register
# the additive /mcp router at construction time while leaving all existing v8
# routes, gates, signing functions and deployment commands unchanged.
def _register_mcp_router_on_fastapi() -> None:
    try:
        from fastapi import FastAPI
        from mcp_server import router as philthy_mcp_router
    except Exception:
        return
    if getattr(FastAPI, "_philthy_mcp_registered", False):
        return
    original_init = FastAPI.__init__

    def governed_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.include_router(philthy_mcp_router)

    FastAPI.__init__ = governed_init
    FastAPI._philthy_mcp_registered = True


_register_mcp_router_on_fastapi()
