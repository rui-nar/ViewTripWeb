/// Pure resolution of a single day's route points from project geo + items.
///
/// Mirrors the day→geometry logic used by the map panel
/// (`_dayItemIds` + `_extractSelectedPoints`) so the day-focus map export
/// zooms to exactly the activities/segments shown for that day. Pure and
/// unit-testable — no Flutter, no I/O.
library;

import 'package:latlong2/latlong.dart';

/// Returns the LatLng points of every activity/segment belonging to [date].
///
/// [activities] are the project's activity maps (each with `id` and
/// `start_date_local`); [items] is the ordered project item list. Segments
/// without an explicit date inherit the preceding activity's date, matching
/// the map panel's behaviour. Returns an empty list when nothing matches.
List<LatLng> dayRoutePoints({
  required Map<String, dynamic>? geo,
  required List<Map<String, dynamic>> items,
  required List<Map<String, dynamic>> activities,
  required String date,
}) {
  if (geo == null) return const [];

  final activityById = {for (final a in activities) a['id']: a};
  final actIds = <String>{};
  final segIds = <String>{};
  String? lastDate;
  for (final item in items) {
    if (item['item_type'] == 'activity') {
      final a = activityById[item['activity_id']];
      final ds = (a?['start_date_local'] as String?)?.split('T').first;
      if (ds != null) lastDate = ds;
      if ((ds ?? lastDate) == date) {
        final id = item['activity_id']?.toString();
        if (id != null) actIds.add(id);
      }
    } else {
      final ds = item['segment']?['date'] as String? ?? lastDate;
      if (ds == date) {
        final id = item['segment']?['id']?.toString();
        if (id != null) segIds.add(id);
      }
    }
  }

  final points = <LatLng>[];
  final features = geo['features'];
  if (features is! List) return points;
  for (final feature in features) {
    if (feature is! Map) continue;
    final props = feature['properties'] as Map? ?? {};
    final isSegment = props['type'] == 'segment';
    final featureId = isSegment
        ? props['segment_id']?.toString()
        : props['activity_id']?.toString();
    final match =
        isSegment ? segIds.contains(featureId) : actIds.contains(featureId);
    if (!match) continue;
    final coords = (feature['geometry'] as Map? ?? {})['coordinates'];
    if (coords is! List) continue;
    for (final c in coords) {
      if (c is List && c.length >= 2) {
        points.add(LatLng((c[1] as num).toDouble(), (c[0] as num).toDouble()));
      }
    }
  }
  return points;
}
