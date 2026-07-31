/// Choosing a plan (issue #121).
///
/// One sheet serves both entry points — "Change plan" in Settings, and the
/// upgrade prompt after a 402 — because they ask the same question. What
/// differs is the framing: after a refusal the sheet leads with the cheapest
/// plan that actually covers what was refused, rather than the priciest one.
library;

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import 'billing_service.dart';

/// The cheapest plan in [plans] that covers [needed] of [resource], or null.
///
/// Pure and exported so the recommendation is testable without a widget.
PlanInfo? cheapestPlanCovering(
  List<PlanInfo> plans,
  String resource,
  int needed, {
  String? strongerThan,
}) {
  final ordered = plans.toList();
  final floor = strongerThan == null
      ? -1
      : ordered.indexWhere((p) => p.id == strongerThan);
  for (var i = 0; i < ordered.length; i++) {
    if (i <= floor) continue;         // never suggest what they already have
    if (ordered[i].isFree) continue;  // free is not an upgrade
    if (ordered[i].limits.covers(resource, needed)) return ordered[i];
  }
  return null;
}

class PlanPicker extends StatefulWidget {
  /// Plan the user is on — shown as current, never offered as an upgrade.
  final String currentPlan;

  /// The refusal that opened this, when it was opened by one.
  final QuotaError? because;

  final BillingService? service;
  final Future<void> Function(String url)? launcher;

  const PlanPicker({
    super.key,
    required this.currentPlan,
    this.because,
    this.service,
    this.launcher,
  });

  @override
  State<PlanPicker> createState() => _PlanPickerState();
}

class _PlanPickerState extends State<PlanPicker> {
  late final BillingService _billing = widget.service ?? BillingService();
  late final Future<List<PlanInfo>> _plans = _billing.plans();
  String? _busyPlan;
  String? _failure;

  Future<void> _buy(PlanInfo plan) async {
    setState(() {
      _busyPlan = plan.id;
      _failure = null;
    });
    try {
      final url = await _billing.checkoutUrl(plan: plan.id);
      if (url.isEmpty) throw Exception('empty checkout url');
      final launch = widget.launcher ??
          (String u) async =>
              launchUrl(Uri.parse(u), mode: LaunchMode.externalApplication);
      await launch(url);
      if (mounted) Navigator.of(context).maybePop();
    } catch (_) {
      if (mounted) {
        setState(() => _failure = 'Could not start checkout. Please try again.');
      }
    } finally {
      if (mounted) setState(() => _busyPlan = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return FutureBuilder<List<PlanInfo>>(
      future: _plans,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Padding(
            padding: EdgeInsets.all(48),
            child: Center(child: CircularProgressIndicator()),
          );
        }
        final plans = snapshot.data ?? const <PlanInfo>[];
        if (plans.isEmpty) {
          return Padding(
            padding: const EdgeInsets.all(24),
            child: Text('Plans are unavailable right now.',
                style: theme.textTheme.bodyMedium),
          );
        }
        final quota = widget.because;
        final recommended = quota == null
            ? null
            : cheapestPlanCovering(plans, quota.resource, quota.needed,
                strongerThan: widget.currentPlan);

        return SingleChildScrollView(
          padding: EdgeInsets.fromLTRB(
            20, 8, 20, 20 + MediaQuery.of(context).viewInsets.bottom,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(quota == null ? 'Choose a plan' : 'Upgrade to keep going',
                  style: theme.textTheme.titleLarge),
              if (quota != null) ...[
                const SizedBox(height: 8),
                Text(quota.detail, style: theme.textTheme.bodyMedium),
              ],
              if (_failure != null) ...[
                const SizedBox(height: 12),
                Text(_failure!,
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: theme.colorScheme.error)),
              ],
              const SizedBox(height: 16),
              for (final plan in plans)
                _PlanTile(
                  plan: plan,
                  isCurrent: plan.id == widget.currentPlan,
                  isRecommended: recommended != null && plan.id == recommended.id,
                  busy: _busyPlan == plan.id,
                  onChoose: plan.isFree || plan.id == widget.currentPlan
                      ? null
                      : () => _buy(plan),
                ),
            ],
          ),
        );
      },
    );
  }
}

class _PlanTile extends StatelessWidget {
  final PlanInfo plan;
  final bool isCurrent;
  final bool isRecommended;
  final bool busy;
  final VoidCallback? onChoose;

  const _PlanTile({
    required this.plan,
    required this.isCurrent,
    required this.isRecommended,
    required this.busy,
    required this.onChoose,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        border: Border.all(
          color: isRecommended ? theme.colorScheme.primary : theme.dividerColor,
          width: isRecommended ? 1.5 : 1,
        ),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Name and price wrap onto a second line rather than pushing the
              // badge off the edge — the three together overflow a 360 px phone
              // once the tier names get any longer (issue #153).
              Expanded(
                child: Wrap(
                  spacing: 8,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text(plan.name, style: theme.textTheme.titleMedium),
                    Text(plan.priceLabel, style: theme.textTheme.bodySmall),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              if (isCurrent)
                Text('Current plan', style: theme.textTheme.labelSmall)
              else if (isRecommended)
                Text('Recommended',
                    style: theme.textTheme.labelSmall
                        ?.copyWith(color: theme.colorScheme.primary)),
            ],
          ),
          const SizedBox(height: 10),
          for (final feature in plan.features)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Row(
                children: [
                  Icon(Icons.check_rounded,
                      size: 16, color: theme.colorScheme.primary),
                  const SizedBox(width: 6),
                  Expanded(
                      child: Text(feature, style: theme.textTheme.bodySmall)),
                ],
              ),
            ),
          if (onChoose != null) ...[
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: busy ? null : onChoose,
                child: busy
                    ? const SizedBox(
                        width: 16, height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2))
                    : Text('Choose ${plan.name}'),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// Open the picker. [because] frames it as an upgrade after a refusal.
Future<void> showPlanPicker(
  BuildContext context, {
  required String currentPlan,
  QuotaError? because,
  BillingService? service,
  Future<void> Function(String url)? launcher,
}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (_) => PlanPicker(
      currentPlan: currentPlan,
      because: because,
      service: service,
      launcher: launcher,
    ),
  );
}
