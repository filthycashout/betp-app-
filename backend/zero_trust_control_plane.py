from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping

CONTROL_PLANE_VERSION = "1.0.0"
GITHUB_ISSUER = "https://token.actions.githubusercontent.com"
GITHUB_AUDIENCE = "philthysports-ci"
TRUSTED_REPOSITORY = "filthycashout/betp-app-"
TRUSTED_REF = "refs/heads/main"

ANDROID_SIGNING_ACTION = "ANDROID_SIGNING_MATERIAL_EXPORT"
MODEL_SIGNING_ACTION = "MODEL_ARTIFACT_SIGN"

_SHA40 = re.compile(r"^[0-9a-fA-F]{40}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_DIGITS = re.compile(r"^[0-9]+$")


@dataclass(frozen=True)
class ActionPolicy:
    action: str
    method: str
    resource_prefix: str
    destination: str
    workflow_refs: frozenset[str]
    event_names: frozenset[str]
    require_resource_sha256: bool


ACTION_POLICIES: dict[str, ActionPolicy] = {
    ANDROID_SIGNING_ACTION: ActionPolicy(
        action=ANDROID_SIGNING_ACTION,
        method="GET",
        resource_prefix="android-release-key",
        destination="github-actions-release-runner",
        workflow_refs=frozenset(
            {
                "filthycashout/betp-app-/.github/workflows/philthysports-full-ci.yml@refs/heads/main",
            }
        ),
        event_names=frozenset({"workflow_dispatch", "push"}),
        require_resource_sha256=False,
    ),
    MODEL_SIGNING_ACTION: ActionPolicy(
        action=MODEL_SIGNING_ACTION,
        method="POST",
        resource_prefix="model-artifact:",
        destination="immutable-model-registry",
        workflow_refs=frozenset(
            {
                "filthycashout/betp-app-/.github/workflows/v8-train-promote.yml@refs/heads/main",
            }
        ),
        event_names=frozenset({"workflow_dispatch", "push", "schedule"}),
        require_resource_sha256=True,
    ),
}


def trusted_workflows() -> frozenset[str]:
    values: set[str] = set()
    for policy in ACTION_POLICIES.values():
        values.update(policy.workflow_refs)
    return frozenset(values)


@dataclass(frozen=True)
class ActionCandidate:
    source: str
    action: str
    method: str
    resource_id: str
    destination: str
    resource_sha256: str | None = None
    status: str = "CANDIDATE_ONLY"
    authorization: str | None = None
    execution_permit: str | None = None
    executable: bool = False


@dataclass(frozen=True)
class ExecutionPermit:
    permit_id: str
    action: str
    method: str
    resource_id: str
    resource_sha256: str | None
    destination: str
    repository: str
    repository_id: str
    repository_owner_id: str
    workflow_ref: str
    workflow_sha: str
    commit_sha: str
    run_id: str
    run_attempt: str
    actor_id: str
    event_name: str
    issued_at_epoch: int
    expires_at_epoch: int
    binding_sha256: str
    mac_sha256: str

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("mac_sha256", None)
        return value


class ControlPlaneDenied(PermissionError):
    def __init__(self, code: str, message: str, *, audit: dict[str, Any] | None = None) -> None:
        self.code = code
        self.audit = audit or {}
        super().__init__(f"{code}: {message}")


class _ReplayGuard:
    def __init__(self, *, now: Callable[[], float]) -> None:
        self._now = now
        self._lock = threading.RLock()
        self._entries: dict[str, int] = {}

    def reserve(self, key: str, expires_at_epoch: int) -> None:
        now = int(self._now())
        with self._lock:
            expired = [item for item, expiry in self._entries.items() if expiry <= now]
            for item in expired:
                self._entries.pop(item, None)
            if key in self._entries:
                raise ControlPlaneDenied(
                    "REPLAY_DETECTED",
                    "the exact token/action/resource binding was already authorized",
                )
            self._entries[key] = expires_at_epoch


class ZeroTrustControlPlane:
    """Deterministic authorization boundary for privileged CI operations.

    The caller supplies cryptographically verified GitHub OIDC claims. This
    class never treats prompt text, document text, tool prose, model output, or
    self-declared administrative claims as authority. It authorizes only exact
    pre-registered action/resource/destination/workflow bindings.
    """

    def __init__(
        self,
        *,
        secret: bytes | None = None,
        now: Callable[[], float] = time.time,
        permit_ttl_seconds: int = 120,
    ) -> None:
        self._secret = secret or secrets.token_bytes(32)
        self._now = now
        self._permit_ttl_seconds = permit_ttl_seconds
        self._replay = _ReplayGuard(now=now)
        self._consume_lock = threading.RLock()
        self._consumed_permits: set[str] = set()

    @staticmethod
    def _deny(code: str, message: str, candidate: ActionCandidate, claims: Mapping[str, Any]) -> None:
        audit = {
            "control_plane_version": CONTROL_PLANE_VERSION,
            "classification": "CANDIDATE_DENIED_FINAL",
            "candidate_status": candidate.status,
            "action": candidate.action,
            "resource_id": candidate.resource_id,
            "destination": candidate.destination,
            "repository": str(claims.get("repository") or ""),
            "workflow_ref": str(claims.get("workflow_ref") or ""),
            "commit_sha": str(claims.get("sha") or ""),
            "run_id": str(claims.get("run_id") or ""),
            "deny_code": code,
        }
        raise ControlPlaneDenied(code, message, audit=audit)

    @staticmethod
    def _canonical(value: Mapping[str, Any]) -> bytes:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    @staticmethod
    def _claim_text(claims: Mapping[str, Any], name: str) -> str:
        value = claims.get(name)
        return "" if value is None else str(value)

    def authorize(
        self,
        candidate: ActionCandidate,
        claims: Mapping[str, Any],
        *,
        token_fingerprint_sha256: str,
    ) -> ExecutionPermit:
        if candidate.status != "CANDIDATE_ONLY" or candidate.executable:
            self._deny(
                "INVALID_CANDIDATE_STATE",
                "LLM/application candidates may not self-promote into executable state",
                candidate,
                claims,
            )

        policy = ACTION_POLICIES.get(candidate.action)
        if policy is None:
            self._deny("UNKNOWN_ACTION", "action is not present in the deterministic allowlist", candidate, claims)
        assert policy is not None

        if candidate.method != policy.method:
            self._deny("METHOD_SCOPE_MISMATCH", "HTTP method does not match the action policy", candidate, claims)
        if not candidate.resource_id.startswith(policy.resource_prefix):
            self._deny("RESOURCE_SCOPE_MISMATCH", "resource is outside the action policy", candidate, claims)
        if candidate.destination != policy.destination:
            self._deny("DESTINATION_SCOPE_MISMATCH", "destination is outside the action policy", candidate, claims)
        if policy.require_resource_sha256:
            if not candidate.resource_sha256 or not _SHA256.fullmatch(candidate.resource_sha256):
                self._deny("RESOURCE_DIGEST_REQUIRED", "a canonical SHA-256 resource binding is required", candidate, claims)
        elif candidate.resource_sha256 is not None and not _SHA256.fullmatch(candidate.resource_sha256):
            self._deny("INVALID_RESOURCE_DIGEST", "resource digest is malformed", candidate, claims)

        repository = self._claim_text(claims, "repository")
        repository_id = self._claim_text(claims, "repository_id")
        repository_owner_id = self._claim_text(claims, "repository_owner_id")
        ref = self._claim_text(claims, "ref")
        workflow_ref = self._claim_text(claims, "workflow_ref")
        workflow_sha = self._claim_text(claims, "workflow_sha")
        commit_sha = self._claim_text(claims, "sha")
        run_id = self._claim_text(claims, "run_id")
        run_attempt = self._claim_text(claims, "run_attempt")
        actor_id = self._claim_text(claims, "actor_id")
        event_name = self._claim_text(claims, "event_name")
        subject = self._claim_text(claims, "sub")
        issuer = self._claim_text(claims, "iss")
        audience = claims.get("aud")

        if repository != TRUSTED_REPOSITORY:
            self._deny("UNTRUSTED_REPOSITORY", "repository claim does not match", candidate, claims)
        if ref != TRUSTED_REF:
            self._deny("UNTRUSTED_REF", "ref claim does not match", candidate, claims)
        if workflow_ref not in policy.workflow_refs:
            self._deny(
                "WORKFLOW_ACTION_MISMATCH",
                "this workflow is authenticated but is not authorized for this exact action",
                candidate,
                claims,
            )
        if event_name not in policy.event_names:
            self._deny("UNTRUSTED_EVENT", "workflow event is not authorized for this action", candidate, claims)
        if issuer != GITHUB_ISSUER:
            self._deny("ISSUER_MISMATCH", "issuer claim does not match GitHub Actions OIDC", candidate, claims)
        audience_ok = audience == GITHUB_AUDIENCE or (
            isinstance(audience, (list, tuple)) and GITHUB_AUDIENCE in audience
        )
        if not audience_ok:
            self._deny("AUDIENCE_MISMATCH", "audience claim does not match", candidate, claims)
        if not subject:
            self._deny("SUBJECT_REQUIRED", "OIDC subject is required", candidate, claims)

        for name, value in (
            ("repository_id", repository_id),
            ("repository_owner_id", repository_owner_id),
            ("run_id", run_id),
            ("run_attempt", run_attempt),
            ("actor_id", actor_id),
        ):
            if not value or not _DIGITS.fullmatch(value):
                self._deny("IDENTITY_CLAIM_INVALID", f"{name} must be a numeric authoritative claim", candidate, claims)
        for name, value in (("sha", commit_sha), ("workflow_sha", workflow_sha)):
            if not value or not _SHA40.fullmatch(value):
                self._deny("IDENTITY_CLAIM_INVALID", f"{name} must be a 40-hex commit binding", candidate, claims)

        runner_environment = self._claim_text(claims, "runner_environment")
        if runner_environment and runner_environment != "github-hosted":
            self._deny(
                "RUNNER_ENVIRONMENT_DENIED",
                "privileged signing actions require a GitHub-hosted runner when the claim is present",
                candidate,
                claims,
            )
        ref_type = self._claim_text(claims, "ref_type")
        if ref_type and ref_type != "branch":
            self._deny("REF_TYPE_DENIED", "privileged signing actions require a branch ref", candidate, claims)

        if not _SHA256.fullmatch(token_fingerprint_sha256):
            self._deny("TOKEN_FINGERPRINT_INVALID", "verified token fingerprint is required", candidate, claims)

        now = int(self._now())
        try:
            token_exp = int(claims.get("exp"))
        except (TypeError, ValueError):
            self._deny("TOKEN_EXPIRY_INVALID", "verified token expiry is missing", candidate, claims)
        if token_exp <= now:
            self._deny("TOKEN_EXPIRED", "verified token is expired", candidate, claims)

        replay_material = {
            "token_fingerprint_sha256": token_fingerprint_sha256,
            "action": candidate.action,
            "resource_id": candidate.resource_id,
            "resource_sha256": candidate.resource_sha256,
        }
        replay_key = hashlib.sha256(self._canonical(replay_material)).hexdigest()
        self._replay.reserve(replay_key, min(token_exp, now + 600))

        issued_at = now
        expires_at = min(token_exp, now + self._permit_ttl_seconds)
        permit_id = secrets.token_hex(16)
        binding = {
            "permit_id": permit_id,
            "action": candidate.action,
            "method": candidate.method,
            "resource_id": candidate.resource_id,
            "resource_sha256": candidate.resource_sha256,
            "destination": candidate.destination,
            "repository": repository,
            "repository_id": repository_id,
            "repository_owner_id": repository_owner_id,
            "workflow_ref": workflow_ref,
            "workflow_sha": workflow_sha,
            "commit_sha": commit_sha,
            "run_id": run_id,
            "run_attempt": run_attempt,
            "actor_id": actor_id,
            "event_name": event_name,
            "issued_at_epoch": issued_at,
            "expires_at_epoch": expires_at,
        }
        binding_sha = hashlib.sha256(self._canonical(binding)).hexdigest()
        mac = hmac.new(self._secret, self._canonical({**binding, "binding_sha256": binding_sha}), hashlib.sha256).hexdigest()
        return ExecutionPermit(
            permit_id=permit_id,
            action=candidate.action,
            method=candidate.method,
            resource_id=candidate.resource_id,
            resource_sha256=candidate.resource_sha256,
            destination=candidate.destination,
            repository=repository,
            repository_id=repository_id,
            repository_owner_id=repository_owner_id,
            workflow_ref=workflow_ref,
            workflow_sha=workflow_sha,
            commit_sha=commit_sha,
            run_id=run_id,
            run_attempt=run_attempt,
            actor_id=actor_id,
            event_name=event_name,
            issued_at_epoch=issued_at,
            expires_at_epoch=expires_at,
            binding_sha256=binding_sha,
            mac_sha256=mac,
        )

    def consume(
        self,
        permit: ExecutionPermit,
        *,
        action: str,
        resource_id: str,
        destination: str,
        resource_sha256: str | None,
    ) -> None:
        now = int(self._now())
        if permit.expires_at_epoch <= now:
            raise ControlPlaneDenied("PERMIT_EXPIRED", "execution permit expired before privileged use")
        if (
            permit.action != action
            or permit.resource_id != resource_id
            or permit.destination != destination
            or permit.resource_sha256 != resource_sha256
        ):
            raise ControlPlaneDenied(
                "PERMIT_BINDING_MISMATCH",
                "execution permit does not match the exact action/resource/destination binding",
            )

        binding = {
            "permit_id": permit.permit_id,
            "action": permit.action,
            "method": permit.method,
            "resource_id": permit.resource_id,
            "resource_sha256": permit.resource_sha256,
            "destination": permit.destination,
            "repository": permit.repository,
            "repository_id": permit.repository_id,
            "repository_owner_id": permit.repository_owner_id,
            "workflow_ref": permit.workflow_ref,
            "workflow_sha": permit.workflow_sha,
            "commit_sha": permit.commit_sha,
            "run_id": permit.run_id,
            "run_attempt": permit.run_attempt,
            "actor_id": permit.actor_id,
            "event_name": permit.event_name,
            "issued_at_epoch": permit.issued_at_epoch,
            "expires_at_epoch": permit.expires_at_epoch,
        }
        expected_binding = hashlib.sha256(self._canonical(binding)).hexdigest()
        if not hmac.compare_digest(expected_binding, permit.binding_sha256):
            raise ControlPlaneDenied("PERMIT_INTEGRITY_FAILURE", "execution permit binding hash is invalid")
        expected_mac = hmac.new(
            self._secret,
            self._canonical({**binding, "binding_sha256": permit.binding_sha256}),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_mac, permit.mac_sha256):
            raise ControlPlaneDenied("PERMIT_INTEGRITY_FAILURE", "execution permit MAC is invalid")

        with self._consume_lock:
            if permit.permit_id in self._consumed_permits:
                raise ControlPlaneDenied("PERMIT_ALREADY_CONSUMED", "execution permit is single-use")
            self._consumed_permits.add(permit.permit_id)

    @staticmethod
    def authorized_audit(permit: ExecutionPermit) -> dict[str, Any]:
        return {
            "control_plane_version": CONTROL_PLANE_VERSION,
            "classification": "AUTHORIZED_FOR_EXACT_ACTION",
            "candidate_status": "CANDIDATE_ONLY",
            "authorization": "VERIFIED",
            "execution": "PERMIT_CONSUMED",
            "permit": permit.public_dict(),
            "invariants": [
                "LLM_COMPROMISE != CONTROL_PLANE_COMPROMISE",
                "MODEL_OUTPUT != AUTHORIZATION",
                "AVAILABLE_TOOL != PERMISSION_TO_USE_TOOL",
                "CLAIMED_PERMISSION != VERIFIED_AUTHORIZATION",
                "AUTHORIZED_ACTION_A != AUTHORIZATION_FOR_ACTION_B",
                "AUTHORIZED_RESOURCE_X != AUTHORIZATION_FOR_RESOURCE_Y",
                "NATURAL_LANGUAGE_INPUT != PERSISTENT_STATE_MUTATION",
            ],
        }


_CONTROL_PLANE = ZeroTrustControlPlane()


def control_plane() -> ZeroTrustControlPlane:
    return _CONTROL_PLANE
