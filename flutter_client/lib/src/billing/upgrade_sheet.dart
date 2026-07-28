/// The prompt a 402 turns into (issue #121).
///
/// Deliberately not an error dialog: hitting a plan limit is not a failure the
/// user caused, so the sheet leads with what they can do about it.
library;

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import 'billing_service.dart';

/// Sheet body. Split from [showUpgradeSheet] so widget tests can pump it
/// directly without a navigator or a live billing service.
class UpgradeSheet extends StatefulWidget {
  final QuotaError error;

  /// Returns the checkout URL to open. Injected in tests.
  final Future<String> Function() onUpgrade;

  /// Opens the checkout URL. Injected in tests.
  final Future<void> Function(String url)? launcher;

  const UpgradeSheet({
    super.key,
    required this.error,
    required this.onUpgrade,
    this.launcher,
  });

  @override
  State<UpgradeSheet> createState() => _UpgradeSheetState();
}

class _UpgradeSheetState extends State<UpgradeSheet> {
  bool _busy = false;
  String? _failure;

  Future<void> _upgrade() async {
    setState(() {
      _busy = true;
      _failure = null;
    });
    try {
      final url = await widget.onUpgrade();
      if (url.isEmpty) throw Exception('empty checkout url');
      final launch = widget.launcher ??
          (String u) async => launchUrl(Uri.parse(u),
              mode: LaunchMode.externalApplication);
      await launch(url);
      if (mounted) Navigator.of(context).maybePop();
    } catch (_) {
      if (mounted) {
        setState(() => _failure = 'Could not start checkout. Please try again.');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isStorage = widget.error.resource == 'storage';

    return Padding(
      padding: EdgeInsets.fromLTRB(
        24, 24, 24, 24 + MediaQuery.of(context).viewInsets.bottom,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                isStorage ? Icons.photo_library_outlined : Icons.map_outlined,
                color: theme.colorScheme.primary,
              ),
              const SizedBox(width: 10),
              Text(
                isStorage ? 'Storage is full' : 'Trip limit reached',
                style: theme.textTheme.titleLarge,
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(widget.error.detail, style: theme.textTheme.bodyMedium),
          if (_failure != null) ...[
            const SizedBox(height: 12),
            Text(_failure!,
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.error)),
          ],
          const SizedBox(height: 20),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: _busy ? null : () => Navigator.of(context).maybePop(),
                  child: const Text('Not now'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: ElevatedButton.icon(
                  onPressed: _busy ? null : _upgrade,
                  icon: _busy
                      ? const SizedBox(
                          width: 16, height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.rocket_launch_outlined, size: 18),
                  label: const Text('Upgrade'),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// Show the upgrade prompt for a quota refusal.
Future<void> showUpgradeSheet(
  BuildContext context,
  QuotaError error, {
  BillingService? service,
  Future<void> Function(String url)? launcher,
}) {
  final billing = service ?? BillingService();
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (_) => UpgradeSheet(
      error: error,
      onUpgrade: () => billing.checkoutUrl(),
      launcher: launcher,
    ),
  );
}
