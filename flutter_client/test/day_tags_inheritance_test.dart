// Unit tests for effectiveDayTags — the "new days inherit the previous day's
// tags" rule (issue #18). Model chosen: live fallback. A day with no tags of
// its own shows the tags of the nearest STRICTLY EARLIER day that has tags;
// empty/gap days in between are skipped; nothing is ever persisted by the
// inheritance itself.

import 'package:flutter_test/flutter_test.dart';
import 'package:viewtrip_client/src/projects/project_filter_mixin.dart';

void main() {
  Map<String, Map<String, dynamic>> meta(Map<String, List<String>> tagsByDay) =>
      {for (final e in tagsByDay.entries) e.key: {'tags': e.value}};

  group('effectiveDayTags', () {
    test('a day with its own tags shows exactly those', () {
      final m = meta({'2026-05-10': ['norway', 'with-anna']});
      expect(
        effectiveDayTags(m, '2026-05-10'),
        ['norway', 'with-anna'],
      );
    });

    test('a tagless day inherits the immediately preceding tagged day', () {
      final m = meta({'2026-05-10': ['norway']});
      // 2026-05-11 has no entry at all.
      expect(effectiveDayTags(m, '2026-05-11'), ['norway']);
    });

    test('inheritance skips empty gap days (nearest EARLIER tagged day wins)',
        () {
      final m = {
        '2026-05-10': {'tags': ['norway']},
        '2026-05-11': {'tags': <String>[]}, // materialised but untagged
        '2026-05-12': <String, dynamic>{}, // present, no tags key
      };
      expect(effectiveDayTags(m, '2026-05-12'), ['norway']);
      expect(effectiveDayTags(m, '2026-05-11'), ['norway']);
    });

    test('own tags win over an inheritable earlier day', () {
      final m = meta({
        '2026-05-10': ['norway'],
        '2026-05-12': ['sweden'],
      });
      expect(effectiveDayTags(m, '2026-05-12'), ['sweden']);
    });

    test('the LATEST earlier tagged day wins, not the earliest', () {
      final m = meta({
        '2026-05-08': ['denmark'],
        '2026-05-10': ['norway'],
      });
      expect(effectiveDayTags(m, '2026-05-15'), ['norway']);
    });

    test('a day before any tagged day inherits nothing', () {
      final m = meta({'2026-05-10': ['norway']});
      expect(effectiveDayTags(m, '2026-05-01'), isEmpty);
    });

    test('only strictly-earlier days count (same day never inherits itself)',
        () {
      final m = {
        '2026-05-10': {'tags': <String>[]},
      };
      expect(effectiveDayTags(m, '2026-05-10'), isEmpty);
    });

    test('future planned days inherit too (universe is not bounded to today)',
        () {
      final m = meta({'2027-01-01': ['ski-trip']});
      expect(effectiveDayTags(m, '2027-01-05'), ['ski-trip']);
    });

    test('empty dayMeta yields no tags', () {
      expect(effectiveDayTags(const {}, '2026-05-10'), isEmpty);
    });
  });
}
