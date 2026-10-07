# PhilthyParleys release evidence history

This file preserves non-secret historical build/signing evidence. It is archival: a prior successful build does not make a later commit validated.

The current source version is defined by `pubspec.yaml`. The release signing certificate currently pinned by CI is:

`97BE4C2028288638C8BE55CE7540164A1995A1F18675964E3D8E733744D89700`

| Version | Source commit | CI run | APK SHA-256 | Evidence summary |
| --- | --- | ---: | --- | --- |
| 1.5.2+19 | `013357dee944e7329593f0986c27648f1f72d480` | 37077311253 | `ce35f16dab5ebb342dbd8b2eb3dde61ce68e3e3d7fd10f3bf8f0c5ba13c3bbdf` | release build/signature/emulator evidence; physical device NOT_RUN |
| 1.5.3+20 | `28f41f620d487312872d2bb4168036eeeb543ec0` | 37110838130 | `38c1f69f7931fbc2c69087ef3dc501a4ada01dbe67428c50b14ad6a395002915` | backend/selftest/build/sign/emulator PASS; physical device NOT_RUN |
| 1.5.4+21 | `92f6a3cb0544ca089072a1d364e28895d237d1e8` | 37116761940 | `12c8fba2b468d06840e28fea5af10bb5c45e733fe7ff659b8e926cc706c901fb` | stable signer and exact APK emulator install/launch PASS |
| 1.6.0+22 | `1935bc9531e1cfe87e2792cac86b9e560ba04e4c` | 37177924944 | `a1a4f6e75202c37fdd35bf6bec3b80e331f5986e3f74db51b8057544a83db9d3` | exact APK emulator PASS; NFL/NBA/MLB/NHL fresh score feeds and Settings PASS |
| 1.6.1+23 | `93ff5858d5cb46c4e080a9e49800ffab57b06765` | 37185814281 | `6a130b0b5c09d21be323bc16f0d5a0d84a2e9516a29a07f5f407b60906440d52` | backend migrated to API v9; stable signing/emulator PASS |
| 1.6.3 | `5db3476f9adb0cdbe4ebfd5b063aa8e0a5b88edb` | 37223019232 | `9526a920a233b61e44d966b67a8727d148977ca30cb18d982bdc069c4acc6c33` | bundled dashboard, four-sport fresh score feeds, Picks/Parlays/Settings and emulator PASS |
| 1.6.6+29 | `d90e6baa415cfb304320dbfef43f4f8b0c1710b2` | 37542842832 | `67db6cae924342d20f107c66ab47e0875a10dfb923a54b057156a144848117e1` | Full CI backend/android/emulator PASS; exact signed APK artifact produced; physical device NOT_RUN |

## Interpretation

- The APK SHA identifies the exact binary, not overall system readiness.
- The certificate fingerprint establishes the current compatible release-signing identity.
- Emulator success does not close the physical-device gate.
- Backend health, live-provider credential proof, model promotion and operations drills are separate gates.
- A current commit must use its own current CI artifact/evidence rather than inheriting the status of an older row in this table.

GitHub Actions remains the preferred distribution point for generated APK binaries; APK binaries are not duplicated into repository source history merely to preserve a release record.
