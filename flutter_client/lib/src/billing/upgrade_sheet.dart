/// What a 402 turns into (issue #121).
///
/// Deliberately not an error dialog: hitting a plan limit is not a failure the
/// user caused, so it opens the plan picker — framed by what was refused, and
/// leading with the cheapest plan that would actually have allowed it.
///
/// Thin on purpose. It exists so call sites read as "if the server refused on a
/// quota, offer the upgrade" without repeating the plumbing, and so none of
/// them has to know which plan the user is on.
library;

import 'package:flutter/material.dart';

import 'billing_service.dart';
import 'plan_picker.dart';

/// Show the upgrade prompt for a quota refusal.
Future<void> showUpgradeSheet(
  BuildContext context,
  QuotaError error, {
  BillingService? service,
  Future<void> Function(String url)? launcher,
}) {
  return showPlanPicker(
    context,
    // The refusal names the plan that was in force, so the picker can mark it
    // as current and never offer it back as an "upgrade".
    currentPlan: error.plan,
    because: error,
    service: service,
    launcher: launcher,
  );
}

/// Show the prompt only if there was a refusal — the shape every caller wants,
/// since they hand over whatever a notifier's `takeQuotaError()` returned.
Future<bool> maybeShowUpgradeSheet(
  BuildContext context,
  QuotaError? error, {
  BillingService? service,
  Future<void> Function(String url)? launcher,
}) async {
  if (error == null || !context.mounted) return false;
  await showUpgradeSheet(context, error, service: service, launcher: launcher);
  return true;
}
