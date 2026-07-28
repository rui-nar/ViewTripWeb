<#
.SYNOPSIS
    Create the Android release signing keystore and print everything derived
    from it that has to be configured elsewhere (issue #136).

.DESCRIPTION
    Android ties an app's identity to its signing key: an update must be signed
    with the same key as the installed copy, or it cannot be installed at all.
    There is no recovery if the key is lost — the app can only be re-released
    under a different applicationId, orphaning every install.

    So this script is run once, by you, and the outputs go three places:

      1. The keystore file and its passwords -> your password manager.
      2. Base64 of the keystore + the passwords -> GitHub repository secrets,
         so .github/workflows/android-release.yml can sign.
      3. The SHA-1 -> the Google Cloud OAuth client (Google Sign-In).
         The SHA-256 -> ANDROID_CERT_FINGERPRINTS on the server (App Links).

    Nothing it produces is written into the repository. See docs/ANDROID.md.

.EXAMPLE
    .\scripts\new-android-keystore.ps1
    .\scripts\new-android-keystore.ps1 -OutFile "$HOME\keys\traxjourney-release.jks"
#>
param(
    [string]$OutFile = "$HOME\.android-keys\traxjourney-release.jks",
    [string]$Alias = 'traxjourney',
    # 100 years: the key must outlive every release it will ever sign.
    [int]$ValidityDays = 36500
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Step([string]$msg) { Write-Host "`n>> $msg" -ForegroundColor Cyan }
function Die([string]$msg) { Write-Host "`nERROR: $msg" -ForegroundColor Red; exit 1 }

$keytool = Get-Command keytool -ErrorAction SilentlyContinue
if (-not $keytool) {
    if ($env:JAVA_HOME -and (Test-Path (Join-Path $env:JAVA_HOME 'bin\keytool.exe'))) {
        $keytool = Join-Path $env:JAVA_HOME 'bin\keytool.exe'
    } else {
        Die 'keytool not found. Install a JDK, or add its bin directory to PATH.'
    }
} else {
    $keytool = $keytool.Source
}

if (Test-Path $OutFile) {
    Die "$OutFile already exists. Refusing to overwrite a signing key — if you truly want a new one, move the old file aside first (and know that it orphans every existing install)."
}

# A keystore committed by accident is a keystore that has to be replaced.
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dir = Split-Path -Parent $OutFile
if (-not $dir) { $dir = (Get-Location).Path }
$fullDir = [IO.Path]::GetFullPath($dir)
if ($fullDir.StartsWith($repoRoot, [StringComparison]::OrdinalIgnoreCase)) {
    Die "Refusing to write the keystore inside the repository ($fullDir). Pass -OutFile with a path outside $repoRoot."
}
if (-not (Test-Path $fullDir)) { New-Item -ItemType Directory -Path $fullDir | Out-Null }

Step "Creating $OutFile"
Write-Host '   keytool will now prompt for a keystore password and your details.' -ForegroundColor DarkGray
Write-Host '   Store the password somewhere you will still have it in five years.' -ForegroundColor DarkGray

& $keytool -genkeypair -v `
    -keystore $OutFile `
    -alias $Alias `
    -keyalg RSA -keysize 4096 `
    -validity $ValidityDays
if ($LASTEXITCODE -ne 0) { Die 'keytool failed.' }

Step 'Certificate fingerprints'
& $keytool -list -v -keystore $OutFile -alias $Alias |
    Select-String -Pattern 'SHA1:|SHA256:'

Step 'Base64 of the keystore (GitHub secret ANDROID_KEYSTORE_BASE64)'
$b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($OutFile))
$clip = Join-Path ([IO.Path]::GetTempPath()) 'android-keystore-base64.txt'
Set-Content -Path $clip -Value $b64 -NoNewline
Write-Host "   Written to $clip — paste its contents into the secret, then delete it." -ForegroundColor DarkGray

Write-Host @"

Next steps (docs/ANDROID.md has the detail):

  1. GitHub -> Settings -> Secrets and variables -> Actions:
       ANDROID_KEYSTORE_BASE64   the file above
       ANDROID_KEY_ALIAS         $Alias
       ANDROID_KEYSTORE_PASSWORD the keystore password you just chose
       ANDROID_KEY_PASSWORD      the key password (same, unless you changed it)

  2. Google Cloud console -> Credentials -> Create OAuth client -> Android:
       package name  com.traxjourney.app
       SHA-1         the SHA1 printed above
     Without this, Google Sign-In fails on device.

  3. Server .env:  ANDROID_CERT_FINGERPRINTS=<the SHA256 printed above>
     then redeploy, so /.well-known/assetlinks.json serves and App Links verify.

  4. Local release builds: create flutter_client/android/key.properties
     (gitignored) with storeFile / storePassword / keyAlias / keyPassword.

"@ -ForegroundColor Green
