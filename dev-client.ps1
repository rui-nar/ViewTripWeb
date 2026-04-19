# Start Flutter web dev server (port 5500)
# Set MAPBOX_TOKEN in your environment or pass it as a parameter.
param([string]$MapboxToken = $env:MAPBOX_TOKEN)
if (-not $MapboxToken) { Write-Error "MAPBOX_TOKEN not set"; exit 1 }
Set-Location "$PSScriptRoot\flutter_client"
flutter run -d chrome --web-port 5500 `
  --dart-define=API_BASE_URL=http://localhost:8000 `
  --dart-define=MAPBOX_TOKEN=$MapboxToken
