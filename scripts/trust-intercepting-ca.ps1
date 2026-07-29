<#
.SYNOPSIS
    Teach every installed JDK to trust a TLS-intercepting proxy's root CA, so
    Gradle and the Android SDK tools can reach the network again (issue #165).

.DESCRIPTION
    Antivirus products with "HTTPS scanning" (Avast, Kaspersky, ESET, BitDefender)
    and corporate TLS proxies work by terminating every TLS connection and
    re-signing it with their own root CA. Windows trusts that CA, so browsers and
    PowerShell keep working — but a JDK ships its own `cacerts` truststore, which
    does not contain it. Every JVM network call then fails with:

        javax.net.ssl.SSLHandshakeException: PKIX path building failed:
        unable to find valid certification path to requested target

    That breaks Gradle distribution downloads and all Maven resolution, and the
    error looks like a network or repository fault rather than an antivirus one,
    which is what makes it expensive to diagnose.

    Gradle alone can be fixed with a line in ~/.gradle/gradle.properties:

        systemProp.javax.net.ssl.trustStoreType=Windows-ROOT

    but nothing else reads that file, so sdkmanager, avdmanager and any `java -jar`
    still fail. This script fixes them all at once by importing the interceptor's
    CA into each JDK's cacerts.

    Re-run it after installing or updating a JDK: a JDK patch update lays down a
    fresh cacerts and silently loses the import.

    It is idempotent — already-trusted JDKs are reported and skipped.

    NOTE: this does not help Dart/Flutter (`flutter pub get`), which does not use
    the JDK truststore.

.PARAMETER CaSubjectMatch
    Substring matched against certificate subjects in the Windows root store.
    Defaults to Avast; pass your own for a different product or corporate proxy.

.PARAMETER JdkPath
    Extra JDK directories to include, beyond the auto-detected ones.

.PARAMETER DryRun
    Report what would change and exit without modifying anything.
    Does not require Administrator.

.EXAMPLE
    .\scripts\trust-intercepting-ca.ps1 -DryRun

.EXAMPLE
    # Run elevated: cacerts lives under Program Files.
    .\scripts\trust-intercepting-ca.ps1

.EXAMPLE
    .\scripts\trust-intercepting-ca.ps1 -CaSubjectMatch 'Kaspersky'
#>
param(
    [string]$CaSubjectMatch = 'Avast',
    [string[]]$JdkPath = @(),
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Step([string]$m) { Write-Host "`n>> $m" -ForegroundColor Cyan }
function Ok  ([string]$m) { Write-Host "   $m" -ForegroundColor Green }
function Warn([string]$m) { Write-Host "   $m" -ForegroundColor Yellow }
function Die ([string]$m) { Write-Host "`nERROR: $m" -ForegroundColor Red; exit 1 }

# The password on a stock JDK cacerts. Not a secret: it is the documented
# default and the file is world-readable inside the JDK.
$StorePass = 'changeit'
$Alias = 'intercepting-proxy-ca'

# ---------------------------------------------------------------- find the CA
Step "Looking for a '$CaSubjectMatch' root CA in the Windows trust store"

$cert = Get-ChildItem -Path Cert:\LocalMachine\Root, Cert:\CurrentUser\Root -ErrorAction SilentlyContinue |
    Where-Object { $_.Subject -like "*$CaSubjectMatch*" } |
    Sort-Object NotAfter -Descending |
    Select-Object -First 1

if (-not $cert) {
    Warn "No certificate matching '$CaSubjectMatch' found."
    Warn 'If HTTPS scanning is currently switched off, there is nothing to import'
    Warn 'and nothing to fix — that is the good state. Re-run this only if the'
    Warn 'PKIX error comes back.'
    exit 0
}

Ok "subject    : $($cert.Subject)"
Ok "thumbprint : $($cert.Thumbprint)"
Ok "expires    : $($cert.NotAfter)"

# ------------------------------------------------------- confirm interception
# The CA being installed does not prove scanning is active; it survives the
# feature being switched off. Check a live connection so the script reports the
# state that actually matters.
Step 'Checking whether TLS is currently being intercepted'
$intercepted = $false
try {
    $tcp = New-Object System.Net.Sockets.TcpClient('services.gradle.org', 443)
    $script:liveIssuer = $null
    $ssl = New-Object System.Net.Security.SslStream($tcp.GetStream(), $false,
        ({ param($sn, $c, $ch, $e) $script:liveIssuer = $c.Issuer; $true }))
    $ssl.AuthenticateAsClient('services.gradle.org')
    $ssl.Close(); $tcp.Close()
    if ($script:liveIssuer -like "*$CaSubjectMatch*") {
        $intercepted = $true
        Warn "INTERCEPTED - issuer is $($script:liveIssuer)"
    } else {
        Ok "not intercepted - issuer is $($script:liveIssuer)"
        Ok 'Importing anyway, so the JDKs are already prepared if it returns.'
    }
} catch {
    Warn "Could not probe services.gradle.org: $($_.Exception.Message)"
}

# -------------------------------------------------------------- find the JDKs
Step 'Locating installed JDKs'

$candidates = [System.Collections.Generic.List[string]]::new()
foreach ($p in $JdkPath) { $candidates.Add($p) }
if ($env:JAVA_HOME) { $candidates.Add($env:JAVA_HOME) }

foreach ($root in @(
    "$env:ProgramFiles\Microsoft",
    "$env:ProgramFiles\Eclipse Adoptium",
    "$env:ProgramFiles\Java",
    "$env:ProgramFiles\Amazon Corretto",
    "$env:ProgramFiles\Zulu",
    "$env:LOCALAPPDATA\Programs\Eclipse Adoptium"
)) {
    if (Test-Path $root) {
        Get-ChildItem $root -Directory -ErrorAction SilentlyContinue |
            Where-Object { Test-Path (Join-Path $_.FullName 'bin\keytool.exe') } |
            ForEach-Object { $candidates.Add($_.FullName) }
    }
}

# Android Studio ships a JBR that Gradle may be pointed at.
foreach ($jbr in @("$env:ProgramFiles\Android\Android Studio\jbr")) {
    if (Test-Path (Join-Path $jbr 'bin\keytool.exe')) { $candidates.Add($jbr) }
}

$jdks = $candidates |
    Where-Object { $_ -and (Test-Path (Join-Path $_ 'lib\security\cacerts')) } |
    ForEach-Object { (Resolve-Path $_).Path.TrimEnd('\') } |
    Sort-Object -Unique

if (-not $jdks) { Die 'No JDKs found. Pass one explicitly with -JdkPath.' }
foreach ($j in $jdks) { Ok $j }

# ------------------------------------------------------------------ elevation
$elevated = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $DryRun -and -not $elevated) {
    Die @'
Administrator rights are required: cacerts lives under Program Files.
Re-run from an elevated PowerShell, or use -DryRun to preview.
'@
}

# -------------------------------------------------------------------- import
$cerFile = Join-Path ([IO.Path]::GetTempPath()) "intercepting-ca-$($cert.Thumbprint).cer"
[IO.File]::WriteAllBytes($cerFile, $cert.RawData)

$imported = 0; $already = 0; $failed = 0
try {
    foreach ($jdk in $jdks) {
        Step (Split-Path $jdk -Leaf)
        $keytool = Join-Path $jdk 'bin\keytool.exe'
        $cacerts = Join-Path $jdk 'lib\security\cacerts'

        # -list exits non-zero when the alias is absent, which is not an error here.
        $existing = & $keytool -list -alias $Alias -keystore $cacerts -storepass $StorePass 2>&1
        if ($LASTEXITCODE -eq 0) {
            if ($existing -match [regex]::Escape($cert.Thumbprint.Insert(2,':'))) {
                Ok 'already trusted, up to date'; $already++; continue
            }
            Warn 'stale alias present, replacing'
            & $keytool -delete -alias $Alias -keystore $cacerts -storepass $StorePass 2>&1 | Out-Null
        }

        if ($DryRun) { Warn 'would import (dry run)'; continue }

        $out = & $keytool -importcert -noprompt -trustcacerts `
            -alias $Alias -file $cerFile -keystore $cacerts -storepass $StorePass 2>&1
        if ($LASTEXITCODE -eq 0) { Ok 'imported'; $imported++ }
        else { Warn "FAILED: $out"; $failed++ }
    }
} finally {
    Remove-Item $cerFile -Force -ErrorAction SilentlyContinue
}

# -------------------------------------------------------------------- verify
if (-not $DryRun -and $imported -gt 0) {
    Step 'Verifying a real HTTPS request from the JVM'
    $probe = Join-Path ([IO.Path]::GetTempPath()) 'TlsProbe.java'
    @'
public class TlsProbe {
  public static void main(String[] a) throws Exception {
    var c = (java.net.HttpURLConnection) java.net.URI
        .create("https://services.gradle.org/distributions/")
        .toURL().openConnection();
    c.setRequestMethod("HEAD");
    c.setConnectTimeout(20000); c.setReadTimeout(20000);
    System.out.println("HTTP " + c.getResponseCode());
  }
}
'@ | Set-Content -Path $probe -Encoding UTF8

    foreach ($jdk in $jdks) {
        $java = Join-Path $jdk 'bin\java.exe'
        $r = & $java $probe 2>&1 | Out-String
        if ($r -match 'HTTP 2\d\d') { Ok "$(Split-Path $jdk -Leaf): OK" }
        elseif ($r -match 'PKIX')   { Warn "$(Split-Path $jdk -Leaf): STILL FAILING (PKIX)" }
        else                        { Warn "$(Split-Path $jdk -Leaf): $($r.Trim() -split "`n" | Select-Object -First 1)" }
    }
    Remove-Item $probe -Force -ErrorAction SilentlyContinue
}

Step 'Summary'
Ok "imported: $imported   already trusted: $already   failed: $failed"
if ($DryRun) { Warn 'Dry run - nothing was modified.' }
if (-not $intercepted) {
    Ok 'TLS is not currently being intercepted, so builds should already work.'
}

# Explicit, so the exit code reports this script's outcome rather than that of
# the last keytool call -- `keytool -list` exits non-zero whenever the alias is
# simply absent, which is the normal first-run case and not a failure.
if ($failed -gt 0) { exit 1 }
exit 0
