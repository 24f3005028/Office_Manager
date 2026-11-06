# H.S. Traders Office 1.4.1

Android package `com.hstraders.office`, versionCode `8`. Install over the existing app.

## Startup crash fix

Fixes an immediate release-only crash before the app screen opens. The connected
phone's native crash log identified `WorkDatabase_Impl.<init>` missing during
AndroidX Startup. R8 full mode had removed the reflective no-argument constructor
needed by WorkManager's Room database.

Tracked release rules now retain Room database and WorkManager input merger
constructors. The local build script attaches the rules after both normal prebuild
and `-SkipPrebuild`, and fails if the expected generated configuration changes.
Release optimization remains enabled. The narrow fix follows the
[upstream Expo issue](https://github.com/expo/expo/issues/51337).

## Validation

- Built the signed release APK locally; verified version, ARM64/ARMv7 and v2 signature.
- Confirmed the final R8 seeds retain `WorkDatabase_Impl`, `ArrayCreatingInputMerger`
  and `OverwritingInputMerger` constructors.
- Installed with Android's replace/update option on the connected Android phone,
  without uninstalling or clearing app data.
- Three cold launches reached React Native and remained alive; the final launch
  stayed running for over 30 seconds. One intermediate process poll was inconclusive
  and was repeated with a longer observation. No fresh native crash was recorded
  after the update. The app's connection screen was confirmed in the UI hierarchy.
- All 17 mobile regression tests, TypeScript checking and PowerShell script syntax
  validation passed.

This hotfix changes Android startup/build rules only. Business report generation,
WhatsApp delivery and authenticated mobile actions were not re-tested on the phone.

APK SHA-256: `0e8a55549fba979664b9d0612bee5d9ab592860aadd028a48109de4581d94a41`.
APK size: 35,460,396 bytes.
