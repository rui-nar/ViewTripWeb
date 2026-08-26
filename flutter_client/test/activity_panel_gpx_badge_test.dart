import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:viewtrip_client/src/projects/activity_panel.dart';
import 'package:viewtrip_client/src/projects/project_notifier.dart';
import 'package:viewtrip_client/src/projects/project_service.dart';

/// GPX-import visual differentiation: an activity with source == 'gpx' shows
/// a small corner badge on its icon box; a Strava (source null/absent)
/// activity does not.
void main() {
  ProjectNotifier notifierWith({required int activityId, String? source}) {
    final n = ProjectNotifier(ProjectService());
    n.activities = [
      {
        'id': activityId,
        'type': 'Ride',
        'name': 'Ride',
        'distance': 5000,
        'moving_time': 1800,
        'start_date_local': '2026-06-01T08:00:00',
        if (source != null) 'source': source,
      },
    ];
    n.items = [
      {'item_type': 'activity', 'activity_id': activityId},
    ];
    return n;
  }

  Future<void> pumpPanel(WidgetTester tester, ProjectNotifier notifier) async {
    tester.view.physicalSize = const Size(1200, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      ChangeNotifierProvider<ProjectNotifier>.value(
        value: notifier,
        child: MaterialApp(
          home: Scaffold(body: ActivityPanel(notifier: notifier)),
        ),
      ),
    );
    // Days start collapsed; expand so the activity row renders.
    await tester.tap(find.byIcon(Icons.unfold_more));
    await tester.pumpAndSettle();
  }

  testWidgets('Strava activity (no source) shows no GPX badge', (tester) async {
    final notifier = notifierWith(activityId: 1);
    await pumpPanel(tester, notifier);

    expect(find.byIcon(Icons.route), findsNothing);
  });

  testWidgets('GPX-imported activity (source == gpx) shows the corner badge',
      (tester) async {
    final notifier = notifierWith(activityId: 2, source: 'gpx');
    await pumpPanel(tester, notifier);

    expect(find.byIcon(Icons.route), findsOneWidget);
  });
}
