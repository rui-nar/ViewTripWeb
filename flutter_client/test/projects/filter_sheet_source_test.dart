/// The Source section of the filter sheet (issue #260, unit 6).
///
/// The sheet is where "show me only what I imported" has to be askable; the
/// section is worth screen space only once a trip actually holds more than one
/// source, because on a Strava-only trip the question has a single answer.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:viewtrip_client/src/projects/activity_panel.dart';
import 'package:viewtrip_client/src/projects/project_notifier.dart';
import 'package:viewtrip_client/src/projects/project_service.dart';

Map<String, dynamic> _activity({required int id, String? source}) => {
      'id': id,
      'name': 'An activity',
      'type': 'Ride',
      'start_date_local': '2026-06-0${id.abs()}T09:00:00',
      if (source != null) 'source': source,
    };

ProjectNotifier _notifierWith(List<Map<String, dynamic>> activities) {
  final n = ProjectNotifier(ProjectService());
  n.activities = activities;
  n.items = [
    for (final a in activities)
      {'item_type': 'activity', 'activity_id': a['id']},
  ];
  return n;
}

Future<void> _pumpSheet(WidgetTester tester, ProjectNotifier notifier,
        {bool readOnly = false}) =>
    tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: FilterSheet(notifier: notifier, readOnly: readOnly),
      ),
    ));

void main() {
  testWidgets('a mixed trip can be asked about its sources', (tester) async {
    await _pumpSheet(
        tester,
        _notifierWith([
          _activity(id: 1),
          _activity(id: -7, source: 'gpx'),
        ]));

    expect(find.text('Source'), findsOneWidget);
    // The user's words, not the column's: nobody calls a synced activity null.
    expect(find.widgetWithText(FilterChip, 'Strava'), findsOneWidget);
    expect(find.widgetWithText(FilterChip, 'GPX file'), findsOneWidget);
  });

  testWidgets('a Strava-only trip is not asked a question with one answer',
      (tester) async {
    await _pumpSheet(tester, _notifierWith([_activity(id: 1)]));

    expect(find.text('Source'), findsNothing);
  });

  testWidgets('tapping a source chip narrows the trip', (tester) async {
    final notifier = _notifierWith([
      _activity(id: 1),
      _activity(id: -7, source: 'gpx'),
    ]);
    await _pumpSheet(tester, notifier);

    await tester.tap(find.widgetWithText(FilterChip, 'GPX file'));
    await tester.pumpAndSettle();

    expect(notifier.sourceFilter, {'gpx'});
    expect(
        tester
            .widget<FilterChip>(find.widgetWithText(FilterChip, 'GPX file'))
            .selected,
        isTrue);

    // And it can be taken off again, leaving no filter behind.
    await tester.tap(find.widgetWithText(FilterChip, 'GPX file'));
    await tester.pumpAndSettle();

    expect(notifier.sourceFilter, isEmpty);
    expect(notifier.hasActiveFilter, isFalse);
  });

  testWidgets('a shared trip can read the section but not use it',
      (tester) async {
    await _pumpSheet(
        tester,
        _notifierWith([
          _activity(id: 1),
          _activity(id: -7, source: 'gpx'),
        ]),
        readOnly: true);

    expect(
        tester
            .widget<FilterChip>(find.widgetWithText(FilterChip, 'GPX file'))
            .onSelected,
        isNull);
  });
}
