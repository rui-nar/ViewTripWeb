/// Enable-encryption flow (issue #26): generate the CMK and let the user pick a
/// security LEVEL, with honest, side-by-side tradeoffs.
///
/// DRAFT COPY: the intro text, the Option-B security questions, the warning
/// wording, and the hex recovery-key rendering below are placeholders for
/// review. The structure/behaviour is final; only the strings are provisional.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/client.dart';
import '../core/design_tokens.dart';
import 'encryption_migration.dart';
import 'encryption_service.dart';

/// DRAFT — security questions offered for the Medium level. Finalize before release.
const List<String> kDraftSecurityQuestions = [
  'What was the name of your first pet?',
  'What city were you born in?',
  'What was the name of your primary school?',
];

/// The three offered levels. Low is admin-recoverable (NOT zero-knowledge) and
/// depends on server escrow + email infra not yet built — surfaced but disabled.
enum SecurityLevel { low, medium, high }

enum _HighMethod { passphrase, recoveryKey }

enum _Step { choose, showRecoveryKey, done }

class EnableEncryptionScreen extends StatefulWidget {
  final EncryptionService service;

  /// Runs after encryption is enabled to encrypt existing entries. Defaults to
  /// the real migration; injectable so tests don't hit the network.
  final Future<void> Function(EncryptionService service)? onEnabled;

  const EnableEncryptionScreen({
    super.key,
    required this.service,
    this.onEnabled,
  });

  @override
  State<EnableEncryptionScreen> createState() => _EnableEncryptionScreenState();
}

class _EnableEncryptionScreenState extends State<EnableEncryptionScreen> {
  _Step _step = _Step.choose;
  SecurityLevel _level = SecurityLevel.high; // strongest by default
  _HighMethod _highMethod = _HighMethod.passphrase;
  bool _busy = false;
  bool _savedConfirmed = false;
  String? _recoveryKeyText;

  final _passphrase = TextEditingController();
  final _answers = List<TextEditingController>.generate(
      kDraftSecurityQuestions.length, (_) => TextEditingController());

  @override
  void dispose() {
    _passphrase.dispose();
    for (final c in _answers) {
      c.dispose();
    }
    super.dispose();
  }

  bool get _canEnable {
    switch (_level) {
      case SecurityLevel.low:
        return false; // backend not built yet
      case SecurityLevel.medium:
        return _answers.every((c) => c.text.trim().isNotEmpty);
      case SecurityLevel.high:
        return _highMethod == _HighMethod.recoveryKey ||
            _passphrase.text.trim().isNotEmpty;
    }
  }

  RecoveryChoice _choice() {
    switch (_level) {
      case SecurityLevel.medium:
        return QnaChoice(_answers.map((c) => c.text).toList());
      case SecurityLevel.high:
        return _highMethod == _HighMethod.passphrase
            ? PassphraseChoice(_passphrase.text)
            : const RecoveryKeyChoice();
      case SecurityLevel.low:
        throw StateError('Low tier is not available yet');
    }
  }

