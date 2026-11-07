param()
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$toolRoot = Join-Path $repo 'data/android-build'
$jdk = Get-ChildItem -LiteralPath (Join-Path $toolRoot 'jdk') -Directory | Select-Object -First 1
if (!$jdk) { throw 'The local Android JDK is missing.' }
$env:JAVA_HOME = $jdk.FullName
$env:ANDROID_HOME = Join-Path $toolRoot 'sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:GRADLE_USER_HOME = Join-Path $repo '.g'
$env:OFFICE_KEYSTORE = Join-Path $toolRoot 'office-release.keystore'
$env:CI = '1'
Push-Location -LiteralPath (Join-Path $repo 'mobile/android')
try {
    & .\gradlew.bat :office-documents:testReleaseUnitTest :office-documents:lintRelease '-Pandroid.onlyEnableUnitTestForTheTestedBuildType=false' '-PreactNativeArchitectures=arm64-v8a,armeabi-v7a' --max-workers=2 --no-daemon --console=plain
    if ($LASTEXITCODE -ne 0) { throw 'Android document verification failed.' }
} finally { Pop-Location }
