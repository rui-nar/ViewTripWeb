/// Recover access on a device with no trusted key (#26, Phase 6): unlock with
/// the recovery key, passphrase, or security questions the user configured, then
/// re-trust this device so future sessions unlock automatically.
///
/// DRAFT COPY: question set + wording are placeholders for review.
library;

import 'package:flutter/material.dart';

import '../core/design_tokens.dart';
import 'e2ee_crypto.dart';
import 'enable_encryption_screen.dart' show kDraftSecurityQuestions;
import 'encryption_service.dart';

enum _Method { recoveryKey, passphrase, questions }

class RecoverScreen extends StatefulWidget {
  final EncryptionService service;
  const RecoverScreen({super.key, required this.service});

  @override
  State<RecoverScreen> createState() => _RecoverScreenState();
}

class _RecoverScreenState extends State<RecoverScreen> {
  _Method _method = _Method.recoveryKey;
  bool _busy = false;
  bool _done = false;
  String? _error;

  final _keyCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  final _answers = List<TextEditingController>.generate(
      kDraftSecurityQuestions.length, (_) => TextEditingController());

  @override
  void dispose() {
    _keyCtrl.dispose();
    _passCtrl.dispose();
    for (final c in _answers) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _unlock() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final ok = switch (_method) {
        _Method.recoveryKey => await _recoverWithKey(),
        _Method.passphrase =>
          await widget.service.recoverWithPassphrase(_passCtrl.text),
        _Method.questions => await widget.service
            .recoverWithQna(_answers.map((c) => c.text).toList()),
      };
      if (!mounted) return;
      setState(() {
        if (ok) {
          _done = true;
        } else {
          _error = "Couldn't unlock. Double-check what you entered and try again.";
        }
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<bool> _recoverWithKey() async {
    final bytes = parseRecoveryKeyHex(_keyCtrl.text);
    if (bytes == null) return false;
    return widget.service.recoverWithRecoveryKey(bytes);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Recover access')),
      body: SafeArea(child: _done ? _success(context) : _form(context)),
    );
  }

  Widget _form(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(
          'No trusted device is available. Unlock with the recovery method you '
          'set up. This device will then be trusted.',
          style: Theme.of(context).textTheme.bodyMedium,
        ),
        const SizedBox(height: 16),
        SegmentedButton<_Method>(
          segments: const [
            ButtonSegment(value: _Method.recoveryKey, label: Text('Key')),
            ButtonSegment(value: _Method.passphrase, label: Text('Passphrase')),
            ButtonSegment(value: _Method.questions, label: Text('Questions')),
          ],
          selected: {_method},
          onSelectionChanged: (s) => setState(() => _method = s.first),
        ),
        const SizedBox(height: 16),
        ..._inputs(context),
        if (_error != null) ...[
          const SizedBox(height: 12),
          Text(_error!, style: TextStyle(color: kAccent)),
        ],
        const SizedBox(height: 20),
        FilledButton(
          onPressed: _busy ? null : _unlock,
          child: _busy
              ? const SizedBox(
                  height: 18, width: 18,
                  child: CircularProgressIndicator(strokeWidth: 2))
              : const Text('Unlock'),
        ),
      ],
    );
  }

  List<Widget> _inputs(BuildContext context) {
    switch (_method) {
      case _Method.recoveryKey:
        return [
          TextField(
            controller: _keyCtrl,
            decoration: const InputDecoration(
              labelText: 'Recovery key',
              helperText: 'The code shown when you turned on encryption.',
              border: OutlineInputBorder(),
            ),
          ),
        ];
      case _Method.passphrase:
        return [
          TextField(
            controller: _passCtrl,
            obscureText: true,
            decoration: const InputDecoration(
              labelText: 'Passphrase', border: OutlineInputBorder()),
          ),
        ];
      case _Method.questions:
        return [
          for (var i = 0; i < kDraftSecurityQuestions.length; i++) ...[
            Text(kDraftSecurityQuestions[i],
                style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 4),
            TextField(
              controller: _answers[i],
              decoration: const InputDecoration(border: OutlineInputBorder()),
            ),
            const SizedBox(height: 10),
          ],
        ];
    }
  }

  Widget _success(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.lock_open, color: kSuccess, size: 48),
          const SizedBox(height: 12),
          Text('Access restored',
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          const Text('This device is now trusted.'),
          const SizedBox(height: 20),
          FilledButton(
            onPressed: () => Navigator.of(context).maybePop(true),
            child: const Text('Done'),
          ),
        ],
      ),
    );
  }
}
