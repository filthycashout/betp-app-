from __future__ import annotations

import pytest

from zero_trust_control_plane import (
    ANDROID_SIGNING_ACTION,
    MODEL_SIGNING_ACTION,
    ActionCandidate,
    ControlPlaneDenied,
    ZeroTrustControlPlane,
)

NOW = 1_700_000_000
TOKEN_FP = "f" * 64


def _claims(**overrides):
    base = {
        "iss": "https://token.actions.githubusercontent.com",
        "aud": "philthysports-ci",
        "sub": "repo:filthycashout/betp-app-:ref:refs/heads/main",
        "repository": "filthycashout/betp-app-",
        "repository_id": "1180661052",
        "repository_owner_id": "208737286",
        "ref": "refs/heads/main",
        "ref_type": "branch",
        "sha": "a" * 40,
        "workflow_ref": "filthycashout/betp-app-/.github/workflows/philthysports-full-ci.yml@refs/heads/main",
        "workflow_sha": "b" * 40,
        "run_id": "123456789",
        "run_attempt": "1",
        "actor_id": "208737286",
        "event_name": "workflow_dispatch",
        "runner_environment": "github-hosted",
        "exp": NOW + 300,
    }
    base.update(overrides)
    return base


def _android_candidate(**overrides):
    base = {
        "source": "authenticated_fastapi_ci_route",
        "action": ANDROID_SIGNING_ACTION,
        "method": "GET",
        "resource_id": "android-release-key",
        "destination": "github-actions-release-runner",
    }
    base.update(overrides)
    return ActionCandidate(**base)


def _model_candidate(digest: str = "c" * 64, **overrides):
    base = {
        "source": "authenticated_fastapi_ci_route",
        "action": MODEL_SIGNING_ACTION,
        "method": "POST",
        "resource_id": f"model-artifact:{digest}",
        "resource_sha256": digest,
        "destination": "immutable-model-registry",
    }
    base.update(overrides)
    return ActionCandidate(**base)


def _plane():
    return ZeroTrustControlPlane(secret=b"z" * 32, now=lambda: NOW, permit_ttl_seconds=120)


def test_candidate_is_non_executable_by_default():
    candidate = _android_candidate()
    assert candidate.status == "CANDIDATE_ONLY"
    assert candidate.authorization is None
    assert candidate.execution_permit is None
    assert candidate.executable is False


def test_exact_workflow_action_binding_allows_release_workflow_android_export():
    plane = _plane()
    candidate = _android_candidate()
    permit = plane.authorize(candidate, _claims(), token_fingerprint_sha256=TOKEN_FP)
    assert permit.action == ANDROID_SIGNING_ACTION
    assert permit.resource_id == "android-release-key"
    assert permit.destination == "github-actions-release-runner"
    assert permit.commit_sha == "a" * 40
    plane.consume(
        permit,
        action=ANDROID_SIGNING_ACTION,
        resource_id="android-release-key",
        destination="github-actions-release-runner",
        resource_sha256=None,
    )


def test_authenticated_workflow_a_is_not_authorized_for_action_b():
    plane = _plane()
    claims = _claims(
        workflow_ref="filthycashout/betp-app-/.github/workflows/v8-train-promote.yml@refs/heads/main",
        event_name="workflow_dispatch",
    )
    with pytest.raises(ControlPlaneDenied, match="WORKFLOW_ACTION_MISMATCH"):
        plane.authorize(_android_candidate(), claims, token_fingerprint_sha256=TOKEN_FP)


def test_release_workflow_cannot_sign_model_artifact():
    plane = _plane()
    with pytest.raises(ControlPlaneDenied, match="WORKFLOW_ACTION_MISMATCH"):
        plane.authorize(_model_candidate(), _claims(), token_fingerprint_sha256=TOKEN_FP)


