/// "Plan" section of the settings screen (issue #121).
///
/// Renders nothing at all when the server reports `billing_enabled: false` —
/// a self-hosted instance has no tiers, and showing a greyed-out plan card
/// there would advertise a limit that does not exist.
library;

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import 'billing_service.dart';
import 'plan_picker.dart';

class BillingSection extends StatefulWidget {
  /// Injected in tests; defaults to the live service.
  final BillingService? service;

  /// Opens checkout / portal URLs. Injected in tests.
  final Future<void> Function(String url)? launcher;

  /// The page URL, checked for `?checkout=success` (issue #192). Injected in
  /// tests; defaults to the real browser URL — checkout only ever happens on
  /// web (see docs/BILLING.md), so this is always empty on other platforms.
  final Uri? currentUri;

  /// Spacing between plan-status retries after a checkout redirect.
  /// Injected in tests to keep them fast; defaults to a real wait.
  final Duration retryDelay;

  const BillingSection({
    super.key,
    this.service,
    this.launcher,
    this.currentUri,
    this.retryDelay = const Duration(seconds: 2),
  });

  @override
  State<BillingSection> createState() => _BillingSectionState();
}

class _BillingSectionState extends State<BillingSection> {
  late final BillingService _billing = widget.service ?? BillingService();
  late final Future<BillingStatus> _future = _loadStatus();
  bool _busy = false;
  String? _failure;

  /// Stripe's webhook can lag a beat behind the checkout redirect (issue
  /// #192): landing back on `?checkout=success` right after paying can still
  /// read the pre-upgrade plan if we ask before the webhook has landed. Poll
  /// briefly rather than believe the very first read.
  Future<BillingStatus> _loadStatus() async {
    final uri = widget.currentUri ?? Uri.base;
    final justPaid = uri.queryParameters['checkout'] == 'success';
    var status = await _billing.status();
    if (!justPaid) return status;
    for (var i = 0; i < 5 && !status.isPaid; i++) {
      await Future.delayed(widget.retryDelay);
      status = await _billing.status();
    }
    return status;
  }

  Future<void> _changePlan(BillingStatus status) async {
    await showPlanPicker(
      context,
      currentPlan: status.plan,
      service: _billing,
      launcher: widget.launcher,
    );
  }

  Future<void> _open(Future<String> Function() fetch) async {
    setState(() {
      _busy = true;
      _failure = null;
    });
    try {
      final url = await fetch();
      if (url.isEmpty) throw Exception('empty url');
      final launch = widget.launcher ??
          (String u) async =>
              launchUrl(Uri.parse(u), mode: LaunchMode.externalApplication);
      await launch(url);
    } catch (_) {
      if (mounted) setState(() => _failure = 'Could not reach the billing service.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<BillingStatus>(
      future: _future,
      builder: (context, snapshot) {
        final status = snapshot.data;
        // Hidden while loading, on error, and on self-hosted instances: the
        // section must never flash a plan the deployment doesn't sell.
        if (status == null || !status.billingEnabled) {
          return const SizedBox.shrink();
        }
        return Padding(
          padding: const EdgeInsets.only(bottom: 16),
          child: _card(context, status),
        );
      },
    );
  }

  Widget _card(BuildContext context, BillingStatus status) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.workspace_premium_outlined,
                    color: theme.colorScheme.primary, size: 20),
                const SizedBox(width: 8),
                Text('Plan', style: theme.textTheme.titleLarge),
              ],
            ),
            const Divider(height: 24),
            Row(
              children: [
                Text(status.planName, style: theme.textTheme.titleMedium),
                const SizedBox(width: 8),
                if (status.adminOverride)
                  const _Chip(label: 'Granted')
                else if (status.cancelAtPeriodEnd)
                  const _Chip(label: 'Ends soon')
                else if (status.status == 'past_due')
                  const _Chip(label: 'Payment failed'),
              ],
            ),
            const SizedBox(height: 16),
            _usage(
              context,
              label: 'Trips',
              used: '${status.projects}',
              limit: status.limits.maxProjects == null
                  ? 'unlimited'
                  : '${status.limits.maxProjects}',
              fraction: status.limits.maxProjects == null
                  ? null
                  : (status.projects / status.limits.maxProjects!)
                      .clamp(0.0, 1.0),
            ),
            const SizedBox(height: 12),
            _usage(
              context,
              label: 'Photos',
              used: formatBytes(status.storageBytes),
              limit: status.limits.maxStorageBytes == null
                  ? 'unlimited'
                  : formatBytes(status.limits.maxStorageBytes!),
              fraction: status.storageFraction,
            ),
            const SizedBox(height: 12),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text('Trip length', style: theme.textTheme.bodySmall),
                Text(
                  status.limits.maxTripDays == null
                      ? 'any length'
                      : 'up to ${status.limits.maxTripDays} days',
                  style: theme.textTheme.bodySmall,
                ),
              ],
            ),
            if (_failure != null) ...[
              const SizedBox(height: 12),
              Text(_failure!,
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.error)),
            ],
            const SizedBox(height: 20),
            // Wrap, not Row: on a narrow phone the two actions stack instead of
            // overflowing. The explicit minimumSize is required — the app theme
            // sets ElevatedButton's to Size.fromHeight(44), i.e. *infinite*
            // width, which a Row's unbounded main axis turns into a layout
            // failure and an invisible button (issue #153).
            Wrap(
              spacing: 12,
              runSpacing: 8,
              children: [
                ElevatedButton.icon(
                  style: ElevatedButton.styleFrom(
                      minimumSize: const Size(0, 40)),
                  onPressed: _busy ? null : () => _changePlan(status),
                  icon: const Icon(Icons.rocket_launch_outlined, size: 18),
                  label: Text(status.isPaid ? 'Change plan' : 'Upgrade'),
                ),
                if (status.canManage)
                  OutlinedButton.icon(
                    style: OutlinedButton.styleFrom(
                        minimumSize: const Size(0, 40)),
                    onPressed:
                        _busy ? null : () => _open(() => _billing.portalUrl()),
                    icon: const Icon(Icons.receipt_long_outlined, size: 18),
                    label: const Text('Manage billing'),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _usage(
    BuildContext context, {
    required String label,
    required String used,
    required String limit,
    required double? fraction,
  }) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label, style: theme.textTheme.bodySmall),
            Text('$used / $limit', style: theme.textTheme.bodySmall),
          ],
        ),
        const SizedBox(height: 6),
        ClipRRect(
          borderRadius: BorderRadius.circular(4),
          child: LinearProgressIndicator(
            value: fraction ?? 0,
            minHeight: 6,
            backgroundColor: theme.colorScheme.surfaceContainerHighest,
          ),
        ),
      ],
    );
  }
}

class _Chip extends StatelessWidget {
  final String label;
  const _Chip({required this.label});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: theme.colorScheme.secondaryContainer,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(label,
          style: theme.textTheme.labelSmall
              ?.copyWith(color: theme.colorScheme.onSecondaryContainer)),
    );
  }
}
