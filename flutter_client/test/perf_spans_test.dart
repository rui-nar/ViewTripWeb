import 'package:flutter_test/flutter_test.dart';
import 'package:viewtrip_client/src/core/perf_timing.dart';

/// Issue #291. The span recorder is the measurement seam the whole map-load
/// plan (docs/PERF_MAP_LOAD.md) is verified against, so its aggregation and
/// its over-budget verdict are pinned here — a harness that quietly reports
/// the wrong number is worse than no harness.
void main() {
  setUp(() {
    perfSpans
      ..reset()
      ..enabled = true;
  });

  tearDown(() {
    perfSpans
      ..reset()
      ..enabled = kPerfTiming;
  });

  group('PerfSpans recording', () {
    test('disabled recorder still runs the body but records nothing', () {
      perfSpans.enabled = false;
      var ran = false;
      perfSpans.blocking('decode_geo', () => ran = true);
      expect(ran, isTrue);
      expect(perfSpans.blockingSpans, isEmpty);
    });

    test('blocking() returns the body result and records one sample', () {
      final result = perfSpans.blocking('decode_geo', () => 42);
      expect(result, 42);
      expect(perfSpans.blockingSpans['decode_geo'], hasLength(1));
    });

    test('repeated calls accumulate samples under the same name', () {
      for (var i = 0; i < 3; i++) {
        perfSpans.blocking('apply_geo', () {});
      }
      expect(perfSpans.blockingSpans['apply_geo'], hasLength(3));
    });

    test('a throwing body still records its stall, then rethrows', () {
      expect(
        () => perfSpans.blocking('decode_details', () => throw StateError('x')),
        throwsStateError,
      );
      expect(perfSpans.blockingSpans['decode_details'], hasLength(1));
    });

    test('stage() records into the wall-clock bucket, not the blocking one',
        () async {
      await perfSpans.stage('fetch_geo', () async {});
      expect(perfSpans.stageSpans['fetch_geo'], hasLength(1));
      // The distinction is the whole point: an async stage that spent its time
      // on a worker isolate costs zero frames and must never be mistaken for
      // UI-isolate stall.
      expect(perfSpans.blockingSpans, isEmpty);
    });

    test('reset clears both buckets', () async {
      perfSpans.blocking('a', () {});
      await perfSpans.stage('b', () async {});
      perfSpans.reset();
      expect(perfSpans.blockingSpans, isEmpty);
      expect(perfSpans.stageSpans, isEmpty);
    });

    test('snapshots are unmodifiable so a caller cannot corrupt the record',
        () {
      perfSpans.blocking('a', () {});
      expect(() => perfSpans.blockingSpans['a']!.add(1.0), throwsUnsupportedError);
    });
  });

  group('perfOverBudgetSpans', () {
    test('no spans over budget yields an empty list', () {
      expect(perfOverBudgetSpans(const {'a': [1.0, 2.0]}), isEmpty);
    });

    test('a span is over budget on its WORST sample, not its average', () {
      // 40ms once among fast samples is a dropped frame the user saw; an
      // average would hide it.
      expect(
        perfOverBudgetSpans(const {'decode_geo': [1.0, 1.0, 1.0, 40.0]}),
        ['decode_geo'],
      );
    });

    test('names are reported sorted so the assertion message is stable', () {
      expect(
        perfOverBudgetSpans(const {
          'z_span': [40.0],
          'a_span': [40.0],
        }),
        ['a_span', 'z_span'],
      );
    });

    test('the budget is overridable for a deliberately looser assertion', () {
      expect(perfOverBudgetSpans(const {'a': [20.0]}), ['a']);
      expect(perfOverBudgetSpans(const {'a': [20.0]}, budgetMs: 50), isEmpty);
    });

    test('exactly at budget is not over budget', () {
      expect(perfOverBudgetSpans({'a': [kFrameBudgetMs]}), isEmpty);
    });
  });

  group('perfSpanReport', () {
    test('empty spans report explicitly', () {
      expect(perfSpanReport('blocking', const {}), contains('none'));
    });

    test('reports count, total and worst per span', () {
      final line = perfSpanReport('blocking', const {
        'decode_geo': [10.0, 30.0],
      });
      expect(line, contains('decode_geo'));
      expect(line, contains('n=2'));
      expect(line, contains('total=40.0ms'));
      expect(line, contains('worst=30.0ms'));
    });

    test('worst span is listed first', () {
      final report = perfSpanReport('blocking', const {
        'cheap': [1.0],
        'expensive': [500.0],
        'middling': [50.0],
      });
      final lines = report.split('\n');
      expect(lines[1], contains('expensive'));
      expect(lines[2], contains('middling'));
      expect(lines[3], contains('cheap'));
    });
  });
}
