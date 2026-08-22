import 'package:flutter/material.dart';
import 'package:flutter_map_animations/flutter_map_animations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:viewtrip_client/src/core/project_ref.dart';
import 'package:viewtrip_client/src/projects/map_panel.dart';
import 'package:viewtrip_client/src/projects/project_notifier.dart';
import 'package:viewtrip_client/src/projects/project_service.dart';

ProjectNotifier _notifierWithActivity() {
  final n = ProjectNotifier(ProjectService())..ref = const ProjectRef(name: 'Trip');
  n.items = [
    {
      'item_type': 'activity',
      'activity': {'id': 1, 'name': 'Hike', 'sport_type': 'hike'},
    },
  ];
  n.geo = {
    'type': 'FeatureCollection',
    'features': [
      {
        'type': 'Feature',
        'properties': {'type': 'activity', 'activity_id': '1', 'sport_type': 'hike'},
        'geometry': {
          'type': 'LineString',
          'coordinates': [
            [7.0, 45.0],
            [7.1, 45.1],
          ],
        },
      },
    ],
  };
  return n;
}

Future<void> _pump(WidgetTester tester, MapPanel panel) async {
  tester.view.physicalSize = const Size(800, 800);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(MaterialApp(home: Scaffold(body: panel)));
  // The activity geo triggers _fitBoundsOnce's animated camera fit (a
  // post-frame callback): one pump to run the build + callback, a second so
  // the ticker takes its zero-elapsed first tick, then the animation's own
  // duration — otherwise its Ticker is still running when the test ends
  // (see map_panel_fit_bounds_test.dart's _settleFit).
  await tester.pump();
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 600));
}

/// Guards issue #215 (an Activities toggle, alongside Memories/Encounters,
/// to hide the activity icons on a crowded map).
void main() {
  testWidgets('activity markers render an Activities toggle that hides them',
      (tester) async {
    final notifier = _notifierWithActivity();
    final controller = AnimatedMapController(vsync: const TestVSync());
    addTearDown(controller.dispose);

    await _pump(
      tester,
      MapPanel(
        notifier: notifier,
        mapController: controller,
        basemapUrl: 'https://example.invalid/{z}/{x}/{y}.png',
      ),
    );

    expect(find.text('Activities'), findsOneWidget);
    expect(find.byIcon(Icons.hiking), findsOneWidget);

    await tester.tap(find.byType(Switch).first);
    await tester.pump();

    expect(find.byIcon(Icons.hiking), findsNothing);
  });

  testWidgets('no activity markers hides the Activities toggle',
      (tester) async {
    final notifier = ProjectNotifier(ProjectService())
      ..ref = const ProjectRef(name: 'Trip');
    final controller = AnimatedMapController(vsync: const TestVSync());
    addTearDown(controller.dispose);

    await _pump(
      tester,
      MapPanel(
        notifier: notifier,
        mapController: controller,
        basemapUrl: 'https://example.invalid/{z}/{x}/{y}.png',
      ),
    );

    expect(find.text('Activities'), findsNothing);
  });
}
