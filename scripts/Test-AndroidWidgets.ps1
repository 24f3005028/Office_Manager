param()
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$toolRoot = Join-Path $repo 'data/android-build'
$jdk = Get-ChildItem -LiteralPath (Join-Path $toolRoot 'jdk') -Directory | Select-Object -First 1
if (!$jdk) { throw 'The local Android JDK is missing.' }
$nativeProject = Join-Path $repo 'mobile/android'
if (!(Test-Path -LiteralPath (Join-Path $nativeProject 'gradlew.bat'))) {
    throw 'Run scripts/Build-Android.ps1 to generate the native project first.'
}
$env:JAVA_HOME = $jdk.FullName
$env:ANDROID_HOME = Join-Path $toolRoot 'sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:GRADLE_USER_HOME = Join-Path $repo '.g'
# Gradle evaluates the app signing file path even for library-only test tasks.
# These tasks do not sign an app, so no password is loaded or exposed.
$env:OFFICE_KEYSTORE = Join-Path $toolRoot 'office-release.keystore'
$env:CI = '1'
Push-Location -LiteralPath $nativeProject
try {
    & .\gradlew.bat :office-widgets:testReleaseUnitTest :office-widgets:lintRelease '-Pandroid.onlyEnableUnitTestForTheTestedBuildType=false' '-PreactNativeArchitectures=arm64-v8a,armeabi-v7a' --max-workers=2 --no-daemon --console=plain
    if ($LASTEXITCODE -ne 0) { throw 'Android widget verification failed.' }
} finally { Pop-Location }
