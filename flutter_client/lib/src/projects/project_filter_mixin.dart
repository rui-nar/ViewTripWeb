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

  /// Tags shown for [dateKey] under the "inherit from the previous day" rule
  /// (issue #18): a day with its own tags keeps them; a day with none falls
  /// back to the nearest strictly-earlier day that has tags. See
  /// [effectiveDayTags] for the gap-skipping semantics.
  List<String> effectiveTagsFor(String dateKey) =>
      effectiveDayTags(dayMeta, dateKey);

  /// Whether [dateKey] carries tags of its own (vs only inherited ones). Lets
  /// the UI render inherited tags faded and distinguish them from real ones.
  bool dayHasOwnTags(String dateKey) =>
      _ownDayTags(dayMeta, dateKey).isNotEmpty;

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
        // Match on *effective* tags so days that only inherit a tag from an
        // earlier day still satisfy the tag filter (issue #18).
        final tags = effectiveDayTags(dayMeta, dk).toSet();
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

// ── Pure tag-inheritance helpers (issue #18) ─────────────────────────────────
//
// Kept as free functions so they can be unit-tested without building a
// ProjectNotifier. Date keys are "YYYY-MM-DD", so lexicographic string order is
// chronological order — no DateTime parsing needed.

/// The tags a day owns outright (an empty list if it has none of its own).
List<String> _ownDayTags(
  Map<String, Map<String, dynamic>> dayMeta,
  String dateKey,
) {
  final raw = dayMeta[dateKey]?['tags'];
  return raw is List ? raw.cast<String>() : const <String>[];
}

/// Effective tags for [dateKey] under the "inherit from the previous day" rule
/// (issue #18, "live fallback" model):
///
/// * a day with its own tags shows exactly those;
/// * a day with none falls back to the tags of the nearest *strictly earlier*
///   day that has its own tags — empty days in between are skipped (so a gap
///   day never blanks out the inheritance chain);
/// * a day with no own tags and no earlier tagged day shows nothing.
///
/// Inherited tags are never persisted: they vanish the moment the source day's
/// tags change, and a day only "owns" tags once the user edits it.
@visibleForTesting
List<String> effectiveDayTags(
  Map<String, Map<String, dynamic>> dayMeta,
  String dateKey,
) {
  final own = _ownDayTags(dayMeta, dateKey);
  if (own.isNotEmpty) return own;

  String? best;
  for (final k in dayMeta.keys) {
    if (k.compareTo(dateKey) >= 0) continue; // must be strictly earlier
    if (_ownDayTags(dayMeta, k).isEmpty) continue; // must own tags
    if (best == null || k.compareTo(best) > 0) best = k; // keep the latest
  }
  return best == null ? const <String>[] : _ownDayTags(dayMeta, best);
}
