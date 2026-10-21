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

from zero_trust_control_plane import (
    ANDROID_SIGNING_ACTION,
    GITHUB_AUDIENCE,
    GITHUB_ISSUER,
    MODEL_SIGNING_ACTION,
    TRUSTED_REF,
    TRUSTED_REPOSITORY,
    ActionCandidate,
    ControlPlaneDenied,
    control_plane,
    trusted_workflows,
)

GITHUB_JWKS = f"{GITHUB_ISSUER}/.well-known/jwks"
TRUSTED_WORKFLOWS = trusted_workflows()
P256_ORDER = int(
    "FFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551", 16
)
ANDROID_KEY_CONTEXT = b"philthysports-android-release-v1"
ANDROID_PUBLIC_SPKI_SHA256_PIN = "0b1a418efeef35fdbbb77dfc129aabae2fc43141e3893dc21fd03cac8fa9f469"
DEFAULT_ANDROID_SIGNING_FALLBACK = ""
MAX_MODEL_ARTIFACT_BYTES = 2 * 1024 * 1024
SUPPORTED_MODEL_SPORTS = frozenset({"NFL", "NBA", "MLB", "NHL"})

_SIGNING_BEARER_TOKEN: ContextVar[str | None] = ContextVar(
    "philthy_signing_bearer_token", default=None
)
_VERIFIED_OIDC_CLAIMS: ContextVar[dict[str, Any] | None] = ContextVar(
    "philthy_verified_oidc_claims", default=None
)
_TOKEN_FINGERPRINT_SHA256: ContextVar[str | None] = ContextVar(
    "philthy_token_fingerprint_sha256", default=None
)
_SIGNING_FALLBACK_PAYLOAD: ContextVar[dict[str, Any] | None] = ContextVar(
    "philthy_signing_fallback_payload", default=None
)
_CONTROL_PLANE_AUDIT: ContextVar[dict[str, Any] | None] = ContextVar(
    "philthy_control_plane_audit", default=None
)


@lru_cache(maxsize=1)
def _jwk_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(GITHUB_JWKS, cache_keys=True)


def verify_github_oidc(authorization: str | None) -> dict[str, Any]:
    """Cryptographically authenticate the GitHub Actions caller.

    Authentication is deliberately separate from action authorization. Passing
    this function proves only an authenticated identity from an allowed repo/ref
    and known workflow. Exact action/resource authorization happens later in the
    deterministic zero-trust control plane immediately before privileged use.
    """

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

    # Keep verified identity context request-local. No prose, prompt text,
    # document content, connector output, or model output can write these values.
    _SIGNING_BEARER_TOKEN.set(token)
    _VERIFIED_OIDC_CLAIMS.set(dict(claims))
    _TOKEN_FINGERPRINT_SHA256.set(hashlib.sha256(token.encode("utf-8")).hexdigest())
    _SIGNING_FALLBACK_PAYLOAD.set(None)
    _CONTROL_PLANE_AUDIT.set(None)
    return claims


def _authorize_privileged_action(
    *,
    action: str,
    method: str,
    resource_id: str,
    destination: str,
    resource_sha256: str | None = None,
) -> dict[str, Any]:
    claims = _VERIFIED_OIDC_CLAIMS.get()
    token_fingerprint = _TOKEN_FINGERPRINT_SHA256.get()
    if claims is None or not token_fingerprint:
        raise PermissionError("verified GitHub OIDC context is required before authorization")

    candidate = ActionCandidate(
        source="authenticated_fastapi_ci_route",
        action=action,
        method=method,
        resource_id=resource_id,
        destination=destination,
        resource_sha256=resource_sha256,
    )
    plane = control_plane()
    permit = plane.authorize(
        candidate,
        claims,
        token_fingerprint_sha256=token_fingerprint,
    )
    # Consume immediately at the privileged function boundary. A permit cannot
    # be reused for another action/resource or replayed later in the process.
    plane.consume(
        permit,
        action=action,
        resource_id=resource_id,
        destination=destination,
        resource_sha256=resource_sha256,
    )
    audit = plane.authorized_audit(permit)
    _CONTROL_PLANE_AUDIT.set(audit)
    return audit


def control_plane_audit_snapshot() -> dict[str, Any] | None:
    audit = _CONTROL_PLANE_AUDIT.get()
    return dict(audit) if audit is not None else None


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


