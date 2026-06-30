/// Enable-encryption flow (issue #26): generate the CMK and let the user pick a
/// recovery method with honest, side-by-side tradeoffs.
///
/// DRAFT COPY: the intro text, the Option B security questions, and the
/// "weaker" warning wording below are placeholders for review — the product
/// owner should finalize the question set and copy. The structure/behaviour is
/// final; only the strings are provisional.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/design_tokens.dart';
import 'encryption_service.dart';

/// DRAFT — security questions offered for Option B. Finalize before release.
const List<String> kDraftSecurityQuestions = [
  'What was the name of your first pet?',
  'What city were you born in?',
  'What was the name of your primary school?',
];

enum _Step { choose, showRecoveryKey, done }

class EnableEncryptionScreen extends StatefulWidget {
  final EncryptionService service;
  const EnableEncryptionScreen({super.key, required this.service});

  @override
  State<EnableEncryptionScreen> createState() => _EnableEncryptionScreenState();
}

class _EnableEncryptionScreenState extends State<EnableEncryptionScreen> {
  _Step _step = _Step.choose;
  bool _useRecoveryKey = true; // Option A by default (stronger)
  bool _busy = false;
  bool _savedConfirmed = false;
  String? _recoveryKeyText;

  final _answers =
      List<TextEditingController>.generate(kDraftSecurityQuestions.length, (_) => TextEditingController());

  @override
  void dispose() {
    for (final c in _answers) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _enable() async {
    setState(() => _busy = true);
    try {
      final choice = _useRecoveryKey
          ? const RecoveryKeyChoice()
          : QnaChoice(_answers.map((c) => c.text).toList());
      final result = await widget.service.enable(choice);
      if (!mounted) return;
      if (result.recoverySecret != null) {
        setState(() {
          _recoveryKeyText = _formatRecoveryKey(result.recoverySecret!);
          _step = _Step.showRecoveryKey;
        });
      } else {
        setState(() => _step = _Step.done);
      }
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
    final hex = bytes.map((b) => b.toRadixString(16).padLeft(2, '0').toUpperCase()).join();
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
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        // DRAFT intro copy.
        Text('When encryption is on, your memories, journal and trip names are '
            'locked with a key only you hold. Not even an administrator can read '
            'them. If you lose access, only your recovery method can restore it.',
            style: Theme.of(context).textTheme.bodyMedium),
        const SizedBox(height: 20),
        Text('Choose a recovery method',
            style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 12),
        _recoveryCard(
          selected: _useRecoveryKey,
          onTap: () => setState(() => _useRecoveryKey = true),
          icon: Icons.vpn_key,
          title: 'Recovery key  ·  Stronger',
          subtitle: 'We generate a one-time key. Save it somewhere safe — it '
              'cannot be recovered for you. Strongest protection.',
          accent: kSuccess,
        ),
        const SizedBox(height: 10),
        _recoveryCard(
          selected: !_useRecoveryKey,
          onTap: () => setState(() => _useRecoveryKey = false),
          icon: Icons.help_outline,
          title: 'Security questions  ·  Easier',
          subtitle: 'Answer a few questions instead of saving a key. Easier — '
              'but weaker.',
          accent: kWarning,
        ),
        if (!_useRecoveryKey) ...[
          const SizedBox(height: 12),
          _qnaWarning(context),
          const SizedBox(height: 8),
          for (var i = 0; i < kDraftSecurityQuestions.length; i++) ...[
            const SizedBox(height: 10),
            Text(kDraftSecurityQuestions[i],
                style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 4),
            TextField(
              controller: _answers[i],
              decoration: const InputDecoration(border: OutlineInputBorder()),
            ),
          ],
        ],
        const SizedBox(height: 24),
        FilledButton(
          onPressed: _busy || (!_useRecoveryKey && _answersIncomplete())
              ? null
              : _enable,
          child: _busy
              ? const SizedBox(
                  height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2))
              : const Text('Turn on encryption'),
        ),
      ],
    );
  }

  bool _answersIncomplete() => _answers.any((c) => c.text.trim().isEmpty);

  Widget _qnaWarning(BuildContext context) {
    // DRAFT warning copy.
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
            child: Text(
              'Easier, but weaker. Security answers can be guessed, so someone '
              'with access to the server has a chance of recovering your data. '
              'A recovery key is much safer.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
        ],
      ),
    );
  }

  Widget _recoveryCard({
    required bool selected,
    required VoidCallback onTap,
    required IconData icon,
    required String title,
    required String subtitle,
    required Color accent,
  }) {
    return InkWell(
      onTap: onTap,
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
            Icon(icon, color: accent),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title, style: Theme.of(context).textTheme.titleSmall),
                  const SizedBox(height: 4),
                  Text(subtitle, style: Theme.of(context).textTheme.bodySmall),
                ],
              ),
            ),
            if (selected) Icon(Icons.check_circle, color: accent, size: 20),
          ],
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
          onPressed: _savedConfirmed ? () => setState(() => _step = _Step.done) : null,
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
          Text('Encryption is on', style: Theme.of(context).textTheme.titleMedium),
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
