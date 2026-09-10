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

ApiClient _recordingApi() => ApiClient(
      httpClient: MockClient((req) async {
        if (req.method == 'PUT' && req.url.path.endsWith('/day-meta')) {
          final body = jsonDecode(req.body) as Map<String, dynamic>;
          putDayMeta.add(body['day_meta'] as Map<String, dynamic>);
          return http.Response('', 204);
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

Map<String, Map<String, dynamic>> _days(List<String> keys) => {
      for (final k in keys) k: <String, dynamic>{'note': 'note for $k'},
    };

void main() {
  late ApiClient realApi;

  setUp(() {
    putDayMeta = [];
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
    // The review catch: contentDayKeys used to count memories only, so a day
    // held on screen by a journal entry was classified removable — the dialog
    // promised it would go, its notes were wiped, and the day still rendered.
    final n = _notifier(
      tripEnd: '2026-06-14',
      dayMeta: _days(['2026-06-14', '2026-06-15']),
      items: [
        {'item_type': 'journal', 'journal': {'id': 'j1', 'date': '2026-06-15'}},
      ],
    );
    await _pumpSettings(tester, n);

    await _tapSave(tester);

    expect(find.text('Days after the end date will stay'), findsOneWidget);
    expect(find.textContaining('1 day after Jun 14, 2026'), findsOneWidget);
    expect(find.text('Delete'), findsNothing);

    await tester.tap(find.text('Continue'));
    await _frames(tester);

    expect(putDayMeta.last.keys.toSet(), {'2026-06-14', '2026-06-15'});
  });

  testWidgets('a fully pinned set still warns instead of saving silently', (tester) async {
    final n = _notifier(
      tripEnd: '2026-06-14',
      dayMeta: _days(['2026-06-14', '2026-06-15']),
      activities: [
        {'start_date_local': '2026-06-15T08:00:00'},
      ],
    );
    await _pumpSettings(tester, n);

    await _tapSave(tester);

    expect(find.text('Days after the end date will stay'), findsOneWidget);

    // Cancelling an informational warning must still abort the save.
    await tester.tap(find.text('Cancel'));
    await _frames(tester);
    expect(putDayMeta, isEmpty);
  });
}
