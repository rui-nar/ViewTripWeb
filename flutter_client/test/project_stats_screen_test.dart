// Widget tests for ProjectStatsScreen sourcing tags/groups from the ambient
// ProjectNotifier provider instead of GoRouterState.extra (issue #76
// follow-up: extra isn't URL-encoded, so it's lost on a forced reload), and
// loading the project into that notifier first when it isn't already the one
// loaded (e.g. a direct reload of the /stats URL, where the singleton starts
// empty).

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:viewtrip_client/src/projects/project_notifier.dart';
import 'package:viewtrip_client/src/projects/project_service.dart';
import 'package:viewtrip_client/src/projects/project_stats_screen.dart';

class _FakeProjectService extends ProjectService {
  @override
  Future<Map<String, dynamic>> getDetailsMeta(String name) async => {
        'name': name,
        'activities': <dynamic>[],
        'items': <dynamic>[],
        'day_meta': {
          '2026-05-10': {
            'tags': ['norway']
          },
        },
        'people': <dynamic>[],
        'groups': <dynamic>[],
        'sleeping_options': <dynamic>[],
      };

  @override
  Future<Map<String, dynamic>> getLowResGeo(String name) async =>
      {'type': 'FeatureCollection', 'features': <dynamic>[]};

  @override
  Future<Map<String, dynamic>> getGeo(String name) async =>
      {'type': 'FeatureCollection', 'features': <dynamic>[]};

  // load() unconditionally kicks off a background elevation-data fetch via
  // getDetails() (not gated by loadOwnerExtras) — override it too so nothing
  // falls through to a real, unmocked api.get() call.
  @override
  Future<Map<String, dynamic>> getDetails(String name) async =>
      getDetailsMeta(name);
}

/// Skips owner-only network calls and the 5 s background-sync-check Timer
/// that would otherwise leak past testWidgets teardown — irrelevant here.
class _TestProjectNotifier extends ProjectNotifier {
  _TestProjectNotifier(super.service);
  @override
  bool get loadOwnerExtras => false;
}

class _FakeStatsService extends ProjectService {
  @override
  Future<Map<String, dynamic>> getStats(String name,
          {List<String> tags = const []}) async =>
      <String, dynamic>{};
}

void main() {
  // ProjectNotifier.load() now round-trips selection/filter state through
  // shared_preferences (issue #76 follow-up) — without a mock, getInstance()
  // hangs on the platform channel in a widget test.
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets(
      'reads tags from the ambient ProjectNotifier, not a constructor param',
      (tester) async {
    final notifier = _TestProjectNotifier(_FakeProjectService());
    await notifier.load('Trip');

    await tester.pumpWidget(MaterialApp(
      home: ChangeNotifierProvider<ProjectNotifier>.value(
        value: notifier,
        child: ProjectStatsScreen(
          projectName: 'Trip',
          service: _FakeStatsService(),
        ),
      ),
    ));
    await tester.pumpAndSettle();

    expect(find.widgetWithText(FilterChip, 'norway'), findsOneWidget);
  });

  testWidgets(
      'loads the project into the ambient notifier when it is not already loaded',
      (tester) async {
    final notifier = _TestProjectNotifier(_FakeProjectService());
    expect(notifier.projectName, isNull);

    await tester.pumpWidget(MaterialApp(
      home: ChangeNotifierProvider<ProjectNotifier>.value(
        value: notifier,
        child: ProjectStatsScreen(
          projectName: 'Trip',
          service: _FakeStatsService(),
        ),
      ),
    ));
    await tester.pumpAndSettle();

    expect(notifier.projectName, 'Trip');
  });
}
