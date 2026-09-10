/// Pure rules for the days that fall after a trip's end date.
///
/// Split out of project_settings_screen.dart so the claim the "Remove days
/// after the end date?" confirmation makes can be unit-tested on its own
/// (issue #358), and so the day list here and the one the trip actually
/// renders are derived from the same extraction.
library;

/// The days sitting after a trip end date, split by whether dropping their
/// day-meta entry actually makes them disappear from the trip.
class TripEndOrphans {
  /// Days after the end date whose only content is day-meta. Removing that
  /// entry removes the day.
  final List<String> removable;

  /// Days after the end date that carry an activity or a memory. The trip's
  /// day list is the union of day-meta keys, activity dates and memory dates
  /// (see [ProjectNotifier.orderedDayKeys]), so these stay visible whatever
  /// day-meta says. Their day-meta is deliberately left alone: silently
  /// wiping the notes of a day the user can still see would be worse than
  /// leaving them.
  final List<String> pinned;

  const TripEndOrphans({required this.removable, required this.pinned});
}

/// Day keys ("YYYY-MM-DD") that carry an activity or a memory.
Set<String> contentDayKeys(
  List<Map<String, dynamic>> activities,
  List<Map<String, dynamic>> items,
) {
  final keys = <String>{};
  for (final a in activities) {
    final ds = (a['start_date_local'] as String?)?.split('T').first;
    if (ds != null && ds.isNotEmpty) keys.add(ds);
  }
  for (final item in items) {
    if (item['item_type'] != 'memory') continue;
    final m = item['memory'] as Map<String, dynamic>?;
    final ds = (m?['date'] as String?)?.split('T').first;
    if (ds != null && ds.isNotEmpty) keys.add(ds);
  }
  return keys;
}

/// Classifies every day in [dayKeys] strictly after [tripEnd] (both plain
/// "YYYY-MM-DD", so a lexicographic compare is a date compare). Both returned
/// lists are sorted ascending and duplicate-free.
TripEndOrphans classifyTripEndOrphans({
  required Iterable<String> dayKeys,
  required Set<String> daysWithContent,
  required String tripEnd,
}) {
  final removable = <String>[];
  final pinned = <String>[];
  for (final key in dayKeys.toSet().toList()..sort()) {
    if (key.compareTo(tripEnd) <= 0) continue;
    (daysWithContent.contains(key) ? pinned : removable).add(key);
  }
  return TripEndOrphans(removable: removable, pinned: pinned);
}
