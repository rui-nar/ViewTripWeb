import 'dart:js_interop';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:web/web.dart' as web;

import '../api/client.dart';
import '../auth/auth_notifier.dart';
import '../auth/auth_service.dart';
import 'theme_notifier.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  // ── Strava state ──────────────────────────────────────────────────────────
  bool _stravaConnected = false;
  bool _stravaLoading = false;
  JSFunction? _stravaMessageHandler;

  // ── Account state ─────────────────────────────────────────────────────────
  final _displayNameCtrl = TextEditingController();
  String _email = '';
  String _authProvider = 'local';
  bool _profileSaving = false;

  // Change-password state
  final _currentPwCtrl = TextEditingController();
  final _newPwCtrl = TextEditingController();
  final _confirmPwCtrl = TextEditingController();
  bool _pwChanging = false;
  bool _showCurrentPw = false;
  bool _showNewPw = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _loadStravaStatus();
      _loadProfile();
    });
  }

  @override
  void dispose() {
    if (_stravaMessageHandler != null) {
      web.window.removeEventListener('message', _stravaMessageHandler!);
      _stravaMessageHandler = null;
    }
    _displayNameCtrl.dispose();
    _currentPwCtrl.dispose();
    _newPwCtrl.dispose();
    _confirmPwCtrl.dispose();
    super.dispose();
  }

  // ── Profile ───────────────────────────────────────────────────────────────

  Future<void> _loadProfile() async {
    try {
      final data = await api.get('/api/auth/me') as Map<String, dynamic>;
      if (mounted) {
        setState(() {
          _displayNameCtrl.text = data['display_name'] as String? ?? '';
          _email = data['email'] as String? ?? '';
          _authProvider = data['auth_provider'] as String? ?? 'local';
        });
      }
    } catch (_) {}
  }

  Future<void> _saveProfile() async {
    final name = _displayNameCtrl.text.trim();
    if (name.isEmpty) return;
    setState(() => _profileSaving = true);
    final auth = context.read<AuthNotifier>();
    try {
      final data = await api.put('/api/auth/me', {'display_name': name})
          as Map<String, dynamic>;
      // Refresh the stored JWT so AuthNotifier reflects the new name.
      final token = data['access_token'] as String?;
      if (token != null) {
        await AuthService().persistToken(token);
        auth.updateUser(data['user'] as Map<String, dynamic>? ?? {});
      }
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Profile saved')),
        );
      }
    } on ApiException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Save failed: ${e.body}')),
        );
      }
    } finally {
      if (mounted) setState(() => _profileSaving = false);
    }
  }

  Future<void> _changePassword() async {
    final current = _currentPwCtrl.text;
    final next = _newPwCtrl.text;
    final confirm = _confirmPwCtrl.text;
    if (current.isEmpty || next.isEmpty) return;
    if (next != confirm) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('New passwords do not match')),
      );
      return;
    }
    setState(() => _pwChanging = true);
    try {
      await api.post('/api/auth/change-password', {
        'current_password': current,
        'new_password': next,
      });
      _currentPwCtrl.clear();
      _newPwCtrl.clear();
      _confirmPwCtrl.clear();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Password changed')),
        );
      }
    } on ApiException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(_extractDetail(e.body))),
        );
      }
    } finally {
      if (mounted) setState(() => _pwChanging = false);
    }
  }

  Future<void> _deleteAccount() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete account?'),
        content: const Text(
          'This will permanently delete your account and all projects. '
          'This cannot be undone.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Cancel'),
          ),
          TextButton(
            style: TextButton.styleFrom(
              foregroundColor: Theme.of(ctx).colorScheme.error,
            ),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    final auth = context.read<AuthNotifier>();
    final router = GoRouter.of(context);
    try {
      await api.delete('/api/auth/me');
      await auth.logout();
      router.go('/login');
    } on ApiException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Delete failed: ${e.body}')),
        );
      }
    }
  }

  // ── Strava ────────────────────────────────────────────────────────────────

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
      final urlStr = data['url'] as String;

      if (kIsWeb) {
        // Remove any stale listener from a previous attempt.
        if (_stravaMessageHandler != null) {
          web.window.removeEventListener('message', _stravaMessageHandler!);
          _stravaMessageHandler = null;
        }

        // Open OAuth in a popup. The popup redirects to oauth_callback.html
        // which postMessages the result back here, then closes itself.
        final popup = web.window.open(
          urlStr,
          'strava_oauth',
          'width=600,height=700,left=200,top=100',
        );

        // Listen for the postMessage from oauth_callback.html.
        // Message format: "strava_oauth:connected" or "strava_oauth:error[:reason]"
        // Must store as JSFunction field so the same reference can be removed.
        _stravaMessageHandler = (web.Event event) {
          final msg = event as web.MessageEvent;
          if (msg.origin != web.window.origin) return;
          final raw = msg.data?.toString() ?? '';
          if (!raw.startsWith('strava_oauth:')) return;

          web.window.removeEventListener('message', _stravaMessageHandler!);
          _stravaMessageHandler = null;
          popup?.close();

          final parts = raw.split(':');
          final status = parts.length > 1 ? parts[1] : 'error';
          final reason = parts.length > 2 ? parts.sublist(2).join(':') : '';

          if (!mounted) return;
          if (status == 'connected') {
            _loadStravaStatus();
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('Strava connected!')),
            );
          } else {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text(reason.isNotEmpty
                    ? 'Strava connection failed: $reason'
                    : 'Strava connection failed.'),
              ),
            );
          }
        }.toJS;

        web.window.addEventListener('message', _stravaMessageHandler!);
      } else {
        await launchUrl(Uri.parse(urlStr),
            mode: LaunchMode.externalApplication);
      }
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

  // ── Helpers ───────────────────────────────────────────────────────────────

  String _extractDetail(String body) {
    final m = RegExp(r'"detail"\s*:\s*"([^"]+)"').firstMatch(body);
    return m?.group(1) ?? body;
  }

  // ── Build ─────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final themeNotifier = context.watch<ThemeNotifier>();

    return Scaffold(
      appBar: AppBar(
        leading: BackButton(onPressed: () => context.pop()),
        title: const Text('Settings'),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // ── Appearance ─────────────────────────────────────────
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

                // ── Account ────────────────────────────────────────────
                _SectionCard(
                  title: 'Account',
                  icon: Icons.person_outlined,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      TextField(
                        controller: _displayNameCtrl,
                        decoration: const InputDecoration(
                          labelText: 'Display name',
                          border: OutlineInputBorder(),
                        ),
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        readOnly: true,
                        decoration: InputDecoration(
                          labelText: 'Email',
                          border: const OutlineInputBorder(),
                          filled: true,
                          fillColor: theme.colorScheme.surfaceContainerHighest
                              .withValues(alpha: 0.4),
                        ),
                        controller:
                            TextEditingController(text: _email),
                        style: TextStyle(
                            color: theme.colorScheme.onSurface
                                .withValues(alpha: 0.5)),
                      ),
                      const SizedBox(height: 16),
                      Align(
                        alignment: Alignment.centerRight,
                        child: FilledButton(
                          onPressed: _profileSaving ? null : _saveProfile,
                          child: _profileSaving
                              ? const SizedBox(
                                  width: 18,
                                  height: 18,
                                  child: CircularProgressIndicator(
                                      strokeWidth: 2))
                              : const Text('Save'),
                        ),
                      ),

                      // Change-password subsection (local accounts only)
                      if (_authProvider == 'local') ...[
                        const Divider(height: 32),
                        Text('Change password',
                            style: theme.textTheme.titleSmall),
                        const SizedBox(height: 12),
                        TextField(
                          controller: _currentPwCtrl,
                          obscureText: !_showCurrentPw,
                          decoration: InputDecoration(
                            labelText: 'Current password',
                            border: const OutlineInputBorder(),
                            suffixIcon: IconButton(
                              icon: Icon(_showCurrentPw
                                  ? Icons.visibility_off_outlined
                                  : Icons.visibility_outlined),
                              onPressed: () => setState(
                                  () => _showCurrentPw = !_showCurrentPw),
                            ),
                          ),
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: _newPwCtrl,
                          obscureText: !_showNewPw,
                          decoration: InputDecoration(
                            labelText: 'New password',
                            border: const OutlineInputBorder(),
                            suffixIcon: IconButton(
                              icon: Icon(_showNewPw
                                  ? Icons.visibility_off_outlined
                                  : Icons.visibility_outlined),
                              onPressed: () =>
                                  setState(() => _showNewPw = !_showNewPw),
                            ),
                          ),
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: _confirmPwCtrl,
                          obscureText: true,
                          decoration: const InputDecoration(
                            labelText: 'Confirm new password',
                            border: OutlineInputBorder(),
                          ),
                        ),
                        const SizedBox(height: 16),
                        Align(
                          alignment: Alignment.centerRight,
                          child: OutlinedButton(
                            onPressed: _pwChanging ? null : _changePassword,
                            child: _pwChanging
                                ? const SizedBox(
                                    width: 18,
                                    height: 18,
                                    child: CircularProgressIndicator(
                                        strokeWidth: 2))
                                : const Text('Change password'),
                          ),
                        ),
                      ],
                    ],
                  ),
                ),

                const SizedBox(height: 16),

                // ── Strava ─────────────────────────────────────────────
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

                const SizedBox(height: 16),

                // ── Polarsteps ─────────────────────────────────────────
                _SectionCard(
                  title: 'Polarsteps',
                  icon: Icons.explore_outlined,
                  child: Text(
                    'Polarsteps integration coming soon.',
                    style: theme.textTheme.bodySmall,
                  ),
                ),

                const SizedBox(height: 16),

                // ── Danger Zone ────────────────────────────────────────
                _SectionCard(
                  title: 'Danger Zone',
                  icon: Icons.warning_amber_outlined,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Permanently delete your account and all associated projects and data.',
                        style: theme.textTheme.bodySmall,
                      ),
                      const SizedBox(height: 16),
                      OutlinedButton(
                        style: OutlinedButton.styleFrom(
                          foregroundColor: theme.colorScheme.error,
                          side: BorderSide(color: theme.colorScheme.error),
                        ),
                        onPressed: _deleteAccount,
                        child: const Text('Delete my account'),
                      ),
                    ],
                  ),
                ),

                const SizedBox(height: 16),

                // ── About ──────────────────────────────────────────────
                _SectionCard(
                  title: 'About',
                  icon: Icons.info_outlined,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('ViewTripWeb',
                          style: theme.textTheme.titleMedium),
                      const SizedBox(height: 4),
                      const Text(
                        String.fromEnvironment('APP_VERSION', defaultValue: 'dev'),
                        style: TextStyle(
                          fontFamily: 'monospace',
                          fontSize: 12,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        '© ${DateTime.now().year} Rui Narciso. All rights reserved.',
                        style: theme.textTheme.bodySmall,
                      ),
                    ],
                  ),
                ),

                const SizedBox(height: 32),
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
