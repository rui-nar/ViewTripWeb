/// Mixin that provides all filter state and logic to ProjectNotifier.
///
/// Abstract getters/setters declared here are satisfied automatically by
/// ProjectNotifier's existing fields — no boilerplate needed in the class.
library;

import 'package:flutter/foundation.dart';

import 'project_filters.dart';

mixin ProjectFilterMixin on ChangeNotifier {
  // ── Abstract: project data (provided by ProjectNotifier fields) ──────────
  List<Map<String, dynamic>> get activities;
  List<Map<String, dynamic>> get items;
  Map<String, Map<String, dynamic>> get dayMeta;

  // ── Abstract: selection state (provided by ProjectNotifier fields) ────────
  // setFilters clears item selection so a filtered-out item isn't left active.
  String? get selectedDay;
  set selectedDay(String? v);
  dynamic get selectedActivityId;
  set selectedActivityId(dynamic v);
  dynamic get selectedSegmentId;
  set selectedSegmentId(dynamic v);
  dynamic get selectedMemoryId;
  set selectedMemoryId(dynamic v);
  Set<String> get selectedDays;
  set selectedDays(Set<String> v);

  // ── Filter state (owned by this mixin) ───────────────────────────────────
  ProjectFilters _filters = ProjectFilters.empty;

  ProjectFilters get filters => _filters;

  // Backwards-compat shims — all 31 widget call sites remain unchanged.
  Set<String> get tagFilter          => _filters.tags;
  Set<String> get sleepingFilter     => _filters.sleeping;
  Set<String> get activityTypeFilter => _filters.activityTypes;
  Set<String> get transportFilter    => _filters.transport;
  int  get activeFilterCount         => _filters.activeCount;
  bool get hasActiveFilter           => _filters.hasActive;
  bool get hasFilterableContent      =>
      availableTags.isNotEmpty || availableSleepingModes.isNotEmpty ||
      availableActivityTypes.isNotEmpty || availableTransportationMeans.isNotEmpty;

  // ── Available options (derived from project data) ─────────────────────────

  List<String> get availableTags {
    final s = <String>{};
    for (final m in dayMeta.values) {
      final t = m['tags'];
      if (t is List) s.addAll(t.cast<String>());
    }
    return s.toList()..sort();
  }

  List<String> get availableSleepingModes {
    final s = <String>{};
    bool hasNoData = false;
    for (final m in dayMeta.values) {
      final v = m['sleeping'] as String?;
      if (v != null && v.isNotEmpty) {
        s.add(v);
      } else {
        hasNoData = true;
      }
    }
    final result = s.toList()..sort();
    if (hasNoData) result.add('No data');
    return result;
  }

  List<String> get availableActivityTypes {
    final s = <String>{};
    for (final a in activities) {
      final t = (a['type'] as String? ?? '').toLowerCase();
      if (t.isNotEmpty) s.add(t);
    }
    return s.toList()..sort();
  }

  List<String> get availableTransportationMeans {
    final s = <String>{};
    for (final item in items) {
      if (item['item_type'] != 'segment') continue;
      final t = (item['segment'] as Map?)?['segment_type'] as String?;
      if (t != null && t.isNotEmpty) s.add(t);
    }
    return s.toList()..sort();
  }

  // ── Mutators ──────────────────────────────────────────────────────────────

  void setFilters({
    Set<String>? tags,
    Set<String>? sleeping,
    Set<String>? activityTypes,
    Set<String>? transport,
  }) {
    _filters = _filters.copyWith(
      tags: tags,
      sleeping: sleeping,
      activityTypes: activityTypes,
      transport: transport,
    );
    _recomputeSelectedDays();
    selectedDay = null;
    selectedActivityId = null;
    selectedSegmentId = null;
    selectedMemoryId = null;
    notifyListeners();
  }

  void clearAllFilters() =>
      setFilters(tags: {}, sleeping: {}, activityTypes: {}, transport: {});

  /// Resets filter state to empty. Called by ProjectNotifier.clear().
  void resetFilters() {
    _filters = ProjectFilters.empty;
    selectedDays = {};
  }

  // ── Internal ──────────────────────────────────────────────────────────────

  void _recomputeSelectedDays() {
    if (!_filters.hasActive) {
      selectedDays = {};
      return;
    }

    final actByDay = <String, Set<String>>{};
    for (final a in activities) {
      final d = (a['start_date_local'] as String?)?.substring(0, 10);
      final t = (a['type'] as String? ?? '').toLowerCase();
      if (d != null && t.isNotEmpty) (actByDay[d] ??= {}).add(t);
    }

    final trByDay = <String, Set<String>>{};
    for (final item in items) {
      if (item['item_type'] != 'segment') continue;
      final seg = item['segment'] as Map?;
      final d = seg?['date'] as String?;
      final t = seg?['segment_type'] as String?;
      if (d != null && t != null) (trByDay[d] ??= {}).add(t);
    }

    final matching = <String>{};
    for (final dk in dayMeta.keys) {
      if (_filters.tags.isNotEmpty) {
        final rawTags = dayMeta[dk]?['tags'];
        final tags =
            rawTags is List ? rawTags.cast<String>().toSet() : const <String>{};
        if (!tags.any(_filters.tags.contains)) continue;
      }
      if (_filters.sleeping.isNotEmpty) {
        final s = dayMeta[dk]?['sleeping'] as String?;
        final label = (s == null || s.isEmpty) ? 'No data' : s;
        if (!_filters.sleeping.contains(label)) continue;
      }
      if (_filters.activityTypes.isNotEmpty) {
        final types = actByDay[dk] ?? const {};
        if (!types.any(_filters.activityTypes.contains)) continue;
      }
      if (_filters.transport.isNotEmpty) {
        final types = trByDay[dk] ?? const {};
        if (!types.any(_filters.transport.contains)) continue;
      }
      matching.add(dk);
    }
    selectedDays = matching;
  }
}
