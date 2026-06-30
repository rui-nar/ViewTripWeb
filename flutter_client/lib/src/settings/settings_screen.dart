import 'dart:js_interop';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:web/web.dart' as web;

import '../auth/auth_notifier.dart';
import '../auth/auth_service.dart';
import '../crypto/enable_encryption_screen.dart';
import '../crypto/encryption.dart';
import '../crypto/manage_devices_screen.dart';
import '../crypto/recover_screen.dart';
import 'settings_service.dart';
import 'theme_notifier.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _service = SettingsService();

  // ── Strava state ──────────────────────────────────────────────────────────
  bool _stravaConnected = false;
  bool _stravaLoading = false;
  JSFunction? _stravaMessageHandler;

  // ── Polarsteps state ──────────────────────────────────────────────────────
  bool _polarstepsConnected = false;
  String? _polarstepsUsername;
  bool _polarstepsLoading = false;
  bool _polarstepsConnecting = false;
  bool _polarstepsUpdating = false; // reveal token field while already connected
  final _polarstepsTokenCtrl = TextEditingController();

  // ── Backup state ──────────────────────────────────────────────────────────
  List<Map<String, dynamic>> _backups = [];
  bool _backupsLoading = false;
  String? _restoringDate;

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
      _loadPolarstepsStatus();
      _loadProfile();
      _loadBackups();
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
    _polarstepsTokenCtrl.dispose();
    super.dispose();
  }

  // ── Profile ───────────────────────────────────────────────────────────────

  Future<void> _loadProfile() async {
    try {
      final data = await _service.getProfile();
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
      final result = await _service.updateProfile(name);
      if (result.token != null) {
        await AuthService().persistToken(result.token!);
        auth.updateUser(result.user);
      }
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Profile saved')),
        );
      }
    } on Exception catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Save failed: ${e.toString().replaceFirst('Exception: ', '')}')),
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
      await _service.changePassword(current: current, next: next);
      _currentPwCtrl.clear();
      _newPwCtrl.clear();
      _confirmPwCtrl.clear();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Password changed')),
        );
      }
    } on Exception catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e.toString().replaceFirst('Exception: ', ''))),
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
      await _service.deleteAccount();
      await auth.logout();
      router.go('/login');
    } on Exception catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Delete failed: ${e.toString().replaceFirst('Exception: ', '')}')),
        );
      }
    }
  }

  // ── Strava ────────────────────────────────────────────────────────────────

  Future<void> _loadStravaStatus() async {
    if (!mounted) return;
    setState(() => _stravaLoading = true);
    try {
      final connected = await _service.getStravaStatus();
      if (mounted) setState(() => _stravaConnected = connected);
    } catch (_) {
      // status not critical
    } finally {
      if (mounted) setState(() => _stravaLoading = false);
    }
  }

  Future<void> _connectStrava() async {
    try {
      final urlStr = await _service.getStravaConnectUrl();

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
      await _service.disconnectStrava();
      if (mounted) setState(() => _stravaConnected = false);
    } catch (_) {}
  }

  // ── Polarsteps ────────────────────────────────────────────────────────────

  Future<void> _loadPolarstepsStatus() async {
    if (!mounted) return;
    setState(() => _polarstepsLoading = true);
    try {
      final data = await _service.getPolarstepsStatus();
      if (mounted) {
        setState(() {
          _polarstepsConnected = data['connected'] == true;
          _polarstepsUsername = data['username'] as String?;
        });
      }
    } catch (_) {
      // status not critical
    } finally {
      if (mounted) setState(() => _polarstepsLoading = false);
    }
  }

  Future<void> _connectPolarsteps() async {
    final token = _polarstepsTokenCtrl.text.trim();
    if (token.isEmpty) return;
    setState(() => _polarstepsConnecting = true);
    try {
      final data = await _service.connectPolarsteps(token);
      if (mounted) {
        setState(() {
          _polarstepsConnected = true;
          _polarstepsUpdating = false;
          _polarstepsUsername = data['username'] as String?;
          _polarstepsTokenCtrl.clear();
        });
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Polarsteps connected!')),
        );
      }
    } on Exception catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e.toString().replaceFirst('Exception: ', ''))),
        );
      }
    } finally {
      if (mounted) setState(() => _polarstepsConnecting = false);
    }
  }

  Future<void> _disconnectPolarsteps() async {
    try {
      await _service.disconnectPolarsteps();
      if (mounted) {
        setState(() {
          _polarstepsConnected = false;
          _polarstepsUsername = null;
        });
      }
    } catch (_) {}
  }

  // ── Backups ───────────────────────────────────────────────────────────────

  Future<void> _loadBackups() async {
    if (!mounted) return;
    setState(() => _backupsLoading = true);
    try {
      final data = await _service.listBackups();
      if (mounted) setState(() => _backups = data);
    } catch (_) {
    } finally {
      if (mounted) setState(() => _backupsLoading = false);
    }
  }

  Future<void> _restoreBackup(String date) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Restore backup?'),
        content: Text(
          'This will replace the entire database with the backup from $date. '
          'The app will reload after the restore.',
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
            child: const Text('Restore'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _restoringDate = date);
    try {
      await _service.restoreBackup(date);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Restore complete — reloading…')),
        );
        // Force a full page reload so Flutter re-fetches everything from the restored DB.
        web.window.location.reload();
      }
    } on Exception catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Restore failed: ${e.toString().replaceFirst('Exception: ', '')}')),
        );
      }
    } finally {
      if (mounted) setState(() => _restoringDate = null);
    }
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
                  child: _polarstepsLoading
                      ? const Padding(
                          padding: EdgeInsets.symmetric(vertical: 8),
                          child: Center(child: CircularProgressIndicator()),
                        )
                      : Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            if (_polarstepsConnected) ...[
                              Row(
                                children: [
                                  Icon(Icons.check_circle,
                                      color: theme.colorScheme.primary,
                                      size: 18),
                                  const SizedBox(width: 8),
                                  Expanded(
                                    child: Text(
                                      _polarstepsUsername != null
                                          ? 'Connected as @$_polarstepsUsername'
                                          : 'Connected',
                                      style: theme.textTheme.bodyMedium,
                                    ),
                                  ),
                                  TextButton(
                                    onPressed: () => setState(() =>
                                        _polarstepsUpdating = !_polarstepsUpdating),
                                    child: Text(_polarstepsUpdating
                                        ? 'Cancel'
                                        : 'Update token'),
                                  ),
                                  TextButton(
                                    onPressed: _disconnectPolarsteps,
                                    child: const Text('Disconnect'),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 4),
                              if (_polarstepsUpdating) ...[
                                Text(
                                  'Paste a fresh remember_token if your session expired '
                                  '(no need to disconnect first).',
                                  style: theme.textTheme.bodySmall?.copyWith(
                                    color: theme.colorScheme.onSurfaceVariant,
                                  ),
                                ),
                                const SizedBox(height: 12),
                                TextField(
                                  controller: _polarstepsTokenCtrl,
                                  decoration: const InputDecoration(
                                    labelText: 'remember_token',
                                    hintText: 'Paste cookie value here…',
                                    border: OutlineInputBorder(),
                                    isDense: true,
                                  ),
                                  obscureText: true,
                                ),
                                const SizedBox(height: 12),
                                FilledButton(
                                  onPressed: _polarstepsConnecting
                                      ? null
                                      : _connectPolarsteps,
                                  child: _polarstepsConnecting
                                      ? const SizedBox(
                                          width: 16,
                                          height: 16,
                                          child: CircularProgressIndicator(
                                              strokeWidth: 2,
                                              color: Colors.white),
                                        )
                                      : const Text('Update token'),
                                ),
                              ] else
                                Text(
                                  'Open a project and use the Import button in the toolbar to import Polarsteps memories.',
                                  style: theme.textTheme.bodySmall,
                                ),
                            ] else ...[
                              Text(
                                'Connect your Polarsteps account to import steps as memories.',
                                style: theme.textTheme.bodySmall,
                              ),
                              const SizedBox(height: 4),
                              Text(
                                'In your browser: DevTools → Application → Cookies → polarsteps.com → copy the remember_token value.',
                                style: theme.textTheme.bodySmall?.copyWith(
                                  color: theme.colorScheme.onSurfaceVariant,
                                ),
                              ),
                              const SizedBox(height: 12),
                              TextField(
                                controller: _polarstepsTokenCtrl,
                                decoration: const InputDecoration(
                                  labelText: 'remember_token',
                                  hintText: 'Paste cookie value here…',
                                  border: OutlineInputBorder(),
                                  isDense: true,
                                ),
                                obscureText: true,
                              ),
                              const SizedBox(height: 12),
                              FilledButton(
                                onPressed: _polarstepsConnecting
                                    ? null
                                    : _connectPolarsteps,
                                child: _polarstepsConnecting
                                    ? const SizedBox(
                                        width: 16,
                                        height: 16,
                                        child: CircularProgressIndicator(
                                            strokeWidth: 2,
                                            color: Colors.white),
                                      )
                                    : const Text('Connect Polarsteps'),
                              ),
                            ],
                          ],
                        ),
                ),

                const SizedBox(height: 16),

                // ── Backups ────────────────────────────────────────────
                _SectionCard(
                  title: 'Backups',
                  icon: Icons.history_outlined,
                  child: _backupsLoading
                      ? const Padding(
                          padding: EdgeInsets.symmetric(vertical: 8),
                          child: Center(child: CircularProgressIndicator()),
                        )
                      : _backups.isEmpty
                          ? Text(
                              'No backups yet. The first backup will be created automatically at 02:00 UTC.',
                              style: theme.textTheme.bodySmall,
                            )
                          : Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                Text(
                                  'Daily backups are kept for 30 days. Restoring replaces the entire database.',
                                  style: theme.textTheme.bodySmall,
                                ),
                                const SizedBox(height: 12),
                                ..._backups.map((b) {
                                  final date = b['date'] as String;
                                  final bytes = b['size_bytes'] as int;
                                  final sizeLabel = bytes < 1024 * 1024
                                      ? '${(bytes / 1024).toStringAsFixed(0)} KB'
                                      : '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
                                  final isRestoring = _restoringDate == date;
                                  return Padding(
                                    padding: const EdgeInsets.only(bottom: 6),
                                    child: Row(
                                      children: [
                                        Expanded(
                                          child: Column(
                                            crossAxisAlignment: CrossAxisAlignment.start,
                                            children: [
                                              Text(date, style: theme.textTheme.bodyMedium),
                                              Text(sizeLabel, style: theme.textTheme.bodySmall),
                                            ],
                                          ),
                                        ),
                                        isRestoring
                                            ? const SizedBox(
                                                width: 20,
                                                height: 20,
                                                child: CircularProgressIndicator(strokeWidth: 2),
                                              )
                                            : TextButton(
                                                onPressed: _restoringDate != null
                                                    ? null
                                                    : () => _restoreBackup(date),
                                                child: const Text('Restore'),
                                              ),
                                      ],
                                    ),
                                  );
                                }),
                              ],
                            ),
                ),

                const SizedBox(height: 16),

                // ── Encryption ─────────────────────────────────────────
                _SectionCard(
                  title: 'Encryption',
                  icon: Icons.lock_outline,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Lock your memories and journal with a key only you hold — '
                        'so not even an administrator can read them.',
                        style: theme.textTheme.bodySmall,
                      ),
                      const SizedBox(height: 16),
                      FilledButton.icon(
                        onPressed: () {
                          Navigator.of(context).push(MaterialPageRoute(
                            builder: (_) =>
                                EnableEncryptionScreen(service: encryption),
                          ));
                        },
                        icon: const Icon(Icons.lock_outline),
                        label: const Text('Set up encryption'),
                      ),
                      const SizedBox(height: 8),
                      TextButton.icon(
                        onPressed: () {
                          Navigator.of(context).push(MaterialPageRoute(
                            builder: (_) =>
                                ManageDevicesScreen(service: encryption),
                          ));
                        },
                        icon: const Icon(Icons.devices_other),
                        label: const Text('Approve another device'),
                      ),
                      TextButton.icon(
                        onPressed: () {
                          Navigator.of(context).push(MaterialPageRoute(
                            builder: (_) => RecoverScreen(service: encryption),
                          ));
                        },
                        icon: const Icon(Icons.lock_open),
                        label: const Text('Recover access'),
                      ),
                    ],
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
