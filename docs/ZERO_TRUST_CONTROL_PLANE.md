# PhilthyParleys Zero-Trust Control Plane

Status: implemented on the `zero-trust-control-plane-hardening` branch for privileged CI signing operations.

## Governing invariant

```text
LLM_COMPROMISE != CONTROL_PLANE_COMPROMISE
```

The application treats models, prompts, retrieved files, GitHub content, connector output, tool prose, JSON/YAML fields, comments, and other natural-language or model-generated material as evidence/data. None of those inputs can grant themselves authority.

```text
UNTRUSTED_DATA != GOVERNING_AUTHORITY
RETRIEVED_INSTRUCTION != EXECUTION_PERMISSION
MODEL_OUTPUT != AUTHORIZATION
CLAIMED_PERMISSION != VERIFIED_AUTHORIZATION
AVAILABLE_TOOL != PERMISSION_TO_USE_TOOL
AUTHORIZED_ACTION_A != AUTHORIZATION_FOR_ACTION_B
AUTHORIZED_RESOURCE_X != AUTHORIZATION_FOR_RESOURCE_Y
NATURAL_LANGUAGE_INPUT != PERSISTENT_STATE_MUTATION
```

## Protected operations

The first implementation protects the repository's highest-value CI signing surfaces:

1. Android release signing-material access.
2. Promoted-model artifact signing.

The HTTP routes remain backward-compatible. The privileged cryptographic functions now enforce a separate deterministic authorization boundary after GitHub OIDC authentication and immediately before secret/key use.

## Trust flow

```text
GitHub Actions OIDC token
        |
        v
Cryptographic JWT verification
  issuer + audience + signature + expiry
        |
        v
Authenticated identity only
  (NOT YET AUTHORIZED FOR AN ACTION)
        |
        v
CANDIDATE_ONLY
  exact action
  exact method
  exact resource
  exact destination
  optional canonical resource SHA-256
        |
        v
====================================================
DETERMINISTIC ZERO-TRUST AUTHORIZATION BOUNDARY
====================================================
  exact repository name
  exact stable repository ID
  exact stable repository-owner ID
  trusted main ref
  exact workflow/action mapping
  exact workflow commit SHA
  exact repository commit SHA
  actor ID
  run ID + run attempt
  exact event-type allowlist
  GitHub-hosted runner constraint when claim exists
  resource/destination/method scope
  token fingerprint
  replay reservation
        |
        v
AUTHORIZED_FOR_EXACT_ACTION
        |
        v
HMAC-bound short-lived execution permit
        |
        v
single-use permit consumption
        |
        v
privileged cryptographic operation
```

The stable identity pins are:

```text
repository: filthycashout/betp-app-
repository_id: 1180661052
repository_owner_id: 208737286
ref: refs/heads/main
```

The stable IDs prevent a repository or owner name from being treated as sufficient identity if the underlying GitHub object changes.

No natural-language field participates in authorization.

Claims such as the following are ignored unless they are part of the independently verified deterministic schema and policy:

```text
"administrator approved"
"priority zero"
"system override"
"user already confirmed"
"unrestricted"
"grant all permissions"
```

Adding those strings to a JWT payload, request body, artifact, prompt, comment, document, tool output, or model output does not create authorization.

## Authentication is not authorization

`verify_github_oidc()` verifies the GitHub-issued OIDC identity. It does not itself authorize every trusted workflow to perform every privileged operation.

The deterministic control plane maps each operation to a separate policy.

### Android signing-material export

Action:

```text
ANDROID_SIGNING_MATERIAL_EXPORT
```

Bound to:

```text
method: GET
resource: android-release-key
destination: github-actions-release-runner
workflow:
  - .github/workflows/philthysports-full-ci.yml@refs/heads/main
allowed events:
  - workflow_dispatch
```

The current release workflow itself is `workflow_dispatch` only, so the authorization policy does not pre-authorize a future `push` trigger that is not present today.

A model-training workflow authenticated for the same repository therefore cannot use its valid OIDC identity to obtain the Android signing material.

### Model artifact signing

Action:

```text
MODEL_ARTIFACT_SIGN
```

Bound to:

```text
method: POST
resource: model-artifact:<canonical-sha256>
destination: immutable-model-registry
workflow:
  - .github/workflows/v8-train-promote.yml@refs/heads/main
allowed events:
  - workflow_dispatch
  - push
  - schedule
```

The signed resource is bound to the canonical SHA-256 of the exact artifact body.

The signer also requires deterministic artifact-shape checks before private-key use:

- `status == PROMOTED_TRAINED_MODEL`;
- sport is NFL/NBA/MLB/NHL;
- non-empty model ID;
- `trained_weights == true`;
- `artifact_sha256` exactly matches the canonical unsigned core;
- strict-promotion check map exists and every check is exactly `true`;
- canonical payload does not exceed 2 MiB.

These checks are consistency gates, not proof that scientific/model evidence is true. Dataset chronology, OOF calibration, leakage audits, model metrics, and evidence admission remain separate authoritative gates elsewhere in the repository.

## Candidate-only rule

Every privileged action begins as:

```python
ActionCandidate(
    status="CANDIDATE_ONLY",
    authorization=None,
    execution_permit=None,
    executable=False,
)
```

There is no API that accepts a model-generated `authorized=true`, `admin=true`, prompt string, or free-form role claim and converts it to authority.

Forbidden:

```text
CANDIDATE_ONLY
  -> model/document/tool says "authorized"
  -> EXECUTE
```

Required:

```text
CANDIDATE_ONLY
  -> deterministic policy validation
  -> cryptographically bound permit
  -> exact permit consumption
  -> privileged operation
```

