// Regression test for issue #358: "setting a trip end date triggered a warning
// that some days would be deleted but those days are still in the trip".
//
// ProjectSettingsScreen._save() used to write day-meta twice: once with the
// pruned map right after the confirmation, then again — unconditionally, a few
// lines later — with `_dayMeta`, the deep copy taken in initState() and never
// pruned. Both the client notifier and the server's PUT /day-meta replace the
// whole map, so the second write put every "deleted" day straight back.
//
// These tests drive the real screen and assert on the day-meta bodies that
// actually reach the wire.
//
// The last group covers issue #372: the pin oracle now comes from the server
// (GET /content-days), because a day another member's journal keeps on screen
// is invisible to the caller's own item list.

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

import 'package:viewtrip_client/src/api/client.dart';
import 'package:viewtrip_client/src/core/project_ref.dart';
import 'package:viewtrip_client/src/projects/project_notifier.dart';
import 'package:viewtrip_client/src/projects/project_service.dart';
import 'package:viewtrip_client/src/projects/project_settings_screen.dart';

/// Every day-meta map PUT during a test, in order.
late List<Map<String, dynamic>> putDayMeta;

/// What GET /content-days answers — the days the trip holds content on for
/// *any* member (issue #372). [contentDaysFail] makes the request fail
/// instead, which must never let a day be deleted.
late List<String> serverContentDays;
late bool contentDaysFail;

ApiClient _recordingApi() => ApiClient(
      httpClient: MockClient((req) async {
        if (req.method == 'PUT' && req.url.path.endsWith('/day-meta')) {
          final body = jsonDecode(req.body) as Map<String, dynamic>;
          putDayMeta.add(body['day_meta'] as Map<String, dynamic>);
          return http.Response('', 204);
        }
        if (req.method == 'GET' && req.url.path.endsWith('/content-days')) {
          if (contentDaysFail) return http.Response('boom', 500);
          return http.Response(jsonEncode({'days': serverContentDays}), 200);
        }
        if (req.method == 'GET' && req.url.path.endsWith('/polarsteps/trips')) {
          return http.Response('[]', 200);
        }
        // Everything else the screen touches on open/save (share visitors,
        // project PUT, track style, languages, sync-meta) is irrelevant here.
        return http.Response('{}', 200);
      }),
    );

ProjectNotifier _notifier({
  required Map<String, Map<String, dynamic>> dayMeta,
  String? tripEnd,
  List<Map<String, dynamic>> activities = const [],
  List<Map<String, dynamic>> items = const [],
}) {
  final n = ProjectNotifier(ProjectService())
    ..ref = const ProjectRef(name: 'Trip')
    ..tripStart = '2026-06-01'
    ..tripEnd = tripEnd
    ..dayMeta = dayMeta
    ..activities = List<Map<String, dynamic>>.from(activities)
    ..items = List<Map<String, dynamic>>.from(items);
  return n;
}

