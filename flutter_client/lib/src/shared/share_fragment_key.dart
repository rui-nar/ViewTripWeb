/// Reads the per-share content key from the URL fragment (issue #28).
///
/// `go_router`'s `GoRouterState.uri` does not expose the URL fragment (it's
/// not part of standard web routing), so the fragment must be read directly
/// via `Uri.base.fragment` — mirrors the `kIsWeb` guard in
/// `core/app_router.dart`'s `_initialLocation()`. The key never reaches the
/// server: it's generated client-side, embedded only in the fragment (which
/// browsers never send in requests), and read back here on the viewer's side.
library;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:cryptography_plus/cryptography_plus.dart';

import '../crypto/share_crypto.dart';

/// Returns the share content key from the current URL's `#key=...` fragment,
/// or null when absent — the normal case for most viewers (e.g. the project
/// has no encrypted content, the owner never generated share content, or a
/// link-forwarding mechanism stripped the fragment). Also null on non-web
/// platforms and on a malformed key, since there is nothing useful to do
/// with either case beyond falling back to the "unavailable" viewer state.
SecretKey? readShareKeyFromUrlFragment() {
  if (!kIsWeb) return null;
  final fragment = Uri.base.fragment;
  if (fragment.isEmpty) return null;
  final params = Uri.splitQueryString(fragment);
  final encoded = params['key'];
  if (encoded == null || encoded.isEmpty) return null;
  try {
    return shareKeyFromBase64(encoded);
  } catch (_) {
    return null;
  }
}
