/// Web implementation of [StravaOAuthPopup] — opens the Strava OAuth flow in
/// a popup window and listens for the `postMessage` result sent by
/// `web/oauth_callback.html` once the OAuth redirect completes.
///
/// Message format from oauth_callback.html: `"strava_oauth:connected"` or
/// `"strava_oauth:error[:reason]"`.
library;

import 'dart:async';
import 'dart:js_interop';

import 'package:web/web.dart' as web;

/// Outcome of a Strava OAuth popup flow.
typedef StravaOAuthResult = ({bool connected, String? reason});

class StravaOAuthPopup {
  JSFunction? _messageHandler;

  /// Opens [url] in a popup and resolves once `web/oauth_callback.html`
  /// posts back the OAuth result. Removes the listener and closes the popup
  /// before resolving.
  Future<StravaOAuthResult> connect(String url) {
    dispose(); // Remove any stale listener from a previous attempt.

    final popup = web.window.open(
      url,
      'strava_oauth',
      'width=600,height=700,left=200,top=100',
    );

    final completer = Completer<StravaOAuthResult>();

    // Must store as a JSFunction field so the same reference can be removed.
    _messageHandler = (web.Event event) {
      final msg = event as web.MessageEvent;
      if (msg.origin != web.window.origin) return;
      final raw = msg.data?.toString() ?? '';
      if (!raw.startsWith('strava_oauth:')) return;

      dispose();
      popup?.close();

      final parts = raw.split(':');
      final status = parts.length > 1 ? parts[1] : 'error';
      final reason = parts.length > 2 ? parts.sublist(2).join(':') : '';

      if (!completer.isCompleted) {
        completer.complete((
          connected: status == 'connected',
          reason: reason.isNotEmpty ? reason : null,
        ));
      }
    }.toJS;

    web.window.addEventListener('message', _messageHandler!);

    return completer.future;
  }

  /// Removes any pending message listener. Safe to call even if [connect]
  /// was never invoked or has already settled.
  void dispose() {
    if (_messageHandler != null) {
      web.window.removeEventListener('message', _messageHandler!);
      _messageHandler = null;
    }
  }
}
