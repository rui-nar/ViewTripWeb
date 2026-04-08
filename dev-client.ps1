# Start Flutter web dev server (port 5500)
Set-Location "$PSScriptRoot\flutter_client"
flutter run -d chrome --web-port 5500 --dart-define=API_BASE_URL=http://localhost:8000