/// Pumps a fixed number of frames. The settle helper can't be used past the
/// Save tap: _save() holds _saving = true, and the save button then shows a
/// CircularProgressIndicator, which never stops animating.
Future<void> _frames(WidgetTester tester, [int n = 8]) async {
  for (var i = 0; i < n; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> _pumpSettings(WidgetTester tester, ProjectNotifier n) async {
  // Under 600 logical px the settings sidebar renders icon-only. That avoids
  // a pre-existing label overflow in the wide sidebar that only appears under
  // the test font, and is unrelated to what these tests check.
  tester.view.physicalSize = const Size(520, 1000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final router = GoRouter(routes: [
    GoRoute(
      path: '/',
      builder: (_, __) => const Scaffold(body: Text('home')),
      routes: [
        GoRoute(
          path: 'settings',
          builder: (_, __) => const ProjectSettingsScreen(projectName: 'Trip'),
        ),
      ],
    ),
  ]);
  await tester.pumpWidget(ChangeNotifierProvider<ProjectNotifier>.value(
    value: n,
    child: MaterialApp.router(routerConfig: router),
  ));
  router.go('/settings');
  await _frames(tester);
}

Future<void> _tapSave(WidgetTester tester) async {
  await tester.tap(find.byTooltip('Save'));
  await _frames(tester);
}

/// Moves the trip-end chip labelled [from] to [day] of the month it opens on.
/// The informational half of the warning only fires when the end date is
/// actually set or moved, so tests for it have to go through the picker.
Future<void> _moveEndDate(
    WidgetTester tester, String from, String day) async {
  await tester.tap(find.text(from));
  await _frames(tester);
  await tester.tap(find.descendant(
    of: find.byType(DatePickerDialog),
    matching: find.text(day),
  ));
  await _frames(tester);
  await tester.tap(find.text('OK'));
  await _frames(tester);
}

Map<String, Map<String, dynamic>> _days(List<String> keys) => {
      for (final k in keys) k: <String, dynamic>{'note': 'note for $k'},
    };

void main() {
  late ApiClient realApi;

  setUp(() {
    putDayMeta = [];
    serverContentDays = [];
    contentDaysFail = false;
    realApi = api;
    api = _recordingApi();
  });
  tearDown(() => api = realApi);

  testWidgets('confirming the warning really removes the days after the end date',
      (tester) async {
    final n = _notifier(
      tripEnd: '2026-06-14',
      dayMeta: _days([
        '2026-06-13',
        '2026-06-14',
        '2026-06-15',
        '2026-06-16',
      ]),
    );
    await _pumpSettings(tester, n);

    await _tapSave(tester);

    expect(find.text('Remove days after the end date?'), findsOneWidget);
    expect(find.textContaining('2 days after Jun 14, 2026'), findsOneWidget);

    await tester.tap(find.text('Delete'));
    await _frames(tester);

    // The bug: a first PUT dropped the two days, a second PUT restored them.
    // Whatever the number of writes, none may reintroduce a pruned day, and
    // the last state on the wire must be the pruned one.
    expect(putDayMeta, isNotEmpty);
    for (final body in putDayMeta) {
      expect(body.keys, isNot(contains('2026-06-15')));
      expect(body.keys, isNot(contains('2026-06-16')));
    }
    expect(putDayMeta.last.keys.toSet(), {'2026-06-13', '2026-06-14'});
    expect(n.dayMeta.keys, isNot(contains('2026-06-15')));
  });

  testWidgets('cancelling the warning writes no day-meta at all', (tester) async {
    final n = _notifier(
      tripEnd: '2026-06-14',
      dayMeta: _days(['2026-06-14', '2026-06-15']),
    );
    await _pumpSettings(tester, n);

    await _tapSave(tester);
    await tester.tap(find.text('Cancel'));
    await _frames(tester);

    expect(putDayMeta, isEmpty);
    expect(n.dayMeta.keys, contains('2026-06-15'));
  });

  testWidgets('a day after the end date pinned by an activity is reported as staying',
      (tester) async {
    final n = _notifier(
      tripEnd: '2026-06-14',
      dayMeta: _days(['2026-06-14', '2026-06-15', '2026-06-16']),
      activities: [
        {'start_date_local': '2026-06-16T08:00:00'},
      ],
    );
    await _pumpSettings(tester, n);

    await _tapSave(tester);

    // Only 06-15 actually disappears; 06-16 is pinned by its activity and the
    // dialog says so instead of over-promising.
    expect(find.textContaining('1 day after Jun 14, 2026'), findsOneWidget);
    expect(find.textContaining('1 later day'), findsOneWidget);

    await tester.tap(find.text('Delete'));
    await _frames(tester);

    expect(putDayMeta.last.keys.toSet(), {'2026-06-14', '2026-06-16'});
  });

  testWidgets('no end date means no warning and no pruning', (tester) async {
    final n = _notifier(
      dayMeta: _days(['2026-06-14', '2026-06-15']),
    );
    await _pumpSettings(tester, n);

    await _tapSave(tester);

    expect(find.text('Remove days after the end date?'), findsNothing);
    expect(putDayMeta.last.keys.toSet(), {'2026-06-14', '2026-06-15'});
  });

  testWidgets('a journal-only day past the end date keeps its day-meta', (tester) async {
    // The first review catch: contentDayKeys used to count memories only, so a
    // day held on screen by a journal entry was classified removable — the
    // dialog promised it would go, its notes were wiped, and the day still
    // rendered.
    final n = _notifier(
      tripEnd: '2026-06-20',
      dayMeta: _days(['2026-06-14', '2026-06-15']),
      items: [
        {'item_type': 'journal', 'journal': {'id': 'j1', 'date': '2026-06-15'}},
      ],
    );
    await _pumpSettings(tester, n);
    await _moveEndDate(tester, 'Jun 20, 2026', '14');

    await _tapSave(tester);

    expect(find.text('Days after the end date will stay'), findsOneWidget);
    expect(find.textContaining('1 day after Jun 14, 2026'), findsOneWidget);
    expect(find.text('Delete'), findsNothing);

    await tester.tap(find.text('Continue'));
    await _frames(tester);

    expect(putDayMeta.last.keys.toSet(), {'2026-06-14', '2026-06-15'});
  });

  testWidgets('moving the end date over a fully pinned set warns instead of saving silently',
      (tester) async {
    final n = _notifier(
      tripEnd: '2026-06-20',
      dayMeta: _days(['2026-06-14', '2026-06-15']),
      activities: [
        {'start_date_local': '2026-06-15T08:00:00'},
      ],
    );
    await _pumpSettings(tester, n);
    await _moveEndDate(tester, 'Jun 20, 2026', '14');

    await _tapSave(tester);
    expect(find.text('Days after the end date will stay'), findsOneWidget);

    // Cancelling an informational warning must still abort the save.
    await tester.tap(find.text('Cancel'));
    await _frames(tester);
    expect(putDayMeta, isEmpty);
  });

  testWidgets('an unrelated save is not blocked by days that can only stay',
      (tester) async {
    // The second review catch: warning about pinned-only days on every save
    // raised a dialog nothing could ever satisfy — and cancelling it (the
    // natural response when you came to change a colour) threw the edit away.
    final n = _notifier(
      tripEnd: '2026-06-14',
      dayMeta: _days(['2026-06-14', '2026-06-15']),
      activities: [
        {'start_date_local': '2026-06-15T08:00:00'},
      ],
    );
    await _pumpSettings(tester, n);

    await _tapSave(tester);

    expect(find.text('Days after the end date will stay'), findsNothing);
    expect(find.text('Remove days after the end date?'), findsNothing);
    expect(putDayMeta.last.keys.toSet(), {'2026-06-14', '2026-06-15'});
  });

  testWidgets('a journal-only day with no day-meta is still reported as staying',
      (tester) async {
    // Third review catch: the pin oracle counted journal/encounter/segment
    // days but the candidate set did not, so a day held on screen by a
    // journal alone — with no day-meta row of its own — was classified
    // neither removable nor pinned, and the warning never mentioned it.
    final n = _notifier(
      tripEnd: '2026-06-20',
      dayMeta: _days(['2026-06-14']),
      items: [
        {'item_type': 'journal', 'journal': {'id': 'j1', 'date': '2026-06-15'}},
      ],
    );
    await _pumpSettings(tester, n);
    await _moveEndDate(tester, 'Jun 20, 2026', '14');

    await _tapSave(tester);

    expect(find.text('Days after the end date will stay'), findsOneWidget);
    expect(find.textContaining('1 day after Jun 14, 2026'), findsOneWidget);

    await tester.tap(find.text('Continue'));
    await _frames(tester);

    expect(putDayMeta.last.keys.toSet(), {'2026-06-14'});
  });

  // ── Issue #372: content the caller cannot see ───────────────────────────────

  testWidgets('a day pinned only by a journal the caller cannot see is kept',
      (tester) async {
    // Journals are per-user server-side, so the caller's own item list shows
    // nothing on 06-16 — only GET /content-days knows the companion wrote
    // there. Classified locally, the day was "removable" and confirming the
    // warning wiped its shared notes while it still rendered for its author.
    final n = _notifier(
      tripEnd: '2026-06-14',
      dayMeta: _days(['2026-06-14', '2026-06-15', '2026-06-16']),
    );
    serverContentDays = ['2026-06-16'];
    await _pumpSettings(tester, n);

    await _tapSave(tester);

    expect(find.textContaining('1 day after Jun 14, 2026'), findsOneWidget);
    expect(find.textContaining('1 later day'), findsOneWidget);

    await tester.tap(find.text('Delete'));
    await _frames(tester);

    expect(putDayMeta.last.keys.toSet(), {'2026-06-14', '2026-06-16'});
    expect(n.dayMeta.keys, contains('2026-06-16'));
  });

  testWidgets('a failed content check deletes nothing', (tester) async {
    // Fail safe: with the check unanswered the caller-local view is the one
    // thing that must not decide — it is blind to exactly the content this
    // endpoint exists to report.
    final n = _notifier(
      tripEnd: '2026-06-14',
      dayMeta: _days(['2026-06-14', '2026-06-15', '2026-06-16']),
    );
    contentDaysFail = true;
    await _pumpSettings(tester, n);

    await _tapSave(tester);

    expect(find.text('Remove days after the end date?'), findsNothing);
    expect(putDayMeta.last.keys.toSet(),
        {'2026-06-14', '2026-06-15', '2026-06-16'});
  });

  testWidgets('a failed content check says so when the end date moves',
      (tester) async {
    final n = _notifier(
      tripEnd: '2026-06-20',
      dayMeta: _days(['2026-06-14', '2026-06-15']),
    );
    contentDaysFail = true;
    await _pumpSettings(tester, n);
    await _moveEndDate(tester, 'Jun 20, 2026', '14');

    await _tapSave(tester);

    expect(find.text('Days after the end date will stay'), findsOneWidget);
    expect(find.textContaining('could not be checked'), findsOneWidget);
    expect(find.text('Delete'), findsNothing);

    await tester.tap(find.text('Continue'));
    await _frames(tester);

    expect(putDayMeta.last.keys.toSet(), {'2026-06-14', '2026-06-15'});
  });

  testWidgets('a day only the server knows about is still reported as staying',
      (tester) async {
    // Integration gap found merging #370 and #372: the candidate set must
    // spread the server's answer, not just the caller-visible sources. A day
    // held on screen by another member's journal and carrying no day-meta of
    // its own appears in *none* of _dayMeta, orderedDayKeys() or the local
    // extraction — drop `...?serverDays` from the candidates and it is
    // silently left out of the dialog, since classifyTripEndOrphans only
    // reports days it is handed. Nothing is mis-deleted (there is no day-meta
    // to delete), but the warning under-reports, which is the defect class
    // #358 was about.
    serverContentDays = ['2026-06-15'];
    final n = _notifier(
      tripEnd: '2026-06-20',
      dayMeta: _days(['2026-06-14']),
    );
    await _pumpSettings(tester, n);
    await _moveEndDate(tester, 'Jun 20, 2026', '14');

    await _tapSave(tester);

    expect(find.text('Days after the end date will stay'), findsOneWidget);
    expect(find.textContaining('1 day after Jun 14, 2026'), findsOneWidget);

    await tester.tap(find.text('Continue'));
    await _frames(tester);

    expect(putDayMeta.last.keys.toSet(), {'2026-06-14'});
  });
}