  Future<void> _enable() async {
    setState(() => _busy = true);
    try {
      final result = await widget.service.enable(_choice());
      // Encrypt any existing plaintext entries in the background (idempotent).
      final migrate = widget.onEnabled ??
          (s) async {
            await EncryptionMigration(api, s).run();
          };
      unawaited(migrate(widget.service).catchError((_) {}));
      if (!mounted) return;
      setState(() {
        if (result.recoverySecret != null) {
          _recoveryKeyText = _formatRecoveryKey(result.recoverySecret!);
          _step = _Step.showRecoveryKey;
        } else {
          _step = _Step.done;
        }
      });
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Couldn\'t enable encryption: $e')),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// DRAFT rendering: grouped uppercase hex. A BIP39 word phrase is the intended
  /// final format (needs a wordlist dependency) — tracked as a follow-up.
  String _formatRecoveryKey(List<int> bytes) {
    final hex = bytes
        .map((b) => b.toRadixString(16).padLeft(2, '0').toUpperCase())
        .join();
    final groups = <String>[];
    for (var i = 0; i < hex.length; i += 4) {
      groups.add(hex.substring(i, i + 4));
    }
    return groups.join('-');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Encrypt your data')),
      body: SafeArea(
        child: switch (_step) {
          _Step.choose => _buildChoose(context),
          _Step.showRecoveryKey => _buildRecoveryKey(context),
          _Step.done => _buildDone(context),
        },
      ),
    );
  }

  Widget _buildChoose(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(
            'When encryption is on, your memories, journal and trip names are '
            'locked with a key only you hold. Choose how much convenience you '
            'want to trade for privacy.',
            style: t.bodyMedium),
        const SizedBox(height: 20),
        Text('Choose a level', style: t.titleMedium),
        const SizedBox(height: 12),

        _levelCard(
          level: SecurityLevel.high,
          accent: kSuccess,
          title: 'High  ·  Strongest',
          subtitle: 'A passphrase or a generated recovery key only you hold. '
              'Not even an administrator can read your data.',
        ),
        const SizedBox(height: 10),
        _levelCard(
          level: SecurityLevel.medium,
          accent: kWarning,
          title: 'Medium  ·  Security questions',
          subtitle: 'Answer a few questions instead of holding a secret. '
              'Easier — but weaker.',
        ),
        const SizedBox(height: 10),
        _levelCard(
          level: SecurityLevel.low,
          accent: kAccent,
          title: 'Low  ·  Recoverable by email  (coming soon)',
          subtitle: 'Reset by email if you forget. Most convenient — but because '
              'we can recover it, an administrator could read it. Not yet available.',
          enabled: false,
        ),

        const SizedBox(height: 16),
        if (_level == SecurityLevel.high) _buildHighOptions(context),
        if (_level == SecurityLevel.medium) _buildMediumOptions(context),

        const SizedBox(height: 24),
        FilledButton(
          onPressed: _busy || !_canEnable ? null : _enable,
          child: _busy
              ? const SizedBox(
                  height: 18, width: 18,
                  child: CircularProgressIndicator(strokeWidth: 2))
              : const Text('Turn on encryption'),
        ),
      ],
    );
  }

  Widget _buildHighOptions(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SegmentedButton<_HighMethod>(
          segments: const [
            ButtonSegment(value: _HighMethod.passphrase, label: Text('Passphrase')),
            ButtonSegment(value: _HighMethod.recoveryKey, label: Text('Recovery key')),
          ],
          selected: {_highMethod},
          onSelectionChanged: (s) => setState(() => _highMethod = s.first),
        ),
        const SizedBox(height: 12),
        if (_highMethod == _HighMethod.passphrase)
          TextField(
            controller: _passphrase,
            obscureText: true,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(
              labelText: 'Passphrase',
              helperText: 'Use a long, memorable phrase. Case matters.',
              border: OutlineInputBorder(),
            ),
          )
        else
          Text(
            'We\'ll generate a one-time recovery key for you to save on the next '
            'screen.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
      ],
    );
  }

  Widget _buildMediumOptions(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _warningBanner(
          context,
          // DRAFT warning copy.
          'Easier, but weaker. Security answers can be guessed, so someone with '
          'access to the server has a chance of recovering your data. High is '
          'much safer.',
        ),
        for (var i = 0; i < kDraftSecurityQuestions.length; i++) ...[
          const SizedBox(height: 10),
          Text(kDraftSecurityQuestions[i], style: t.bodySmall),
          const SizedBox(height: 4),
          TextField(
            controller: _answers[i],
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(border: OutlineInputBorder()),
          ),
        ],
      ],
    );
  }

  Widget _warningBanner(BuildContext context, String text) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: kWarning.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.warning_amber_rounded, color: kWarning, size: 20),
          const SizedBox(width: 8),
          Expanded(
              child: Text(text, style: Theme.of(context).textTheme.bodySmall)),
        ],
      ),
    );
  }

  Widget _levelCard({
    required SecurityLevel level,
    required Color accent,
    required String title,
    required String subtitle,
    bool enabled = true,
  }) {
    final selected = _level == level && enabled;
    return Opacity(
      opacity: enabled ? 1 : 0.55,
      child: InkWell(
        onTap: enabled ? () => setState(() => _level = level) : null,
        borderRadius: BorderRadius.circular(10),
        child: Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(10),
            border: Border.all(
              color: selected ? accent : Theme.of(context).dividerColor,
              width: selected ? 2 : 1,
            ),
            color: selected ? accent.withValues(alpha: 0.06) : null,
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(selected ? Icons.check_circle : Icons.circle_outlined,
                  color: accent, size: 20),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: Theme.of(context).textTheme.titleSmall),
                    const SizedBox(height: 4),
                    Text(subtitle,
                        style: Theme.of(context).textTheme.bodySmall),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildRecoveryKey(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text('Save your recovery key',
            style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        const Text('This is shown once. Store it in a password manager or print '
            'it. Without it — and without a trusted device — your data cannot be '
            'recovered.'),
        const SizedBox(height: 16),
        SelectableText(
          _recoveryKeyText ?? '',
          style: monoStyle(fontSize: 15, letterSpacing: 0.5),
        ),
        const SizedBox(height: 12),
        OutlinedButton.icon(
          onPressed: () {
            Clipboard.setData(ClipboardData(text: _recoveryKeyText ?? ''));
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('Recovery key copied')),
            );
          },
          icon: const Icon(Icons.copy),
          label: const Text('Copy'),
        ),
        const SizedBox(height: 16),
        CheckboxListTile(
          contentPadding: EdgeInsets.zero,
          value: _savedConfirmed,
          onChanged: (v) => setState(() => _savedConfirmed = v ?? false),
          title: const Text("I've saved my recovery key somewhere safe"),
        ),
        const SizedBox(height: 8),
        FilledButton(
          onPressed:
              _savedConfirmed ? () => setState(() => _step = _Step.done) : null,
          child: const Text('Done'),
        ),
      ],
    );
  }

  Widget _buildDone(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.lock, color: kSuccess, size: 48),
          const SizedBox(height: 12),
          Text('Encryption is on',
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          const Text('Your data is now end-to-end encrypted.'),
          const SizedBox(height: 20),
          FilledButton(
            onPressed: () => Navigator.of(context).maybePop(true),
            child: const Text('Close'),
          ),
        ],
      ),
    );
  }
}
