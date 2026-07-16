/// Non-web fallback for [StravaOAuthPopup].
///
/// The OAuth popup + postMessage handshake is a web-only flow — on other
/// platforms, `_connectStrava()` in settings_screen.dart takes the
/// `launchUrl()` branch instead and never calls into this class. It exists
/// only so `_SettingsScreenState` compiles under non-web platforms
/// (including `flutter test`'s VM platform).
library;

/// Outcome of a Strava OAuth popup flow.
typedef StravaOAuthResult = ({bool connected, String? reason});

class StravaOAuthPopup {
  Future<StravaOAuthResult> connect(String url) async =>
      (connected: false, reason: 'Strava OAuth popup is web-only');

  void dispose() {}
}
