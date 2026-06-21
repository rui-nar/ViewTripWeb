# Start Flutter web dev server (port 5500)
# Set MAPBOX_TOKEN in your environment or pass it as a parameter.
# -Perf runs a profile build with the frame-timing recorder + performance
#   overlay enabled (measure scroll/jank — see lib/src/core/perf_timing.dart).
param(
  [string]$MapboxToken = $env:MAPBOX_TOKEN,
  [string]$ApiBaseUrl = 'http://localhost:8000',
  [switch]$Perf
)
if (-not $MapboxToken) { Write-Error "MAPBOX_TOKEN not set"; exit 1 }
Set-Location "$PSScriptRoot\flutter_client"

# -Perf builds in profile mode (release-grade rendering, no debug-mode JIT/assert
# pollution) with the frame-timing recorder + overlay on. Point -ApiBaseUrl at a
# real instance to measure against a heavy production trip's data.
$perfArgs = @()
if ($Perf) { $perfArgs = @('--profile', '--dart-define=PERF_TIMING=true') }

flutter run -d chrome --web-port 5500 `
  --dart-define=API_BASE_URL=$ApiBaseUrl `
  --dart-define=MAPBOX_TOKEN=$MapboxToken `
  @perfArgs
