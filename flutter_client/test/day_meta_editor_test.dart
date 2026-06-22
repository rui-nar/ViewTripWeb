import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';

import 'package:viewtrip_client/src/core/design_tokens.dart';
import 'package:viewtrip_client/src/projects/day_meta_editor.dart';

/// Pumps a bare [DayMetaEditor] and returns the meta captured by the most
/// recent onSave. Edits make the editor dirty, which enables "Save day".
class _Harness {
  Map<String, dynamic>? saved;
}

Future<_Harness> _pump(
  WidgetTester tester, {
  Map<String, dynamic> initialMeta = const {},
  List<String> sleepingOptions = const [],
  Map<String, String> sleepingOptionGroups = const {},
  List<String> availableTags = const [],
  List<Map<String, dynamic>> counters = const [],
  int dayNumber = 21,
  int totalDays = 47,
  List<String> effectiveTags = const [],
  double distanceKm = 0,
  double elevationM = 0,
}) async {
  final h = _Harness();
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: SafeArea(
        child: DayMetaEditor(
          dateKey: '2026-06-14',
          initialMeta: initialMeta,
          sleepingOptions: sleepingOptions,
          sleepingOptionGroups: sleepingOptionGroups,
          availableTags: availableTags,
          counters: counters,
          dayNumber: dayNumber,
          totalDays: totalDays,
          date: DateTime(2026, 6, 14),
          effectiveTags: effectiveTags,
          distanceKm: distanceKm,
          elevationM: elevationM,
          onSave: (m) => h.saved = m,
        ),
      ),
    ),
  ));
  return h;
}

bool _saveEnabled(WidgetTester tester) {
  final btn = tester.widget<TextButton>(
    find.ancestor(of: find.text('Save day'), matching: find.byType(TextButton)),
  );
  return btn.onPressed != null;
}

Future<void> _tapSave(WidgetTester tester) async {
  await tester.tap(find.text('Save day'));
  await tester.pump();
}

/// Scrolls a body control into view (the modal body is scrollable) then taps it.
Future<void> _tapVisible(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
  await tester.tap(finder);
  await tester.pump();
}

