#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Bump the minor version, commit, tag, and create a GitHub release.

.DESCRIPTION
    1. Reads the current version from flutter_client/pubspec.yaml (e.g. 0.18.0+1).
    2. Increments the minor component and resets patch to 0 (e.g. 0.19.0+1).
    3. Updates pubspec.yaml.
    4. Commits the change and pushes to origin/main.
    5. Creates an annotated git tag (e.g. v0.19.0) and pushes it.
    6. Creates a GitHub release with auto-generated notes from commits since
       the previous tag.

.PREREQUISITES
    - gh CLI installed and authenticated (gh auth login).
    - git configured with push access to origin.

.EXAMPLE
    .\bump_version_and_release.ps1
    .\bump_version_and_release.ps1 -DryRun
#>
param(
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$PUBSPEC = Join-Path $PSScriptRoot "flutter_client\pubspec.yaml"

function Die([string]$msg) {
    Write-Host ""
    Write-Host "ERROR: $msg" -ForegroundColor Red
    exit 1
}

function Step([string]$msg) {
    Write-Host ""
    Write-Host ">> $msg" -ForegroundColor Cyan
}

# ── 1. Read and parse current version ─────────────────────────────────────────
Step "Reading current version from pubspec.yaml"

$pubspecContent = Get-Content $PUBSPEC -Raw
if ($pubspecContent -notmatch '(?m)^version:\s*(\d+)\.(\d+)\.(\d+)\+(\d+)') {
    Die "Could not parse 'version: X.Y.Z+N' from pubspec.yaml"
}
$major = [int]$Matches[1]
$minor = [int]$Matches[2]
# $patch and $build are captured but we reset patch and keep build
$build = [int]$Matches[4]

$oldVersion = "$major.$minor.$($Matches[3])+$build"
$newMinor   = $minor + 1
$newVersion = "$major.$newMinor.0+$build"
$oldTag     = "v$major.$minor.$($Matches[3])"
$newTag     = "v$major.$newMinor.0"

Write-Host "  $oldVersion  ->  $newVersion  (tag: $oldTag -> $newTag)"

if ($DryRun) {
    Write-Host ""
    Write-Host "[DryRun] No changes made." -ForegroundColor Yellow
    exit 0
}

# ── 2. Ensure working tree is clean ───────────────────────────────────────────
Step "Checking working tree"
$status = git status --porcelain 2>&1
# Allow only pubspec.yaml being modified (edge case: re-run after partial failure)
$dirty = $status | Where-Object { $_ -notmatch '^\s*M\s+flutter_client/pubspec\.yaml' }
if ($dirty) {
    Write-Host "  Uncommitted changes detected:" -ForegroundColor Yellow
    $dirty | ForEach-Object { Write-Host "    $_" }
    Die "Commit or stash your changes before bumping the version."
}

# ── 3. Collect commit log since last tag (for release notes) ──────────────────
Step "Collecting commits since $oldTag"
git fetch --tags | Out-Null
$commits = git log "$oldTag..HEAD" --pretty=format:"- %s" 2>&1
if (-not $commits) { $commits = "- No new commits since $oldTag" }
$releaseBody = "## What's changed`n`n$($commits -join "`n")"
Write-Host $releaseBody

# ── 4. Update pubspec.yaml ────────────────────────────────────────────────────
Step "Updating pubspec.yaml to $newVersion"
$updated = $pubspecContent -replace "(?m)^(version:\s*)$([regex]::Escape($oldVersion))", "`${1}$newVersion"
Set-Content -Path $PUBSPEC -Value $updated -NoNewline

# ── 5. Commit ─────────────────────────────────────────────────────────────────
Step "Committing version bump"
git add $PUBSPEC
git commit -m "chore: bump version to $newTag"
if ($LASTEXITCODE -ne 0) { Die "git commit failed." }

# ── 6. Push commit ────────────────────────────────────────────────────────────
Step "Pushing commit to origin"
git push origin HEAD
if ($LASTEXITCODE -ne 0) { Die "git push failed." }

# ── 7. Create and push annotated tag ─────────────────────────────────────────
Step "Tagging $newTag"
git tag -a $newTag -m "Release $newTag"
if ($LASTEXITCODE -ne 0) { Die "git tag failed." }
git push origin $newTag
if ($LASTEXITCODE -ne 0) { Die "git push tag failed." }

# ── 8. Create GitHub release ──────────────────────────────────────────────────
Step "Creating GitHub release $newTag"
gh release create $newTag `
    --title "ViewTripWeb $newTag" `
    --notes $releaseBody
if ($LASTEXITCODE -ne 0) { Die "gh release create failed." }

Write-Host ""
Write-Host "═══════════════════════════════════════════" -ForegroundColor Green
Write-Host "  Released $newTag" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
