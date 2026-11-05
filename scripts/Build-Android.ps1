[CmdletBinding()]
param([switch]$SkipPrebuild)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$toolRoot = Join-Path $repo 'data/android-build'
$mobile = Join-Path $repo 'mobile'
$jdk = Get-ChildItem -LiteralPath (Join-Path $toolRoot 'jdk') -Directory | Select-Object -First 1
if (!$jdk) { throw 'Install the official JDK in data/android-build/jdk first.' }
$env:JAVA_HOME = $jdk.FullName
$env:ANDROID_HOME = Join-Path $toolRoot 'sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:GRADLE_USER_HOME = Join-Path $repo '.g'
$env:Path = "$env:JAVA_HOME\bin;$env:ANDROID_HOME\platform-tools;$env:Path"
$env:CI = '1'
$tailscale = Join-Path $env:ProgramFiles 'Tailscale/tailscale.exe'
if (!$env:EXPO_PUBLIC_OFFICE_URL -and (Test-Path -LiteralPath $tailscale)) {
    $network = & $tailscale status --json | ConvertFrom-Json
    if ($network.BackendState -eq 'Running' -and $network.Self.DNSName) {
        $env:EXPO_PUBLIC_OFFICE_URL = 'https://' + $network.Self.DNSName.TrimEnd('.')
    }
}
Push-Location -LiteralPath $mobile
try {
    & bun run typecheck
    if ($LASTEXITCODE -ne 0) { throw 'Type checking failed.' }
    if (!$SkipPrebuild) {
        & bunx expo prebuild --platform android --no-install
        if ($LASTEXITCODE -ne 0) { throw 'Android project generation failed.' }
    } elseif (!(Test-Path -LiteralPath (Join-Path $mobile 'android/app/build.gradle'))) {
        throw 'Generate the native project with a full build before using SkipPrebuild.'
    }
    $secretsPath = Join-Path $toolRoot 'signing.json'
    if (!(Test-Path -LiteralPath $secretsPath)) {
        $randomBytes = New-Object byte[] 36
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($randomBytes) } finally { $rng.Dispose() }
        @{ password = [Convert]::ToBase64String($randomBytes); alias = 'office-release' } |
            ConvertTo-Json | Set-Content -LiteralPath $secretsPath -Encoding UTF8
    }
    $signing = Get-Content -LiteralPath $secretsPath -Raw | ConvertFrom-Json
    $env:OFFICE_KEY_PASSWORD = $signing.password
    $env:OFFICE_KEY_ALIAS = $signing.alias
    $env:OFFICE_KEYSTORE = Join-Path $toolRoot 'office-release.keystore'
    if (!(Test-Path -LiteralPath $env:OFFICE_KEYSTORE)) {
        & "$env:JAVA_HOME/bin/keytool.exe" -genkeypair -keystore $env:OFFICE_KEYSTORE `
            -storepass:env OFFICE_KEY_PASSWORD -keypass:env OFFICE_KEY_PASSWORD `
            -alias $env:OFFICE_KEY_ALIAS -keyalg RSA -keysize 3072 -validity 10000 `
            -dname 'CN=H.S. TRADERS, OU=Office, O=H.S. TRADERS, L=Amritsar, ST=Punjab, C=IN'
        if ($LASTEXITCODE -ne 0) { throw 'App signing key generation failed.' }
    }
    $gradlePath = Join-Path $mobile 'android/app/build.gradle'
    $gradle = Get-Content -LiteralPath $gradlePath -Raw
    $releaseConfig = @'
    signingConfigs {
        officeRelease {
            storeFile file(System.getenv('OFFICE_KEYSTORE'))
            storePassword System.getenv('OFFICE_KEY_PASSWORD')
            keyAlias System.getenv('OFFICE_KEY_ALIAS')
            keyPassword System.getenv('OFFICE_KEY_PASSWORD')
        }
'@
    if (!$gradle.Contains('officeRelease {')) {
        $gradle = $gradle.Replace('    signingConfigs {', $releaseConfig)
    }
    $gradle = $gradle.Replace('signingConfig signingConfigs.debug', 'signingConfig signingConfigs.officeRelease')
    if (!$gradle.Contains('CMAKE_OBJECT_PATH_MAX')) {
        $gradle = $gradle.Replace('    defaultConfig {', "    defaultConfig {`n        externalNativeBuild { cmake { arguments '-DCMAKE_OBJECT_PATH_MAX=240' } }")
    }
    $gradle = [regex]::Replace($gradle, 'CMAKE_OBJECT_PATH_MAX=\d+', 'CMAKE_OBJECT_PATH_MAX=240')
    [IO.File]::WriteAllText($gradlePath, $gradle, (New-Object Text.UTF8Encoding($false)))
    # Build both common phone architectures; no emulator-only libraries.
    Push-Location -LiteralPath (Join-Path $mobile 'android')
    try {
        & .\gradlew.bat :app:assembleRelease '-PreactNativeArchitectures=arm64-v8a,armeabi-v7a' --max-workers=2 --no-daemon --console=plain
        if ($LASTEXITCODE -ne 0) { throw 'Android APK build failed.' }
    } finally { Pop-Location }
    $output = Join-Path $repo 'output/android'
    New-Item -ItemType Directory -Force -Path $output | Out-Null
    Copy-Item -LiteralPath (Join-Path $mobile 'android/app/build/outputs/apk/release/app-release.apk') `
        -Destination (Join-Path $output 'HS-Traders-Office.apk') -Force
    Write-Host "Signed APK saved to $output\HS-Traders-Office.apk"
    Write-Host 'Keep data/android-build/office-release.keystore and signing.json private and backed up for future updates.'
} finally {
    Remove-Item Env:OFFICE_KEY_PASSWORD -ErrorAction SilentlyContinue
    Pop-Location
}