void main() {
  // Avoid network font fetches during tests — fall back to a bundled font.
  setUpAll(() => GoogleFonts.config.allowRuntimeFetching = false);

  group('Edit Day hero', () {
    testWidgets('shows day number, progress and dist/climb', (tester) async {
      await _pump(tester,
          dayNumber: 21, totalDays: 47, distanceKm: 88, elevationM: 276);

      expect(find.text('21'), findsOneWidget); // big mono day number
      expect(find.text('21 / 47'), findsOneWidget); // progress label
      expect(find.text('DIST'), findsOneWidget);
      expect(find.text('88'), findsOneWidget);
      expect(find.text('CLIMB'), findsOneWidget);
      expect(find.text('276'), findsOneWidget);
    });

    testWidgets('hides the stat strip when the day has no activity', (tester) async {
      await _pump(tester, distanceKm: 0, elevationM: 0);
      expect(find.text('DIST'), findsNothing);
      expect(find.text('CLIMB'), findsNothing);
    });

    testWidgets('renders effective tags as the hero context', (tester) async {
      await _pump(tester, effectiveTags: ['EV10 — North Cape']);
      expect(find.text('EV10 — North Cape'), findsOneWidget);
    });
  });

  group('Chip groups', () {
    testWidgets('selecting difficulty puts the value in saved meta', (tester) async {
      final h = await _pump(tester);
      expect(_saveEnabled(tester), isFalse); // clean → disabled

      await tester.tap(find.text('Hard'));
      await tester.pump();
      expect(_saveEnabled(tester), isTrue);

      await _tapSave(tester);
      expect(h.saved!['difficulty'], 'hard');
    });

    testWidgets('the dashed "Not set" chip clears a value', (tester) async {
      final h = await _pump(tester, initialMeta: {'difficulty': 'hard'});
      // First "Not set" belongs to the Difficulty group (first section).
      await tester.tap(find.text('Not set').first);
      await tester.pump();
      await _tapSave(tester);
      expect(h.saved!.containsKey('difficulty'), isFalse);
    });

    testWidgets('sleeping chips carry their category dot colour', (tester) async {
      await _pump(tester,
          sleepingOptions: ['Hotel', 'Camping'],
          sleepingOptionGroups: {'Hotel': 'Indoors', 'Camping': 'Outdoors'});

      Finder dot(Color c) => find.byWidgetPredicate((w) =>
          w is Container &&
          w.decoration is BoxDecoration &&
          (w.decoration as BoxDecoration).color == c &&
          (w.decoration as BoxDecoration).shape == BoxShape.circle);

      expect(dot(kSleepIndoors), findsOneWidget); // Hotel
      expect(dot(kSleepOutdoors), findsOneWidget); // Camping
    });
  });

  group('Tags', () {
    testWidgets('tapping a tag toggles it into saved meta', (tester) async {
      final h = await _pump(tester, availableTags: ['EV6']);
      await _tapVisible(tester, find.text('EV6'));
      await _tapSave(tester);
      expect(h.saved!['tags'], ['EV6']);
    });

    testWidgets('a tag can be toggled back off', (tester) async {
      final h = await _pump(tester,
          availableTags: ['EV6'], initialMeta: {'tags': ['EV6']});
      await _tapVisible(tester, find.text('EV6')); // toggle off
      await _tapSave(tester);
      expect(h.saved!.containsKey('tags'), isFalse);
    });

    testWidgets('a new tag is added via the field + Add', (tester) async {
      final h = await _pump(tester);
      await tester.enterText(find.widgetWithText(TextField, 'New tag…'), 'Transfer');
      await _tapVisible(tester, find.text('Add'));
      await _tapSave(tester);
      expect(h.saved!['tags'], ['Transfer']);
    });
  });

  group('Counters', () {
    testWidgets('the + stepper increments the saved amount', (tester) async {
      final h = await _pump(tester,
          counters: [{'name': 'Snacks'}],
          initialMeta: {'counters': {'Snacks': 3}});

      expect(find.text('3'), findsOneWidget);
      await _tapVisible(tester, find.byKey(const ValueKey('ctr_inc_Snacks')));
      expect(find.text('4'), findsOneWidget);

      await _tapSave(tester);
      expect((h.saved!['counters'] as Map)['Snacks'], 4.0);
    });

    testWidgets('"Add counter" adds an unused vocabulary counter', (tester) async {
      final h = await _pump(tester, counters: [{'name': 'Snacks'}]);
      await _tapVisible(tester, find.text('Add counter'));
      await _tapSave(tester);
      expect((h.saved!['counters'] as Map).containsKey('Snacks'), isTrue);
    });

    testWidgets('removing a counter drops it from saved meta', (tester) async {
      final h = await _pump(tester,
          counters: [{'name': 'Snacks'}],
          initialMeta: {'counters': {'Snacks': 3}});
      await _tapVisible(tester, find.byTooltip('Remove counter'));
      await _tapSave(tester);
      expect(h.saved!.containsKey('counters'), isFalse);
    });
  });

  group('Footer', () {
    testWidgets('empty + clean shows "Nothing to save yet" with Save disabled',
        (tester) async {
      await _pump(tester);
      expect(find.text('Nothing to save yet'), findsOneWidget);
      expect(_saveEnabled(tester), isFalse);
    });

    testWidgets('an edit flips the status to "Unsaved changes" and enables Save',
        (tester) async {
      await _pump(tester);
      await tester.tap(find.text('Normal'));
      await tester.pump();
      expect(find.text('Unsaved changes'), findsOneWidget);
      expect(_saveEnabled(tester), isTrue);
    });
  });
}
