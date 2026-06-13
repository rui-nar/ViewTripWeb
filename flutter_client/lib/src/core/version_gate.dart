/// App-wide guard against stale cached web bundles.
///
/// A returning web user can be served an old `main.dart.js` from cache after a
/// deploy (the bug that surfaced as a wrong baked API URL). This widget compares
/// the client's build-time [APP_VERSION] against the server's `/api/version` and,
/// when they differ, shows a non-dismissable "new version available" bar with a
/// Reload button — turning a silent breakage into a one-tap refresh.
library;

import 'dart:async';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';

import '../api/client.dart';
import 'version_reload_stub.dart'
    if (dart.library.html) 'version_reload_web.dart';

/// True when the running client bundle is older/different than what the server
/// reports — i.e. the user is on a stale build and should reload.
///
/// Conservative on purpose: never fires when either side is missing or `dev`
/// (local builds), so it only triggers between two real, differing deployments.
bool isClientStale(String clientVersion, String serverVersion) {
  if (clientVersion.isEmpty || serverVersion.isEmpty) return false;
  if (clientVersion == 'dev' || serverVersion == 'dev') return false;
  return clientVersion != serverVersion;
}

class VersionGate extends StatefulWidget {
  final Widget child;
  const VersionGate({super.key, required this.child});

  @override
  State<VersionGate> createState() => _VersionGateState();
}

class _VersionGateState extends State<VersionGate> with WidgetsBindingObserver {
  static const _clientVersion =
      String.fromEnvironment('APP_VERSION', defaultValue: 'dev');

  bool _stale = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    // Only relevant on web — native apps update through their store, and the
    // page-reload action is a no-op there.
    if (kIsWeb) {
      WidgetsBinding.instance.addObserver(this);
      WidgetsBinding.instance.addPostFrameCallback((_) => _check());
      // Periodic re-check so a long-lived tab notices a deploy without a manual
      // reload; cheap (one tiny GET).
      _timer = Timer.periodic(const Duration(minutes: 15), (_) => _check());
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _check();
  }

  Future<void> _check() async {
    if (_stale || !mounted) return;
    try {
      final data = await api.get('/api/version') as Map<String, dynamic>;
      final serverVersion = (data['version'] as String?) ?? '';
      if (mounted && isClientStale(_clientVersion, serverVersion)) {
        setState(() => _stale = true);
      }
    } catch (_) {
      // Network blip — ignore; we'll try again on the next tick/resume.
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    if (kIsWeb) WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_stale) return widget.child;
    final scheme = Theme.of(context).colorScheme;
    return Stack(
      children: [
        widget.child,
        Positioned(
          left: 0,
          right: 0,
          bottom: 0,
          child: SafeArea(
            child: Material(
              color: scheme.inverseSurface,
              elevation: 6,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 10, 8, 10),
                child: Row(
                  children: [
                    Icon(Icons.system_update_alt,
                        size: 20, color: scheme.onInverseSurface),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        'A new version of ViewTrip is available.',
                        style: TextStyle(color: scheme.onInverseSurface),
                      ),
                    ),
                    TextButton(
                      onPressed: reloadApp,
                      child: Text(
                        'Reload',
                        style: TextStyle(
                          color: scheme.inversePrimary,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}
