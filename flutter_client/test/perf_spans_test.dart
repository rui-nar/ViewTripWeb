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
      ..enabled = true;  // the library default — see PerfSpans.enabled
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

  group('perfLoadReport', () {
    // This is what a user reads off Settings -> Performance and pastes into an
    // issue, so its shape is pinned rather than incidental.
    test('carries both buckets and an explicit all-clear', () {
      final r = perfLoadReport(const {'style_markers': [0.7]},
          const {'decode_geo': [1200.0]});
      expect(r, contains('blocking (UI isolate)'));
      expect(r, contains('style_markers'));
      expect(r, contains('stages (wall clock)'));
      expect(r, contains('decode_geo'));
      // A slow *stage* is not jank: it ran on a worker. Saying so explicitly
      // is the point, otherwise a 1.2 s decode_geo reads as a problem.
      expect(r, contains('no UI-isolate span over'));
    });

    test('payload notes are rendered, sorted, when present', () {
      // A duration alone cannot tell a big payload on a slow link from a slow
      // server; the size is what disambiguates them.
      final r = perfLoadReport(const {}, const {'fetch_geo': [5263.0]},
          const {'geo': '11.4 MB', 'details': '3.2 MB'});
      expect(r, contains('payloads'));
      expect(r.indexOf('details'), lessThan(r.indexOf('geo  11.4 MB')));
      expect(r, contains('11.4 MB'));
    });

    test('no payloads section when nothing was noted', () {
      expect(perfLoadReport(const {}, const {'a': [1.0]}), isNot(contains('payloads')));
    });

    test('note() is a no-op while recording is disabled', () {
      perfSpans.enabled = false;
      perfSpans.note('geo', '1 MB');
      expect(perfSpans.notes, isEmpty);
    });

    test('names the over-budget spans when there are any', () {
      final r = perfLoadReport(const {'build_specs': [480.0]}, const {});
      expect(r, contains('OVER BUDGET'));
      expect(r, contains('build_specs'));
    });
  });

  group('stage failures', () {
    // A span timed in a finally is written whether the body returned or threw,
    // so duration alone cannot tell a failing fetch from a slow one. On issue
    // #276 that ambiguity was the whole problem: fetch_geo showed 5.1 s twice
    // with no decode after it, and the report could not say why.
    test('a failed stage is recorded as a failure, and still rethrows',
        () async {
      await expectLater(
        perfSpans.stage('fetch_geo', () async => throw StateError('boom')),
        throwsStateError,
      );
      expect(perfSpans.failures['fetch_geo'], hasLength(1));
      expect(perfSpans.failures['fetch_geo']!.single, contains('boom'));
      // The duration is still recorded — a failure has a duration too.
      expect(perfSpans.stageSpans['fetch_geo'], hasLength(1));
    });

    test('a successful stage records no failure', () async {
      await perfSpans.stage('fetch_geo', () async => 1);
      expect(perfSpans.failures, isEmpty);
    });

    test('repeated failures accumulate, newest last', () async {
      for (final msg in ['first', 'second']) {
        try {
          await perfSpans.stage('fetch_details', () async => throw StateError(msg));
        } on StateError {
          // expected
        }
      }
      expect(perfSpans.failures['fetch_details'], hasLength(2));
      expect(perfSpans.failures['fetch_details']!.last, contains('second'));
    });

    test('reset clears failures', () async {
      try {
        await perfSpans.stage('x', () async => throw StateError('e'));
      } on StateError {
        // expected
      }
      perfSpans.reset();
      expect(perfSpans.failures, isEmpty);
    });
  });

  group('perfDescribeError', () {
    test('collapses whitespace to one line', () {
      expect(perfDescribeError('a\n  b'), 'a b');
    });

    test('truncates something very long', () {
      final d = perfDescribeError('x' * 500);
      expect(d.length, 120);
      expect(d, endsWith('...'));
    });
  });

  group('failure reporting', () {
    test('failures are called out, with the last error', () {
      final r = perfFullReport(const {}, const {'fetch_geo': [5081.0, 38.0]},
          const {}, failures: const {'fetch_geo': ['ApiException(504)', 'ApiException(504)']});
      expect(r, contains('FAILURES'));
      expect(r, contains('fetch_geo'));
      expect(r, contains('x2'));
      expect(r, contains('504'));
    });

    test('no failures section when everything succeeded', () {
      expect(perfFullReport(const {}, const {'fetch_geo': [10.0]}, const {}),
          isNot(contains('FAILURES')));
    });
  });

  group('gesture-scoped blocking', () {
    test('work outside a gesture is not attributed to one', () {
      perfSpans.blocking('activity_panel_build', () {});
      expect(perfSpans.blockingSpans['activity_panel_build'], hasLength(1));
      expect(perfSpans.gestureBlockingSpans, isEmpty);
    });

    test('work during a gesture lands in both buckets', () {
      perfSpans.beginGesture();
      perfSpans.blocking('activity_panel_build', () {});
      perfSpans.endGesture();
      perfSpans.blocking('activity_panel_build', () {});
      expect(perfSpans.blockingSpans['activity_panel_build'], hasLength(2));
      expect(perfSpans.gestureBlockingSpans['activity_panel_build'],
          hasLength(1),
          reason: 'session totals cannot say which work happens while panning');
    });

    test('reset clears the gesture bucket', () {
      perfSpans.beginGesture();
      perfSpans.blocking('x', () {});
      perfSpans.reset();
      expect(perfSpans.gestureBlockingSpans, isEmpty);
    });
  });

  group('stall reporting', () {
    // The number that corresponds to a freeze. Frames that never happen leave
    // no timing behind, so build/raster percentiles stay survivable through an
    // ANR; a late timer tick measures the block directly.
    test('a stall is reported, split by whether the user was panning', () {
      final r = perfFullReport(const {}, const {}, const {},
          worstStallMs: 5200, worstGestureStallMs: 5200);
      expect(r, contains('worst event-loop stall'));
      expect(r, contains('5200ms overall'));
      expect(r, contains('5200ms while panning'));
    });

    test('no stall line when nothing stalled', () {
      expect(perfFullReport(const {}, const {'a': [1.0]}, const {}),
          isNot(contains('event-loop stall')));
    });

    test('gesture-scoped blocking is reported under the gesture section', () {
      final r = perfFullReport(const {}, const {}, const {},
          gestures: 3,
          gestureBuild: const [5.0],
          gestureRaster: const [5.0],
          gestureBlocking: const {'elevation_chart_build': [40.0]});
      expect(r, contains('blocking DURING gestures'));
      expect(r, contains('elevation_chart_build'));
    });
  });

  group('gesture frames', () {
    test('nothing is recorded until a gesture begins', () {
      expect(perfSpans.gestureFrames.gestures, 0);
      expect(perfSpans.gestureFrames.build, isEmpty);
    });

    test('beginGesture counts a gesture; repeats do not double-count', () {
      perfSpans.beginGesture();
      perfSpans.beginGesture(); // a second camera event in the same drag
      expect(perfSpans.gestureFrames.gestures, 1);
      perfSpans.endGesture();
      perfSpans.beginGesture();
      expect(perfSpans.gestureFrames.gestures, 2);
    });

    test('a disabled recorder counts nothing', () {
      perfSpans.enabled = false;
      perfSpans.beginGesture();
      expect(perfSpans.gestureFrames.gestures, 0);
    });

    test('reset clears gesture state too', () {
      perfSpans.beginGesture();
      perfSpans.reset();
      expect(perfSpans.gestureFrames.gestures, 0);
    });
  });

  group('perfFullReport', () {
    test('omits the gesture section when nothing panned', () {
      expect(perfFullReport(const {}, const {'a': [1.0]}, const {}),
          isNot(contains('map gestures')));
    });

    test('reports gesture frames when there are any', () {
      // A pan that drops frames must be visible even when every load span is
      // comfortably under budget — that combination is exactly what issue
      // #276 turned out to be.
      final r = perfFullReport(
        const {'build_specs': [12.0]},
        const {},
        const {},
        gestures: 2,
        gestureBuild: const [4.0, 90.0, 5.0],
        gestureRaster: const [3.0, 6.0, 4.0],
      );
      expect(r, contains('map gestures: 2'));
      expect(r, contains('frames=3'));
      expect(r, contains('janky'));
      expect(r, isNot(contains('OVER BUDGET')),
          reason: 'the load was fine; the gesture was not — they must not be '
              'conflated');
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
