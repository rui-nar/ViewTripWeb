import 'package:flutter/material.dart';
import 'package:flutter_map_animations/flutter_map_animations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:viewtrip_client/src/projects/map_panel.dart';
import 'package:viewtrip_client/src/projects/project_notifier.dart';
import 'package:viewtrip_client/src/projects/project_service.dart';

ProjectNotifier _notifierWithEncounter() {
  final n = ProjectNotifier(ProjectService())..projectName = 'Trip';
  n.people = [
    {'id': 1, 'name': 'Alice'},
  ];
  n.items = [
    {
      'item_type': 'encounter',
      'encounter': {
        'id': 10,
        'person_id': 1,
        'lat': 45.0,
        'lon': 7.0,
        'date': '2026-01-01',
      },
    },
  ];
  return n;
}

Future<void> _pump(WidgetTester tester, MapPanel panel) async {
  tester.view.physicalSize = const Size(800, 800);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(MaterialApp(home: Scaffold(body: panel)));
  await tester.pump();
}

/// Guards issue #71 (owner sees encounter pins + toggle on the view-mode map)
/// and, more importantly, the privacy regression it must never introduce:
/// `MapPanel` is reused by the public/unauthenticated share screen
/// (shared_project_screen.dart), so encounters must stay invisible there
/// (see docs/ENCOUNTERS.md — people/encounters are owner-only PII).
void main() {
  testWidgets(
      'showEncounters:true renders the encounter pin and the Encounters toggle',
      (tester) async {
    final notifier = _notifierWithEncounter();
    final controller = AnimatedMapController(vsync: const TestVSync());
    addTearDown(controller.dispose);

    await _pump(
      tester,
      MapPanel(
        notifier: notifier,
        mapController: controller,
        basemapUrl: 'https://example.invalid/{z}/{x}/{y}.png',
        showEncounters: true,
      ),
    );

    expect(find.text('Encounters'), findsOneWidget);
    expect(find.byIcon(Icons.person), findsOneWidget);
  });

  testWidgets(
      'showEncounters omitted (default false) shows neither pin nor toggle — '
      'the privacy guarantee for shared_project_screen.dart', (tester) async {
    final notifier = _notifierWithEncounter();
    final controller = AnimatedMapController(vsync: const TestVSync());
    addTearDown(controller.dispose);

    await _pump(
      tester,
      MapPanel(
        notifier: notifier,
        mapController: controller,
        basemapUrl: 'https://example.invalid/{z}/{x}/{y}.png',
        // showEncounters intentionally omitted.
      ),
    );

    expect(find.text('Encounters'), findsNothing);
    expect(find.byIcon(Icons.person), findsNothing);
  });

  testWidgets('showEncounters:false explicitly also hides pin and toggle',
      (tester) async {
    final notifier = _notifierWithEncounter();
    final controller = AnimatedMapController(vsync: const TestVSync());
    addTearDown(controller.dispose);

    await _pump(
      tester,
      MapPanel(
        notifier: notifier,
        mapController: controller,
        basemapUrl: 'https://example.invalid/{z}/{x}/{y}.png',
        showEncounters: false,
      ),
    );

    expect(find.text('Encounters'), findsNothing);
    expect(find.byIcon(Icons.person), findsNothing);
  });
}
