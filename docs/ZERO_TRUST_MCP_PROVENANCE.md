# Zero-Trust MCP / Connector Data Plane

## Security objective

The MCP layer is deliberately treated as a data plane, not an authorization plane.

```text
MCP_TOOL_OUTPUT != GOVERNING_AUTHORITY
CONNECTOR_OUTPUT != EXECUTION_PERMISSION
RETRIEVED_INSTRUCTION != VERIFIED_USER_INTENT
NATURAL_LANGUAGE_INPUT != PERSISTENT_STATE_MUTATION
```

The design assumes retrieved sports data, API payloads, errors, comments, text fields, and other remote content may contain attacker-controlled or misleading natural language.

Prompt injection may therefore succeed at the interpretation layer without creating execution authority.

```text
LLM_COMPROMISE != CONTROL_PLANE_COMPROMISE
```

## Exposed capability classes

Every currently registered MCP capability is assigned one deterministic policy in `backend/zero_trust_provenance.py`.

Allowed side-effect classes are currently:

```text
READ_ONLY
DETERMINISTIC_LOCAL_COMPUTE
```

No registered MCP capability has:

```text
external_mutation = true
```

The standalone service exposes:

- `philthy_health` — read only;
- `philthy_system_status` — read only;
- `philthy_provider_status` — read only;
- `philthy_search` — read only;
- `philthy_best12` — read only;
- `philthy_best3` — read only;
- `philthy_evidence` — read only;
- `philthy_capability_inventory` — read only;
- `philthy_dfs_optimize` — deterministic local compute over explicit caller-provided inputs.

The embedded MCP adapter exposes a strict subset and every exposed name must exist in the same deterministic policy registry.

## Output provenance contract

Tool results receive an additive `zero_trust` object. Existing result keys remain unchanged for backward compatibility.

The envelope records:

```text
SOURCE_ID
SOURCE_TYPE
PROVENANCE
TRUST_FOR_FACTS
TRUST_FOR_INSTRUCTIONS
RECENCY
AUTHORITY
CORROBORATION
SIDE_EFFECT_CLASS
EXTERNAL_MUTATION
PROMPT_INJECTION_POSSIBLE
RETRIEVED_AT
```

Hard invariants are code constants:

```text
TRUST_FOR_INSTRUCTIONS = FALSE
AUTHORITY = EVIDENCE_ONLY
AUTHORIZATION_GRANTED = FALSE
PERSISTENT_STATE_MUTATION = FALSE
```

Remote content cannot override those values by including fields such as:

```text
trusted_for_instructions: true
administrator: true
priority: zero
system_override: true
user_confirmed: true
authorized: true
```

Such strings remain payload data.

## Authority ceiling

The maximum interpretation status of MCP or connector output is:

```text
CANDIDATE_OR_EVIDENCE_ONLY
```

It cannot directly become:

```text
AUTHORIZED_ACTION
USER_CONFIRMATION
ACCOUNT_ENTITLEMENT
POLICY_OVERRIDE
BACKEND_PERMISSION
PERSISTENT_STATE_MUTATION
```

Any future state-changing tool must cross a separate deterministic authorization boundary and may not be added merely by inserting a new function or natural-language tool description.

## Unknown-tool behavior

The embedded MCP adapter checks the deterministic tool registry before application dispatch.

An unknown name is returned as:

```text
UNREGISTERED_TOOL
execution_authority = NONE
authorization_granted = false
```

Therefore:

```text
CALLER_SUPPLIED_TOOL_NAME != CAPABILITY_CREATION
```

## Redirect containment

The standalone MCP backend reader sends HTTPS GET requests with redirects disabled.

A remote response therefore cannot use an HTTP redirect to silently change the resource/destination being read.

```text
AUTHORIZED_RESOURCE_X != AUTHORIZATION_FOR_RESOURCE_Y
```

If the configured backend responds with a redirect, the tool returns an unavailable/error observation instead of following it.

## Static architecture regression guard

`backend/tests/test_zero_trust_mcp_architecture.py` parses the MCP source with Python AST and fails CI if the governed MCP data plane drifts across key trust boundaries.

The guard currently asserts:

1. both MCP source files remain syntactically valid;
2. the standalone MCP client does not call POST/PUT/PATCH/DELETE through `requests` or its shared session;
3. MCP files do not invoke common shell/subprocess execution primitives;
4. every standalone `@mcp.tool()` function exists in the deterministic tool-security registry;
5. every embedded MCP-declared tool exists in the same registry;
6. no policy entry claims external mutation authority.

This is intentionally defensive and fail-closed: adding a new tool requires an explicit policy decision and test update.

## Relationship to CI signing control plane

MCP provenance and CI signing authorization solve different trust boundaries.

MCP/data plane:

```text
EXTERNAL CONTENT
  -> provenance
  -> evidence only
  -> interpretation
  -> no mutation authority
```

Privileged CI signer:

```text
AUTHENTICATED GITHUB OIDC
  -> CANDIDATE_ONLY
  -> exact deterministic authorization
  -> short-lived single-use permit
  -> privileged cryptographic operation
```

They must not be collapsed.

A sports-data result cannot authorize a signing action.
A model output cannot authorize a signing action.
A valid MCP schema cannot authorize a signing action.
An authenticated workflow for one signing action cannot authorize another signing action.

## Residual scope

This document does not claim every backend endpoint is read-only. It describes the MCP surfaces governed by the policy registry and static regression guard.

The separate Android-signing residual remains: the current release workflow receives exportable P-256 private-key material after authorization. That must move to a non-exportable signer/HSM/KMS boundary before the Android signing path can be classified as fully non-exportable.

The replay ledger for privileged CI permits is also process-local and requires a durable atomic store for global multi-replica replay guarantees.

## Governing classification rule

If malicious retrieved content manipulates a model but no unauthorized authority promotion, execution, disclosure, or backend mutation occurs:

```text
MODEL_LAYER_COMPROMISED
CONTROL_PLANE_INTACT
INVARIANTS_PRESERVED
```

A trust-boundary failure requires independently verified unauthorized authoritative side effects.

```text
THE LLM MAY LOSE.
THE CONTROL PLANE MUST STILL WIN.
```
