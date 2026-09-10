// Unit tests for the rules behind the "Remove days after the end date?"
// confirmation in project settings (issue #358).
//
// The bug the confirmation had: it counted day-meta keys only, so it claimed
// days would disappear that the trip's day list pins via an activity or a
// memory. classifyTripEndOrphans splits the two so the dialog can say which
// days actually go and which stay.

import 'package:flutter_test/flutter_test.dart';
import 'package:viewtrip_client/src/projects/trip_end_days.dart';

Map<String, dynamic> _activity(String date) => {'start_date_local': date};

Map<String, dynamic> _memory(String date) => {
      'item_type': 'memory',
      'memory': {'id': 'm-$date', 'date': date},
    };

void main() {
  group('contentDayKeys', () {
    test('collects activity dates and memory dates, date part only', () {
      expect(
        contentDayKeys(
          [_activity('2026-06-14T09:30:00'), _activity('2026-06-15')],
          [_memory('2026-06-20T18:00:00'), _memory('2026-06-14')],
        ),
        {'2026-06-14', '2026-06-15', '2026-06-20'},
      );
    });

    test('ignores non-memory items and missing/empty dates', () {
      expect(
        contentDayKeys(
          [
            _activity('2026-06-14'),
            <String, dynamic>{'start_date_local': null},
            <String, dynamic>{},
          ],
          [
            {'item_type': 'journal', 'journal': {'date': '2026-07-01'}},
            {'item_type': 'encounter', 'encounter': {'date': '2026-07-02'}},
            {'item_type': 'memory', 'memory': null},
            {'item_type': 'memory', 'memory': {'date': ''}},
          ],
        ),
        {'2026-06-14'},
      );
    });
  });

  group('classifyTripEndOrphans', () {
    test('keeps the end date itself and everything before it', () {
      final o = classifyTripEndOrphans(
        dayKeys: ['2026-06-10', '2026-06-14', '2026-06-15'],
        daysWithContent: const {},
        tripEnd: '2026-06-14',
      );
      expect(o.removable, ['2026-06-15']);
      expect(o.pinned, isEmpty);
    });

    test('days after the end with an activity or memory are pinned, not removable', () {
      final o = classifyTripEndOrphans(
        dayKeys: ['2026-06-15', '2026-06-16', '2026-06-17'],
        daysWithContent: const {'2026-06-16'},
        tripEnd: '2026-06-14',
      );
      expect(o.removable, ['2026-06-15', '2026-06-17']);
      expect(o.pinned, ['2026-06-16']);
    });

    test('output is sorted and de-duplicated regardless of input order', () {
      final o = classifyTripEndOrphans(
        dayKeys: ['2026-06-17', '2026-06-15', '2026-06-17', '2026-06-16'],
        daysWithContent: const {},
        tripEnd: '2026-06-14',
      );
      expect(o.removable, ['2026-06-15', '2026-06-16', '2026-06-17']);
    });

    test('content on a day at or before the end date is irrelevant', () {
      final o = classifyTripEndOrphans(
        dayKeys: ['2026-06-13', '2026-06-14'],
        daysWithContent: const {'2026-06-13', '2026-06-14'},
        tripEnd: '2026-06-14',
      );
      expect(o.removable, isEmpty);
      expect(o.pinned, isEmpty);
    });

    test('crossing a month and a year boundary compares as dates', () {
      final o = classifyTripEndOrphans(
        dayKeys: ['2026-09-30', '2026-10-01', '2027-01-02'],
        daysWithContent: const {},
        tripEnd: '2026-09-30',
      );
      expect(o.removable, ['2026-10-01', '2027-01-02']);
    });

    test('nothing after the end date leaves both lists empty', () {
      final o = classifyTripEndOrphans(
        dayKeys: ['2026-06-01', '2026-06-02'],
        daysWithContent: const {'2026-06-02'},
        tripEnd: '2026-12-31',
      );
      expect(o.removable, isEmpty);
      expect(o.pinned, isEmpty);
    });
  });
}
