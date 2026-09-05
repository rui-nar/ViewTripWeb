/// The two version numbers the app can show: its own, baked in at build time,
/// and the server's, as reported by `GET /api/version` (issue #275).
///
/// Every place that shows a version shows both, in the same shape, so a bug
/// report never has to guess which half is which — a native app is routinely a
/// release or two behind the server it talks to, and a stale cached web bundle
/// is the whole reason [VersionGate] exists.
library;

import 'package:flutter/material.dart';

/// Set by `--dart-define=APP_VERSION` at build time; already carries its `v`
/// prefix from the release tag, so it is shown verbatim.
const kClientVersion =
    String.fromEnvironment('APP_VERSION', defaultValue: 'dev');

/// The server version last reported by `/api/version`.
///
/// `null` until a call succeeds — and it may legitimately stay null for the
/// whole session: offline, a server that is down, or a first frame that beats
/// the request home. Readers must render that case immediately rather than
/// wait, which is what [versionLabel] does. `VersionGate` is the sole writer;
/// nothing else should fetch the endpoint.
final ValueNotifier<String?> serverVersion = ValueNotifier<String?>(null);

/// One line naming both versions, e.g. `app v0.42.0 · server v0.42.0`.
///
/// An absent [server] reads as `server unknown` rather than collapsing to the
/// app version alone: a blank where the server version should be would read as
/// "there is no server", and a placeholder that spins would never resolve
/// offline. The two being equal is not called out — the stale-bundle bar owns
/// that story, and repeating it here would either duplicate or contradict it.
String versionLabel(String client, String? server) =>
    'app $client · server ${server == null || server.isEmpty ? 'unknown' : server}';

/// [versionLabel] for the running build, re-rendered when the server version
/// arrives. [prefix] is prepended verbatim (e.g. `'© 2026 ViewTrip · '`).
class VersionText extends StatelessWidget {
  const VersionText({super.key, this.prefix = '', this.style, this.textAlign});

  final String prefix;
  final TextStyle? style;
  final TextAlign? textAlign;

  @override
  Widget build(BuildContext context) => ValueListenableBuilder<String?>(
        valueListenable: serverVersion,
        builder: (_, server, __) => Text(
          '$prefix${versionLabel(kClientVersion, server)}',
          style: style,
          textAlign: textAlign,
        ),
      );
}