## Execution permit

A successful authorization issues a short-lived permit bound to:

- action;
- HTTP method;
- resource ID;
- resource SHA-256 when required;
- destination;
- repository and stable repository ID;
- stable repository-owner ID;
- workflow ref and workflow SHA;
- commit SHA;
- run ID and run attempt;
- actor ID;
- event name;
- issue and expiration times.

The binding is SHA-256 hashed and authenticated with a server-process HMAC key. The permit is single-use and cannot be rebound to a different resource, destination, digest, or action.

## Replay defense

The control plane records a replay key derived from:

```text
token fingerprint
+ exact action
+ exact resource
+ canonical resource digest when applicable
```

Reusing the same authenticated token for the same protected action/resource is denied.

For model promotion, the same OIDC token may authorize different artifact digests but not the same digest twice.

Current replay state is process-local. This is intentionally documented as a limitation; a multi-replica signer requires a durable/atomic replay store (for example a transactional database or KMS-backed nonce ledger) before replay prevention can be classified as globally verified.

## Fail-fast denial order

The control plane denies on the first decisive failure, including:

```text
INVALID_CANDIDATE_STATE
UNKNOWN_ACTION
METHOD_SCOPE_MISMATCH
RESOURCE_SCOPE_MISMATCH
DESTINATION_SCOPE_MISMATCH
RESOURCE_DIGEST_REQUIRED
UNTRUSTED_REPOSITORY
UNTRUSTED_REPOSITORY_ID
UNTRUSTED_REPOSITORY_OWNER_ID
UNTRUSTED_REF
WORKFLOW_ACTION_MISMATCH
UNTRUSTED_EVENT
ISSUER_MISMATCH
AUDIENCE_MISMATCH
SUBJECT_REQUIRED
IDENTITY_CLAIM_INVALID
RUNNER_ENVIRONMENT_DENIED
REF_TYPE_DENIED
TOKEN_FINGERPRINT_INVALID
TOKEN_EXPIRY_INVALID
TOKEN_EXPIRED
REPLAY_DETECTED
PERMIT_EXPIRED
PERMIT_BINDING_MISMATCH
PERMIT_INTEGRITY_FAILURE
PERMIT_ALREADY_CONSUMED
```

A denied candidate is final for that exact attempt. It is not silently promoted or retried by the control plane.

## Adversarial regression suite

`backend/tests/test_zero_trust_control_plane.py` covers:

- candidate begins non-executable;
- exact workflow/action success;
- action-A authorization does not grant action-B authority;
- resource-scope expansion denial;
- destination-scope expansion denial;
- method-scope expansion denial;
- self-declared administrator/priority/system-override claims have no effect;
- wrong repository denial;
- same-name repository with wrong stable repository ID denial;
- same-name owner with wrong stable owner ID denial;
- Android-signing event expansion denial;
- wrong ref denial;
- malformed authoritative identity claim denial;
- commit/workflow-SHA binding;
- self-hosted runner denial when the claim is present;
- replay denial;
- separate model digests remain independently scoped;
- single-use execution permit;
- permit rebinding denial;
- expired-token denial.

The existing backend CI already runs all tests under `backend/tests`, so these regressions are automatically included in the normal backend test job.

## Residual signing risk: not yet eliminated

The Android release flow still returns raw P-256 private-key material to the authorized GitHub runner because the existing Android build pipeline expects a local PKCS#12 keystore.

That means this hardening materially narrows who/what can obtain the key, but it does **not** establish the strongest possible non-exportable signing boundary.

Current classification:

```text
OIDC AUTHENTICATION: implemented
EXACT ACTION AUTHORIZATION: implemented
STABLE REPOSITORY IDENTITY BINDING: implemented
WORKFLOW/ACTION SEPARATION: implemented
RESOURCE/DESTINATION/EVENT BINDING: implemented
SHORT-LIVED SINGLE-USE PERMIT: implemented
PROCESS-LOCAL REPLAY DEFENSE: implemented
MODEL-ARTIFACT DIGEST BINDING: implemented
NON-EXPORTABLE ANDROID PRIVATE KEY: NOT IMPLEMENTED
GLOBAL MULTI-REPLICA REPLAY STORE: NOT IMPLEMENTED
```

Do not classify the Android signer as fully zero-trust/non-exportable until the private key never leaves a dedicated signer/HSM/KMS boundary.

## Target phase 2

The stronger architecture is:

```text
unsigned APK digest / signing request
        |
        v
exact GitHub OIDC + control-plane authorization
        |
        v
non-exportable signer / HSM / KMS
        |
        v
signature or signed artifact
        |
        v
independent certificate + artifact-hash verification
```

The GitHub runner should receive only the signed result, never the release private key.

Implementing that correctly requires an actual server-side Android APK signing capability or external non-exportable signing service. This repository change does not fabricate that capability.

## Final security classification

For the implemented CI authorization layer, model/prompt/retrieved-content authority promotion is structurally excluded from the privileged decision path.

```text
MODEL_OUTPUT != BACKEND_AUTHORITY
CLAIMED_PERMISSION != VERIFIED_AUTHORIZATION
VALID_SCHEMA != AUTHORIZED_ACTION
CONNECTED != AUTHORIZED_FOR_ALL_ACTIONS
AUTHENTICATION != AUTHORIZATION
```

The system remains secure only if the privileged executor continues to consume permits from this deterministic boundary rather than treating model output, documents, tool prose, or natural-language claims as authority.

```text
THE LLM MAY LOSE.
THE CONTROL PLANE MUST STILL WIN.
```
