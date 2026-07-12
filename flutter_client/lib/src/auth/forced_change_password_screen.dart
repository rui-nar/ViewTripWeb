/// Blocking password-change screen shown when the account has
/// `password_change_required` (e.g. the seeded `admin` account, or a user whose
/// password an admin reset). The router keeps the user here until it's changed.
library;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../settings/settings_service.dart';
import 'auth_notifier.dart';
import 'auth_service.dart';
import 'password_rules.dart';

class ForcedChangePasswordScreen extends StatefulWidget {
  final SettingsService? service; // injectable for tests
  const ForcedChangePasswordScreen({super.key, this.service});

  @override
  State<ForcedChangePasswordScreen> createState() =>
      _ForcedChangePasswordScreenState();
}

class _ForcedChangePasswordScreenState
    extends State<ForcedChangePasswordScreen> {
  late final SettingsService _service = widget.service ?? SettingsService();
  final _current = TextEditingController();
  final _next = TextEditingController();
  final _confirm = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _current.dispose();
    _next.dispose();
    _confirm.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final err = changePasswordError(
        current: _current.text, next: _next.text, confirm: _confirm.text);
    if (err != null) {
      setState(() => _error = err);
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final result = await _service.changePassword(
          current: _current.text, next: _next.text);
      // The old token still carries password_change_required=true as a baked-in
      // claim, so a stale-token refetch of /me would never see it clear. Store
      // the fresh token the server just issued instead; the router redirect
      // then re-evaluates against the current user and lets the user through.
      if (result.token != null) {
        await AuthService().persistToken(result.token!);
      }
      if (!mounted) return;
      context.read<AuthNotifier>().updateUser(result.user);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Change your password'),
        actions: [
          TextButton(
            onPressed: () => context.read<AuthNotifier>().logout(),
            child: const Text('Sign out'),
          ),
        ],
      ),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: ListView(
              padding: const EdgeInsets.all(20),
              children: [
                Text(
                  'You must set a new password before continuing.',
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                const SizedBox(height: 20),
                TextField(
                  controller: _current,
                  obscureText: true,
                  decoration: const InputDecoration(
                    labelText: 'Current password',
                    border: OutlineInputBorder(),
                    isDense: true,
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _next,
                  obscureText: true,
                  decoration: const InputDecoration(
                    labelText: 'New password',
                    border: OutlineInputBorder(),
                    isDense: true,
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _confirm,
                  obscureText: true,
                  onSubmitted: (_) => _submit(),
                  decoration: const InputDecoration(
                    labelText: 'Confirm new password',
                    border: OutlineInputBorder(),
                    isDense: true,
                  ),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Text(_error!,
                      style: TextStyle(
                          color: Theme.of(context).colorScheme.error)),
                ],
                const SizedBox(height: 20),
                FilledButton(
                  onPressed: _busy ? null : _submit,
                  child: _busy
                      ? const SizedBox(
                          height: 18,
                          width: 18,
                          child: CircularProgressIndicator(strokeWidth: 2))
                      : const Text('Change password'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
