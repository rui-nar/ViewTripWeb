import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/client.dart';
import 'theme_notifier.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  bool _stravaConnected = false;
  bool _stravaLoading = false;

  @override
  void initState() {
    super.initState();
    _loadStravaStatus();
    if (kIsWeb) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        final uri = Uri.base;
        final stravaParam = uri.queryParameters['strava'];
        if (stravaParam == 'connected') {
          _loadStravaStatus();
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Strava connected!')),
          );
        } else if (stravaParam == 'error') {
          final reason = uri.queryParameters['reason'] ?? '';
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(reason.isNotEmpty
                  ? 'Strava connection failed: $reason'
                  : 'Strava connection failed.'),
            ),
          );
        }
      });
    }
  }

  Future<void> _loadStravaStatus() async {
    if (!mounted) return;
    setState(() => _stravaLoading = true);
    try {
      final data = await api.get('/api/strava/status') as Map<String, dynamic>;
      if (mounted) setState(() => _stravaConnected = data['connected'] == true);
    } catch (_) {
      // status not critical
    } finally {
      if (mounted) setState(() => _stravaLoading = false);
    }
  }

  Future<void> _connectStrava() async {
    try {
      final data =
          await api.get('/api/strava/connect') as Map<String, dynamic>;
      final url = Uri.parse(data['url'] as String);
      await launchUrl(url, mode: LaunchMode.externalApplication);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not open Strava: $e')),
        );
      }
    }
  }

  Future<void> _disconnectStrava() async {
    try {
      await api.delete('/api/strava/disconnect');
      if (mounted) setState(() => _stravaConnected = false);
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final themeNotifier = context.watch<ThemeNotifier>();

    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // ── Appearance ────────────────────────────────────────────
                _SectionCard(
                  title: 'Appearance',
                  icon: Icons.palette_outlined,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Theme', style: theme.textTheme.bodySmall),
                      const SizedBox(height: 10),
                      SegmentedButton<ThemeMode>(
                        segments: const [
                          ButtonSegment(
                            value: ThemeMode.light,
                            icon: Icon(Icons.light_mode_outlined),
                            label: Text('Light'),
                          ),
                          ButtonSegment(
                            value: ThemeMode.system,
                            icon: Icon(Icons.brightness_auto_outlined),
                            label: Text('System'),
                          ),
                          ButtonSegment(
                            value: ThemeMode.dark,
                            icon: Icon(Icons.dark_mode_outlined),
                            label: Text('Dark'),
                          ),
                        ],
                        selected: {themeNotifier.mode},
                        onSelectionChanged: (s) =>
                            themeNotifier.setMode(s.first),
                        multiSelectionEnabled: false,
                      ),
                    ],
                  ),
                ),

                const SizedBox(height: 16),

                // ── Strava ────────────────────────────────────────────────
                _SectionCard(
                  title: 'Strava',
                  icon: Icons.directions_run,
                  child: _stravaLoading
                      ? const Padding(
                          padding: EdgeInsets.symmetric(vertical: 8),
                          child: Center(child: CircularProgressIndicator()),
                        )
                      : Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            if (_stravaConnected) ...[
                              Row(
                                children: [
                                  Icon(Icons.check_circle,
                                      color: theme.colorScheme.primary,
                                      size: 18),
                                  const SizedBox(width: 8),
                                  Text('Connected',
                                      style: theme.textTheme.bodyMedium),
                                  const Spacer(),
                                  TextButton(
                                    onPressed: _disconnectStrava,
                                    child: const Text('Disconnect'),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 4),
                              Text(
                                'Open a project and use the Import button in the toolbar to add Strava activities.',
                                style: theme.textTheme.bodySmall,
                              ),
                            ] else ...[
                              Text(
                                'Connect your Strava account to import activities into projects.',
                                style: theme.textTheme.bodySmall,
                              ),
                              const SizedBox(height: 16),
                              OutlinedButton.icon(
                                onPressed: _connectStrava,
                                icon: const Icon(Icons.link),
                                label: const Text('Connect Strava'),
                              ),
                            ],
                          ],
                        ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// ── Reusable section card ─────────────────────────────────────────────────────

class _SectionCard extends StatelessWidget {
  final String title;
  final IconData icon;
  final Widget child;

  const _SectionCard({
    required this.title,
    required this.icon,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, color: theme.colorScheme.primary, size: 20),
                const SizedBox(width: 8),
                Text(title, style: theme.textTheme.titleLarge),
              ],
            ),
            const Divider(height: 24),
            child,
          ],
        ),
      ),
    );
  }
}