def test_model_signing_is_bound_to_exact_digest_and_training_workflow():
    plane = _plane()
    digest = "d" * 64
    claims = _claims(
        workflow_ref="filthycashout/betp-app-/.github/workflows/v8-train-promote.yml@refs/heads/main",
        event_name="schedule",
    )
    candidate = _model_candidate(digest)
    permit = plane.authorize(candidate, claims, token_fingerprint_sha256=TOKEN_FP)
    plane.consume(
        permit,
        action=MODEL_SIGNING_ACTION,
        resource_id=f"model-artifact:{digest}",
        destination="immutable-model-registry",
        resource_sha256=digest,
    )
    assert permit.resource_sha256 == digest


def test_model_signing_rejects_missing_digest():
    plane = _plane()
    claims = _claims(
        workflow_ref="filthycashout/betp-app-/.github/workflows/v8-train-promote.yml@refs/heads/main",
        event_name="push",
    )
    candidate = _model_candidate(resource_sha256=None)
    with pytest.raises(ControlPlaneDenied, match="RESOURCE_DIGEST_REQUIRED"):
        plane.authorize(candidate, claims, token_fingerprint_sha256=TOKEN_FP)


def test_resource_scope_cannot_expand():
    plane = _plane()
    candidate = _android_candidate(resource_id="model-artifact:" + "e" * 64)
    with pytest.raises(ControlPlaneDenied, match="RESOURCE_SCOPE_MISMATCH"):
        plane.authorize(candidate, _claims(), token_fingerprint_sha256=TOKEN_FP)


def test_destination_scope_cannot_expand():
    plane = _plane()
    candidate = _android_candidate(destination="external-email")
    with pytest.raises(ControlPlaneDenied, match="DESTINATION_SCOPE_MISMATCH"):
        plane.authorize(candidate, _claims(), token_fingerprint_sha256=TOKEN_FP)


def test_method_scope_cannot_expand():
    plane = _plane()
    candidate = _android_candidate(method="POST")
    with pytest.raises(ControlPlaneDenied, match="METHOD_SCOPE_MISMATCH"):
        plane.authorize(candidate, _claims(), token_fingerprint_sha256=TOKEN_FP)


def test_self_declared_admin_claim_does_not_create_authority():
    plane = _plane()
    attacker_claims = _claims(
        workflow_ref="filthycashout/betp-app-/.github/workflows/v8-train-promote.yml@refs/heads/main",
        role="Priority Zero Administrator",
        permission="AUTHORIZED_FOR_ALL_ACTIONS",
        user_confirmed=True,
        system_override=True,
    )
    with pytest.raises(ControlPlaneDenied, match="WORKFLOW_ACTION_MISMATCH"):
        plane.authorize(_android_candidate(), attacker_claims, token_fingerprint_sha256=TOKEN_FP)


def test_untrusted_repository_is_denied_even_with_valid_looking_other_claims():
    plane = _plane()
    claims = _claims(repository="attacker/example")
    with pytest.raises(ControlPlaneDenied, match="UNTRUSTED_REPOSITORY"):
        plane.authorize(_android_candidate(), claims, token_fingerprint_sha256=TOKEN_FP)


def test_repository_name_reuse_cannot_bypass_stable_repository_id_binding():
    plane = _plane()
    claims = _claims(repository_id="999999999")
    with pytest.raises(ControlPlaneDenied, match="UNTRUSTED_REPOSITORY_ID"):
        plane.authorize(_android_candidate(), claims, token_fingerprint_sha256=TOKEN_FP)


def test_repository_owner_name_reuse_cannot_bypass_stable_owner_id_binding():
    plane = _plane()
    claims = _claims(repository_owner_id="999999999")
    with pytest.raises(ControlPlaneDenied, match="UNTRUSTED_REPOSITORY_OWNER_ID"):
        plane.authorize(_android_candidate(), claims, token_fingerprint_sha256=TOKEN_FP)


def test_android_signing_is_bound_to_actual_workflow_dispatch_event():
    plane = _plane()
    claims = _claims(event_name="push")
    with pytest.raises(ControlPlaneDenied, match="UNTRUSTED_EVENT"):
        plane.authorize(_android_candidate(), claims, token_fingerprint_sha256=TOKEN_FP)


