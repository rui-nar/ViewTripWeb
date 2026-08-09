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
import 'plan_widgets.dart';

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

  /// Whether a subscription is actually running, i.e. there is something to
  /// *move* rather than buy. Drives which provider flow each tile opens, and
  /// whether the free tile means "cancel".
  final bool subscribed;

  /// The refusal that opened this, when it was opened by one.
  final QuotaError? because;

  final BillingService? service;
  final Future<void> Function(String url)? launcher;

  const PlanPicker({
    super.key,
    required this.currentPlan,
    this.subscribed = false,
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
      final url = await _billing.urlToReach(
          plan: plan.id, subscribed: widget.subscribed);
      if (url.isEmpty) throw Exception('empty provider url');
      final launch = widget.launcher ??
          (String u) async =>
              launchUrl(Uri.parse(u), mode: LaunchMode.externalApplication);
      await launch(url);
      if (mounted) Navigator.of(context).maybePop(true);
    } catch (_) {
      if (mounted) {
        setState(() => _failure = widget.subscribed
            ? 'Could not start the plan change. Please try again.'
            : 'Could not start checkout. Please try again.');
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
                PlanTile(
                  plan: plan,
                  isCurrent: plan.id == widget.currentPlan,
                  isRecommended: recommended != null && plan.id == recommended.id,
                  busy: _busyPlan == plan.id,
                  // Free is not something you buy — but a subscriber *can*
                  // move down to it, which means ending the subscription.
                  action: plan.id == widget.currentPlan
                      ? null
                      : plan.isFree
                          ? (widget.subscribed ? 'Cancel subscription' : null)
                          : 'Choose ${plan.name}',
                  onChoose: () => _buy(plan),
                ),
            ],
          ),
        );
      },
    );
  }
}

/// Open the picker. [because] frames it as an upgrade after a refusal.
///
/// Returns true when the user was sent off to the provider, so the caller can
/// refresh the plan it is displaying.
Future<bool> showPlanPicker(
  BuildContext context, {
  required String currentPlan,
  bool subscribed = false,
  QuotaError? because,
  BillingService? service,
  Future<void> Function(String url)? launcher,
}) async {
  final left = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (_) => PlanPicker(
      currentPlan: currentPlan,
      subscribed: subscribed,
      because: because,
      service: service,
      launcher: launcher,
    ),
  );
  return left ?? false;
}
