/// Billing: plan, usage, and the quota errors the server sends back (#121).
///
/// Everything here is plain Dart over [ApiClient] — no widgets — so the parsing
/// rules (which are where the bugs live) are unit-testable with a MockClient.
///
/// A self-hosted instance reports `billing_enabled: false`, and the UI hides
/// every billing affordance rather than showing a plan nobody can buy.
library;

import 'dart:convert';

import '../api/client.dart';

class PlanLimits {
  /// null = unlimited.
  final int? maxProjects;
  final int? maxStorageBytes;

  /// Calendar length of one trip, first day to last inclusive — empty days in
  /// the middle count.
  final int? maxTripDays;

  const PlanLimits({this.maxProjects, this.maxStorageBytes, this.maxTripDays});

  factory PlanLimits.fromJson(Map<String, dynamic>? json) => PlanLimits(
        maxProjects: (json?['max_projects'] as num?)?.toInt(),
        maxStorageBytes: (json?['max_storage_bytes'] as num?)?.toInt(),
        maxTripDays: (json?['max_trip_days'] as num?)?.toInt(),
      );

  /// Does this plan cover [needed] of [resource]? An unlimited plan always does.
  bool covers(String resource, int needed) {
    final limit = switch (resource) {
      'projects' => maxProjects,
      'storage' => maxStorageBytes,
      'trip_days' => maxTripDays,
      _ => null,
    };
    return limit == null || needed <= limit;
  }
}

class BillingStatus {
  final bool billingEnabled;
  final bool quotasEnforced;
  final String plan;
  final String planName;
  final String status;
  final bool cancelAtPeriodEnd;
  final double currentPeriodEnd;
  final bool adminOverride;
  final PlanLimits limits;
  final int projects;
  final int storageBytes;

  const BillingStatus({
    required this.billingEnabled,
    required this.quotasEnforced,
    required this.plan,
    required this.planName,
    required this.status,
    required this.cancelAtPeriodEnd,
    required this.currentPeriodEnd,
    required this.adminOverride,
    required this.limits,
    required this.projects,
    required this.storageBytes,
  });

  factory BillingStatus.fromJson(Map<String, dynamic> json) {
    final usage = (json['usage'] as Map?)?.cast<String, dynamic>() ?? const {};
    return BillingStatus(
      billingEnabled: json['billing_enabled'] == true,
      quotasEnforced: json['quotas_enforced'] == true,
      plan: json['plan'] as String? ?? 'free',
      planName: json['plan_name'] as String? ?? 'Free',
      status: json['status'] as String? ?? 'none',
      cancelAtPeriodEnd: json['cancel_at_period_end'] == true,
      currentPeriodEnd: (json['current_period_end'] as num?)?.toDouble() ?? 0,
      adminOverride: json['admin_override'] == true,
      limits: PlanLimits.fromJson((json['limits'] as Map?)?.cast<String, dynamic>()),
      projects: (usage['projects'] as num?)?.toInt() ?? 0,
      storageBytes: (usage['storage_bytes'] as num?)?.toInt() ?? 0,
    );
  }

  bool get isPaid => plan != 'free';

  /// True once the user has a provider account, i.e. the portal can be opened.
  bool get canManage => status != 'none';

  /// Fraction of the storage allowance in use, or null when unlimited.
  double? get storageFraction {
    final limit = limits.maxStorageBytes;
    if (limit == null || limit <= 0) return null;
    return (storageBytes / limit).clamp(0.0, 1.0);
  }
}

class PlanInfo {
  final String id;
  final String name;
  final String priceLabel;
  final List<String> features;
  final PlanLimits limits;

  const PlanInfo({
    required this.id,
    required this.name,
    required this.priceLabel,
    required this.features,
    this.limits = const PlanLimits(),
  });

  factory PlanInfo.fromJson(Map<String, dynamic> json) => PlanInfo(
        id: json['id'] as String? ?? '',
        name: json['name'] as String? ?? '',
        priceLabel: json['price_label'] as String? ?? '',
        features:
            (json['features'] as List?)?.map((e) => e.toString()).toList() ?? const [],
        limits: PlanLimits.fromJson(
            (json['limits'] as Map?)?.cast<String, dynamic>()),
      );

  bool get isFree => id == 'free';
}

/// A 402 from the server: the action is allowed in principle, on a bigger plan.
class QuotaError {
  /// "projects" | "storage"
  /// "projects" | "storage" | "trip_days"
  final String resource;
  final String plan;
  final String detail;
  final int? limit;
  final int used;

  /// What the refused action would have needed — the number a plan has to cover
  /// for the upgrade to actually solve the problem.
  final int needed;

  const QuotaError({
    required this.resource,
    required this.plan,
    required this.detail,
    required this.limit,
    required this.used,
    this.needed = 0,
  });

  /// Parse a 402 quota response, or null if [e] is any other failure.
  ///
  /// Returning null rather than throwing keeps the caller's existing error
  /// handling intact — only a genuine quota refusal opens the upgrade prompt.
  static QuotaError? fromApiException(ApiException e) {
    if (e.statusCode != 402) return null;
    try {
      final body = jsonDecode(e.body);
      if (body is! Map || body['code'] != 'quota_exceeded') return null;
      return QuotaError(
        resource: body['resource'] as String? ?? '',
        plan: body['plan'] as String? ?? '',
        detail: body['detail'] as String? ?? 'Your plan is full.',
        limit: (body['limit'] as num?)?.toInt(),
        used: (body['used'] as num?)?.toInt() ?? 0,
        needed: (body['needed'] as num?)?.toInt() ??
            (body['used'] as num?)?.toInt() ?? 0,
      );
    } catch (_) {
      return null;
    }
  }
}

class BillingService {
  final ApiClient _api;

  BillingService([ApiClient? client]) : _api = client ?? api;

  Future<BillingStatus> status() async {
    final data = await _api.get('/api/billing/me') as Map<String, dynamic>;
    return BillingStatus.fromJson(data);
  }

  Future<List<PlanInfo>> plans() async {
    final data = await _api.get('/api/billing/plans') as List;
    return data
        .map((e) => PlanInfo.fromJson((e as Map).cast<String, dynamic>()))
        .toList();
  }

  /// URL of the provider-hosted checkout page for [plan].
  Future<String> checkoutUrl({
    String? plan,
    String returnPath = '/settings',
  }) async {
    final data = await _api.post('/api/billing/checkout', {
      if (plan != null) 'plan': plan,
      'return_path': returnPath,
    }) as Map<String, dynamic>;
    return data['url'] as String? ?? '';
  }

  /// URL of the provider-hosted billing portal (change card, cancel, invoices).
  Future<String> portalUrl({String returnPath = '/settings'}) async {
    final data = await _api.post('/api/billing/portal', {
      'return_path': returnPath,
    }) as Map<String, dynamic>;
    return data['url'] as String? ?? '';
  }
}

/// "1.4 GB" / "512 MB" / "18 KB" — sizes as a person would write them.
String formatBytes(int bytes) {
  if (bytes < 1024) return '$bytes B';
  const units = ['KB', 'MB', 'GB', 'TB'];
  var value = bytes / 1024;
  var unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  final rounded = value >= 10 ? value.toStringAsFixed(0) : value.toStringAsFixed(1);
  return '$rounded ${units[unit]}';
}