def _canonical_artifact(artifact: dict[str, Any]) -> bytes:
    canonical = json.dumps(
        artifact, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    if len(canonical) > MAX_MODEL_ARTIFACT_BYTES:
        raise ValueError("artifact exceeds maximum signing size")
    return canonical


def _validate_promoted_artifact_for_signing(artifact: dict[str, Any]) -> None:
    if artifact.get("status") != "PROMOTED_TRAINED_MODEL":
        raise ValueError("only PROMOTED_TRAINED_MODEL artifacts may be signed")
    sport = str(artifact.get("sport") or "").upper()
    if sport not in SUPPORTED_MODEL_SPORTS:
        raise ValueError("artifact sport is missing or unsupported")
    if not str(artifact.get("model_id") or "").strip():
        raise ValueError("artifact model_id is required")
    if artifact.get("trained_weights") is not True:
        raise ValueError("artifact does not declare trained weights")

    claimed_artifact_sha = str(artifact.get("artifact_sha256") or "")
    if len(claimed_artifact_sha) != 64:
        raise ValueError("artifact_sha256 is required")
    unsigned_core = {k: v for k, v in artifact.items() if k != "artifact_sha256"}
    expected_artifact_sha = hashlib.sha256(
        json.dumps(
            unsigned_core,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    if claimed_artifact_sha != expected_artifact_sha:
        raise ValueError("artifact_sha256 does not match canonical unsigned core")

    strict_checks = (
        artifact.get("promotion_evidence", {})
        .get("strict_policy", {})
        .get("checks", {})
    )
    if not isinstance(strict_checks, dict) or not strict_checks:
        raise ValueError("strict promotion checks are required")
    if not all(value is True for value in strict_checks.values()):
        raise ValueError("strict promotion checks are not all PASS")


def sign_model_artifact(artifact: dict[str, Any]) -> dict[str, str]:
    if not isinstance(artifact, dict):
        raise ValueError("artifact must be a JSON object")
    _validate_promoted_artifact_for_signing(artifact)
    canonical = _canonical_artifact(artifact)
    digest = hashlib.sha256(canonical).hexdigest()
    _authorize_privileged_action(
        action=MODEL_SIGNING_ACTION,
        method="POST",
        resource_id=f"model-artifact:{digest}",
        destination="immutable-model-registry",
        resource_sha256=digest,
    )
    private = ed25519.Ed25519PrivateKey.from_private_bytes(_root_seed())
    signature = private.sign(canonical)
    return {
        "sha256": digest,
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

    audit = _CONTROL_PLANE_AUDIT.get()
    if not audit or audit.get("classification") != "AUTHORIZED_FOR_EXACT_ACTION":
        raise RuntimeError("control-plane authorization is required before signing fallback")
    permit = audit.get("permit") or {}
    if permit.get("action") != ANDROID_SIGNING_ACTION:
        raise RuntimeError("control-plane permit is not bound to Android signing material")

    token = _SIGNING_BEARER_TOKEN.get()
    if not token:
        raise RuntimeError("validated GitHub OIDC token unavailable for signing fallback")

    fallback_base = os.getenv(
        "PHILTHY_SIGNING_FALLBACK_URL", DEFAULT_ANDROID_SIGNING_FALLBACK
    ).strip().rstrip("/")
    if not fallback_base:
        raise RuntimeError(
            "Android signing fallback is disabled; configure PHILTHY_SIGNING_FALLBACK_URL explicitly or provide MODEL_SIGNING_PRIVATE_KEY_B64"
        )
    if not fallback_base.startswith("https://"):
        raise RuntimeError("Android signing fallback URL must use HTTPS")

    current_host = (
        os.getenv("PHILTHY_PUBLIC_HOST", "").strip()
        or os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
        or os.getenv("PHILTHY_RUNTIME_HOSTNAME", "").strip()
    ).lower()
    fallback_host = fallback_base.split("://", 1)[-1].split("/", 1)[0].lower()
    if current_host and current_host == fallback_host:
        raise RuntimeError("Android signing seed unavailable on fallback signer")

    request = urllib.request.Request(
        f"{fallback_base}/v1/ci/android-signing-material",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "PhilthySports-signing-failover/2.0",
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
    _authorize_privileged_action(
        action=ANDROID_SIGNING_ACTION,
        method="GET",
        resource_id="android-release-key",
        destination="github-actions-release-runner",
    )
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
        # Never trigger a private-key fetch merely to answer a public-key query.
        cached = _SIGNING_FALLBACK_PAYLOAD.get()
        if cached is None:
            raise RuntimeError("authorized Android signing material must be loaded first")
        return str(cached["public_spki_sha256"])
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
