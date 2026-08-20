import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:viewtrip_client/src/projects/day_carousel.dart';
import 'package:viewtrip_client/src/projects/project_notifier.dart';
import 'package:viewtrip_client/src/projects/project_service.dart';

/// Issue #199: view-mode vertical day carousel. Covers the pure
/// index→day-key selection mapping, the day-number/distance/climb labels
/// (sourced from the same `dayTripNumbering`/`dayStats` the manage-mode day
/// hero and map selection overlay already use), the responsive compact
/// breakpoint, the rounded-right-corners shape, and the idle dim/retract.
void main() {
  ProjectNotifier notifierWithThreeDays() {
    final n = ProjectNotifier(ProjectService());
    n.activities = [
      {
        'id': 1,
        'distance': 10000, // 10 km
        'total_elevation_gain': 250,
        'start_date_local': '2026-06-01T08:00:00',
      },
      {
        'id': 2,
        'distance': 5000, // 5 km
        'total_elevation_gain': 100,
        'start_date_local': '2026-06-03T08:00:00',
      },
    ];
    n.items = [
      {'item_type': 'activity', 'activity_id': 1},
      {
        'item_type': 'memory',
        'memory': {'id': 1, 'date': '2026-06-02'},
      },
      {'item_type': 'activity', 'activity_id': 2},
    ];
    return n;
  }

  Future<ProjectNotifier> pumpCarousel(WidgetTester tester, Size size) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final notifier = notifierWithThreeDays();
    await tester.pumpWidget(
      ChangeNotifierProvider<ProjectNotifier>.value(
        value: notifier,
        child: MaterialApp(
          // SizedBox.expand mirrors the tight height DayCarousel gets in
          // production from the stretch-aligned Row in view_screen.dart —
          // ListWheelScrollView needs a bounded height to lay out.
          home: Scaffold(
              body: SizedBox.expand(child: DayCarousel(notifier: notifier))),
        ),
      ),
    );
    await tester.pump();
    return notifier;
  }

  group('dayCarouselSelection', () {
    test('maps a valid index to the day key at that position', () {
      final days = ['2026-06-01', '2026-06-02', '2026-06-03'];
      expect(dayCarouselSelection(0, days), '2026-06-01');
      expect(dayCarouselSelection(2, days), '2026-06-03');
    });

    test('returns null for an out-of-range index', () {
      final days = ['2026-06-01', '2026-06-02'];
      expect(dayCarouselSelection(-1, days), isNull);
      expect(dayCarouselSelection(2, days), isNull);
    });
  });

  testWidgets('wide layout: shows day number, distance and climb per day',
      (tester) async {
    await pumpCarousel(tester, const Size(1200, 900));

    expect(find.text('1'), findsOneWidget);
    expect(find.text('10 km'), findsOneWidget);
    expect(find.text('250 m'), findsOneWidget);

    expect(find.text('2'), findsOneWidget);
    // Day 2 has a memory only — no activity distance/climb.
    expect(find.text('0 km'), findsOneWidget);
    expect(find.text('0 m'), findsOneWidget);

    expect(find.text('3'), findsOneWidget);
    expect(find.text('5 km'), findsOneWidget);
    expect(find.text('100 m'), findsOneWidget);
  });

  testWidgets('narrow layout: compact strip hides distance/climb',
      (tester) async {
    await pumpCarousel(tester, const Size(360, 800));

    expect(find.text('1'), findsOneWidget);
    expect(find.text('10 km'), findsNothing);
    expect(find.text('250 m'), findsNothing);
  });

  testWidgets('dragging the carousel updates the notifier\'s selected day',
      (tester) async {
    final notifier = await pumpCarousel(tester, const Size(1200, 900));
    expect(notifier.selectedDays, isEmpty);

    // Large drag guarantees landing on the last day regardless of the
    // wheel's magnification curvature.
    await tester.drag(find.byType(ListWheelScrollView), const Offset(0, -1000));
    await tester.pumpAndSettle();

    expect(notifier.selectedDays, {'2026-06-03'});
  });

  testWidgets('carousel has rounded top-right/bottom-right corners only',
      (tester) async {
    await pumpCarousel(tester, const Size(1200, 900));

    final container = tester.widget<Container>(find.descendant(
      of: find.byType(DayCarousel),
      matching: find.byWidgetPredicate(
          (w) => w is Container && w.decoration is BoxDecoration),
    ));
    final radius =
        (container.decoration as BoxDecoration).borderRadius as BorderRadius;
    expect(radius.topRight, const Radius.circular(12));
    expect(radius.bottomRight, const Radius.circular(12));
    expect(radius.topLeft, Radius.zero);
    expect(radius.bottomLeft, Radius.zero);
  });

  testWidgets('idle-dims and retracts, then reveals again on tap',
      (tester) async {
    await pumpCarousel(tester, const Size(1200, 900));

    // Freshly mounted: fully revealed.
    expect(
      tester.widget<AnimatedOpacity>(find.byType(AnimatedOpacity)).opacity,
      1.0,
    );

    // Cross the idle delay (fires the retract Timer + its setState), then
    // let the resulting opacity/slide animation finish — two separate pumps,
    // since the animation's own ticker only starts once the Timer callback
    // above has run.
    await tester.pump(const Duration(seconds: 3, milliseconds: 50));
    await tester.pump(const Duration(milliseconds: 300));
    expect(
      tester.widget<AnimatedOpacity>(find.byType(AnimatedOpacity)).opacity,
      lessThan(1.0),
    );
    expect(
      tester.widget<AnimatedSlide>(find.byType(AnimatedSlide)).offset.dx,
      greaterThan(0),
    );

    // Tapping the dimmed strip reveals it again.
    await tester.tap(find.byType(DayCarousel));
    await tester.pump();
    expect(
      tester.widget<AnimatedOpacity>(find.byType(AnimatedOpacity)).opacity,
      1.0,
    );
  });

  testWidgets('renders nothing when the project has no days', (tester) async {
    final notifier = ProjectNotifier(ProjectService());
    await tester.pumpWidget(
      ChangeNotifierProvider<ProjectNotifier>.value(
        value: notifier,
        child: MaterialApp(
          home: Scaffold(body: DayCarousel(notifier: notifier)),
        ),
      ),
    );

    expect(find.byType(ListWheelScrollView), findsNothing);
  });
}