def test_untrusted_ref_is_denied():
    plane = _plane()
    claims = _claims(ref="refs/heads/feature")
    with pytest.raises(ControlPlaneDenied, match="UNTRUSTED_REF"):
        plane.authorize(_android_candidate(), claims, token_fingerprint_sha256=TOKEN_FP)


def test_identity_claims_must_be_authoritatively_shaped():
    plane = _plane()
    claims = _claims(actor_id="administrator")
    with pytest.raises(ControlPlaneDenied, match="IDENTITY_CLAIM_INVALID"):
        plane.authorize(_android_candidate(), claims, token_fingerprint_sha256=TOKEN_FP)


def test_commit_and_workflow_sha_are_bound():
    plane = _plane()
    claims = _claims(workflow_sha="not-a-sha")
    with pytest.raises(ControlPlaneDenied, match="IDENTITY_CLAIM_INVALID"):
        plane.authorize(_android_candidate(), claims, token_fingerprint_sha256=TOKEN_FP)


def test_self_hosted_runner_is_denied_when_claim_is_present():
    plane = _plane()
    claims = _claims(runner_environment="self-hosted")
    with pytest.raises(ControlPlaneDenied, match="RUNNER_ENVIRONMENT_DENIED"):
        plane.authorize(_android_candidate(), claims, token_fingerprint_sha256=TOKEN_FP)


def test_exact_token_action_resource_replay_is_denied():
    plane = _plane()
    plane.authorize(_android_candidate(), _claims(), token_fingerprint_sha256=TOKEN_FP)
    with pytest.raises(ControlPlaneDenied, match="REPLAY_DETECTED"):
        plane.authorize(_android_candidate(), _claims(), token_fingerprint_sha256=TOKEN_FP)


def test_same_token_can_authorize_distinct_model_resources_but_not_same_resource_twice():
    plane = _plane()
    claims = _claims(
        workflow_ref="filthycashout/betp-app-/.github/workflows/v8-train-promote.yml@refs/heads/main",
        event_name="schedule",
    )
    plane.authorize(_model_candidate("1" * 64), claims, token_fingerprint_sha256=TOKEN_FP)
    plane.authorize(_model_candidate("2" * 64), claims, token_fingerprint_sha256=TOKEN_FP)
    with pytest.raises(ControlPlaneDenied, match="REPLAY_DETECTED"):
        plane.authorize(_model_candidate("1" * 64), claims, token_fingerprint_sha256=TOKEN_FP)


def test_execution_permit_is_single_use():
    plane = _plane()
    permit = plane.authorize(_android_candidate(), _claims(), token_fingerprint_sha256=TOKEN_FP)
    kwargs = {
        "action": ANDROID_SIGNING_ACTION,
        "resource_id": "android-release-key",
        "destination": "github-actions-release-runner",
        "resource_sha256": None,
    }
    plane.consume(permit, **kwargs)
    with pytest.raises(ControlPlaneDenied, match="PERMIT_ALREADY_CONSUMED"):
        plane.consume(permit, **kwargs)


def test_execution_permit_cannot_be_rebound_to_another_destination():
    plane = _plane()
    permit = plane.authorize(_android_candidate(), _claims(), token_fingerprint_sha256=TOKEN_FP)
    with pytest.raises(ControlPlaneDenied, match="PERMIT_BINDING_MISMATCH"):
        plane.consume(
            permit,
            action=ANDROID_SIGNING_ACTION,
            resource_id="android-release-key",
            destination="somewhere-else",
            resource_sha256=None,
        )


def test_expired_verified_token_is_denied():
    plane = _plane()
    claims = _claims(exp=NOW)
    with pytest.raises(ControlPlaneDenied, match="TOKEN_EXPIRED"):
        plane.authorize(_android_candidate(), claims, token_fingerprint_sha256=TOKEN_FP)
