---
name: bytecode-viewer-analysis
description: Guide authorized static analysis and reverse engineering of Java/JAR and Android APK/DEX/XAPK/APKM files using Konloch/bytecode-viewer. Use for decompilation, disassembly, resource inspection, static search, dependency/config discovery, release verification, debugging build issues and comparing compiled behavior to source.
---

# Bytecode Viewer Analysis

Use `bytecode-viewer-docs` to confirm current features, CLI status, build steps, decompilers and supported formats. The PhilthySports production MCP exposes this capability as guidance/routing only; it does not claim remote decompilation or device execution.

## Pinned upstream

- Repository: `Konloch/bytecode-viewer`
- Branch: `master`
- Verified current commit: `31430e0033fa220db566b5ef461256727ff6793b`
- Current pinned interface-inspection version: Bytecode Viewer 2.13.2
- PhilthySports lock: `integrations/upstreams.lock.json`

Reproduce the selected-source checkout with:

```bash
bash scripts/clone_external_analysis_repos.sh
```

The checkout must verify the exact pinned commit. Do not silently float to upstream `master` during release verification even when the current branch head matches the pin.

## Workflow

1. Confirm the target artifact exists and record its SHA-256 before analysis.
2. Prefer read-only/static inspection first: package name, version, manifest/resources, permissions, URLs, feature flags, configuration constants, signing metadata, libraries and call sites.
3. When a decompiled method looks malformed or obfuscated, compare more than one decompiler and correlate with bytecode/Smali; decompiled source is an approximation of executable behavior.
4. Preserve the original artifact. Write extracted/decompiled/rebuilt output to a separate path and hash every changed artifact.
5. Redact discovered tokens/secrets from reports. Treat embedded credentials as exposed and rotate them rather than reusing them.
6. For Android, correlate Java/Kotlin decompilation with Smali/resource/manifest evidence before asserting behavior.
7. Use only CLI/build modes actually validated in the execution environment. The pinned source version does not itself prove a given CLI invocation works on a target machine.
8. Do not claim an APK was rebuilt, signed, installed, launched or physical-device tested unless those actions actually ran and produced evidence.
9. Do not use this skill to bypass account/security controls or to deploy modified third-party software without authorization.

## PhilthySports release-domain gate

After building an APK, run `ci/apk_domain_audit.py` against the exact release artifact. The audit checks decompressed APK members for domain literals and compares them with the pinned reference corpus used by PhilthySports release CI.

Recommended command:

```bash
python ci/apk_domain_audit.py \
  --apk build/app/outputs/flutter-apk/app-release.apk \
  --report apk-domain-audit.json \
  --fail-on-ag \
  --fail-on-corpus-match
```

A corpus/domain match is an investigation signal, not proof of malicious behavior. Unexpected `.ag` literals or unreviewed corpus matches block PhilthySports release verification until reviewed.

## Supported investigation goals

- locate backend/base URLs and API routes;
- identify package IDs, versions, feature flags and network clients;
- inspect manifests/resources/permissions;
- trace static code paths and dependencies;
- compare an APK/JAR with available source;
- search for accidental secrets or insecure configuration;
- identify unexpected embedded domains;
- verify signing/package metadata;
- produce reproducible findings with exact file/class/method/resource references.

## Output contract

Return artifact hash, pinned tool commit/version, decompiler(s)/analysis method, exact findings with class/resource references, confidence/ambiguities, discovered secrets only in redacted form, and every verification step that was not performed.
