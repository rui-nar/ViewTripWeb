// Unit tests for ProjectNotifier.orderedDayKeys() and activeDayKey() — the
// day-resolution the add-FAB relies on. orderedDayKeys is the full-trip day
// list (union of day-meta / activity / memory dates, ascending); activeDayKey
// picks the FAB's default day: today while the trip is active, else the last
// trip day.

import 'package:flutter_test/flutter_test.dart';
import 'package:viewtrip_client/src/projects/project_notifier.dart';
import 'package:viewtrip_client/src/projects/project_service.dart';

ProjectNotifier _notifier({
  Map<String, Map<String, dynamic>> dayMeta = const {},
  List<Map<String, dynamic>> activities = const [],
  List<Map<String, dynamic>> items = const [],
  String? tripEnd,
}) {
  return ProjectNotifier(ProjectService())
    ..dayMeta = {for (final e in dayMeta.entries) e.key: e.value}
    ..activities = List.of(activities)
    ..items = List.of(items)
    ..tripEnd = tripEnd;
}

String _ymd(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-'
    '${d.month.toString().padLeft(2, '0')}-'
    '${d.day.toString().padLeft(2, '0')}';

void main() {
  group('orderedDayKeys', () {
    test('is empty when the project has no days', () {
      expect(_notifier().orderedDayKeys(), isEmpty);
    });

    test('unions day-meta, activity and memory dates, sorted ascending, deduped',
        () {
      final n = _notifier(
        dayMeta: {'2025-06-03': {}},
        activities: [
          {'start_date_local': '2025-06-01T08:30:00'},
          {'start_date_local': '2025-06-03T10:00:00'}, // dup with dayMeta day
        ],
        items: [
          {
            'item_type': 'memory',
            'memory': {'date': '2025-06-02'},
          },
          {'item_type': 'activity', 'activity_id': '1'}, // ignored (no memory)
        ],
      );
      expect(
        n.orderedDayKeys(),
        ['2025-06-01', '2025-06-02', '2025-06-03'],
      );
    });
  });

  group('activeDayKey', () {
    test('returns today when the trip is still active (no end date)', () {
      final n = _notifier(
        dayMeta: {'2020-01-01': {}}, // a stale past day exists
      );
      expect(n.activeDayKey(), _ymd(DateTime.now()));
    });

    test('returns the last trip day when the trip has ended', () {
      final n = _notifier(
        dayMeta: {'2025-06-01': {}, '2025-06-05': {}, '2025-06-03': {}},
        tripEnd: '2025-06-05',
      );
      expect(n.activeDayKey(), '2025-06-05');
    });

    test('returns null when the trip has ended and there are no days', () {
      final n = _notifier(tripEnd: '2025-06-05');
      expect(n.activeDayKey(), isNull);
    });
  });
}
