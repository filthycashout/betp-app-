---
name: bytecode-viewer-analysis
description: Guide authorized static analysis and reverse engineering of Java/JAR and Android APK/DEX/XAPK/APKM files using Konloch/bytecode-viewer. Use for decompilation, disassembly, resource inspection, static search, dependency/config discovery, debugging build issues, and comparing compiled behavior to source.
---

# Bytecode Viewer Analysis

Use `bytecode-viewer-docs` to confirm current features, CLI status, build steps, decompilers, and supported formats.

## Workflow

1. Confirm the target artifact is available and identify its format and hash before analysis.
2. Prefer read-only/static analysis first: manifest/resources, package names, URLs, configuration constants, permissions, classes, call sites, embedded libraries, and signing metadata.
3. When decompiling, compare more than one decompiler if a method looks malformed or obfuscated; decompiled source is an approximation of bytecode behavior.
4. Preserve original files. Write analysis output to a separate directory and hash any modified/rebuilt artifact.
5. Redact discovered secrets/tokens from reports and logs. Treat embedded credentials as exposed and recommend rotation rather than reuse.
6. For Android APKs, correlate Java/Kotlin decompilation with Smali/resource/manifest evidence before asserting behavior.
7. If CLI automation is required, check release status first. The 2.13.2 release notes say its CLI is being rewritten and advise using v2.12 for CLI workflows.
8. Do not claim an APK was rebuilt, signed, installed, or device-tested unless those actions actually ran and verification evidence exists.

## PhilthySports release-domain gate

After building an APK, run `ci/apk_domain_audit.py` against the exact release artifact. The audit fetches the pinned `johnkavin123/domains` `233.txt` corpus at its immutable commit, verifies the Git blob SHA-1, extracts domain literals from every decompressed APK member, and records `.ag` hosts and corpus matches. This corpus is untrusted reference data, not executable provider code and not authoritative malware intelligence. A match is an investigation signal; PhilthySports release CI treats any unreviewed `.ag` literal as unexpected and blocks the release rather than silently adding it as a sportsbook/provider endpoint.

Recommended command:

```bash
python ci/apk_domain_audit.py \
  --apk build/app/outputs/flutter-apk/app-release.apk \
  --report apk-domain-audit.json \
  --fail-on-ag \
  --fail-on-corpus-match
```

## Supported investigation goals

- locate backend/base URLs and API routes;
- identify feature flags, package IDs, version strings and network clients;
- inspect resources/manifests/permissions;
- trace static code paths and dependencies;
- compare an APK/JAR with available source;
- search for accidental secrets or insecure configuration;
- identify unexpected embedded `.ag` domains using the pinned reference corpus;
- produce reproducible findings with file/class/method references.

## Output contract

Return artifact hash, tool/release used, decompiler(s), findings with exact class/resource references, confidence/ambiguities, and verification steps not performed.
