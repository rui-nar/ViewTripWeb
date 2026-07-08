import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:viewtrip_client/src/map/geo_point.dart';
import 'package:viewtrip_client/src/projects/activity_editor_page.dart';
import 'package:viewtrip_client/src/projects/project_notifier.dart';
import 'package:viewtrip_client/src/projects/project_service.dart';
import 'package:viewtrip_client/src/projects/track_editor_controller.dart';

/// Minimal Google-polyline encoder for test fixtures.
String _encode(List<GeoPoint> pts) {
  final sb = StringBuffer();
  int lastLat = 0, lastLng = 0;
  for (final p in pts) {
    final lat = (p.lat * 1e5).round();
    final lng = (p.lon * 1e5).round();
    _delta(sb, lat - lastLat);
    _delta(sb, lng - lastLng);
    lastLat = lat;
    lastLng = lng;
  }
  return sb.toString();
}

void _delta(StringBuffer sb, int v) {
  int zig = v < 0 ? ~(v << 1) : (v << 1);
  while (zig >= 0x20) {
    sb.writeCharCode((0x20 | (zig & 0x1f)) + 63);
    zig >>= 5;
  }
  sb.writeCharCode(zig + 63);
}

Map<String, dynamic> _activity({bool edited = false}) {
  final track = <GeoPoint>[
    (lat: 48.0, lon: 2.00),
    (lat: 48.0, lon: 2.01),
    (lat: 48.0, lon: 2.02),
    (lat: 48.0, lon: 2.03),
  ];
  return {
    'id': 111,
    'name': 'Test Ride',
    'is_edited': edited,
    'map': {'summary_polyline': _encode(track)},
    'elevation_profile': [
      [0.0, 100.0],
      [1.0, 110.0],
      [2.0, 120.0],
      [3.0, 130.0],
    ],
  };
}

Future<void> _pump(WidgetTester tester, Map<String, dynamic> activity) async {
  tester.view.physicalSize = const Size(1200, 1000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final notifier = ProjectNotifier(ProjectService())..projectName = 'Trip';
  await tester.pumpWidget(MaterialApp(
    home: ActivityEditorPage(notifier: notifier, activity: activity),
  ));
  await tester.pump();
}

TrackEditorController _controllerOf(WidgetTester tester) {
  final state = tester.state<State>(find.byType(ActivityEditorPage));
  // ignore: invalid_use_of_protected_member
  return (state as dynamic).editorControllerForTest as TrackEditorController;
}

void main() {
  group('modelForActivity', () {
    test('parses polyline and elevation into aligned points', () {
      final m = modelForActivity(_activity());
      expect(m.length, 4);
      expect(m.points.first.lat, closeTo(48.0, 1e-4));
      expect(m.points.first.elev, isNotNull);
    });

    test('handles a missing elevation profile', () {
      final a = _activity()..remove('elevation_profile');
      final m = modelForActivity(a);
      expect(m.length, 4);
      expect(m.points.first.elev, isNull);
    });
  });

  testWidgets('renders the Add-points toggle, hint and a disabled Save',
      (tester) async {
    await _pump(tester, _activity());
    expect(find.text('Add points'), findsOneWidget);
    expect(find.textContaining('Long-press'), findsOneWidget);

    final save = tester.widget<TextButton>(
      find.ancestor(of: find.text('Save'), matching: find.byType(TextButton)),
    );
    expect(save.onPressed, isNull); // nothing edited yet
  });

  testWidgets('toggling Add points flips the hint text', (tester) async {
    await _pump(tester, _activity());
    expect(find.textContaining('Long-press'), findsOneWidget);
    await tester.tap(find.text('Add points'));
    await tester.pump();
    expect(find.textContaining('Tap the map to insert'), findsOneWidget);
  });

  testWidgets('Reset to Strava only shows for an edited activity',
      (tester) async {
    await _pump(tester, _activity(edited: false));
    expect(find.text('Reset to Strava'), findsNothing);

    await _pump(tester, _activity(edited: true));
    expect(find.text('Reset to Strava'), findsOneWidget);
  });

  testWidgets('an edit via the controller enables Save', (tester) async {
    await _pump(tester, _activity());
    _controllerOf(tester).removeSelected(0);
    await tester.pump();
    final save = tester.widget<TextButton>(
      find.ancestor(of: find.text('Save'), matching: find.byType(TextButton)),
    );
    expect(save.onPressed, isNotNull);
  });

  testWidgets('removing a point updates the rendered map polyline',
      (tester) async {
    await _pump(tester, _activity());
    PolylineLayer poly() =>
        tester.widget<PolylineLayer>(find.byType(PolylineLayer));
    expect(poly().polylines.first.points.length, 4);

    _controllerOf(tester).removeSelected(1);
    await tester.pump();

    expect(poly().polylines.first.points.length, 3,
        reason: 'the map polyline should drop the removed vertex');
  });

  // ── End-to-end gesture tests (issue #38) — drive the real widget tree ──────

  int polyCount(WidgetTester tester) =>
      tester.widget<PolylineLayer>(find.byType(PolylineLayer))
          .polylines
          .first
          .points
          .length;

  testWidgets('Add mode: tapping the map surface inserts a point',
      (tester) async {
    await _pump(tester, _activity());
    expect(polyCount(tester), 4);

    // Enable Add mode via the real toolbar chip.
    await tester.tap(find.text('Add points'));
    await tester.pump();

    // Tap the map surface away from the vertices (which sit at/east of centre)
    // so the tap lands on the tile layer, not a handle marker. flutter_map
    // defers the tap by its double-tap window, so pump past it.
    final mapCentre = tester.getCenter(find.byType(FlutterMap));
    await tester.tapAt(mapCentre + const Offset(-200, -120));
    await tester.pump(const Duration(milliseconds: 400));

    expect(polyCount(tester), 5,
        reason: 'a map-surface tap in Add mode should insert one vertex');
  });

  testWidgets('Delete via context menu removes the point and updates the map',
      (tester) async {
    await _pump(tester, _activity());
    expect(polyCount(tester), 4);

    // Long-press the first vertex handle (at map centre, so its menu has room)
    // to open its context menu.
    await tester.longPress(find.byKey(const ValueKey('vertex_0')));
    await tester.pumpAndSettle();
    expect(find.text('Delete point'), findsOneWidget);

    await tester.tap(find.text('Delete point'));
    await tester.pumpAndSettle();

    expect(polyCount(tester), 3,
        reason: 'deleting via the menu should drop the vertex from the map');
  });

  testWidgets('Dragging a vertex handle moves the point (issue #36)',
      (tester) async {
    await _pump(tester, _activity());
    final c = _controllerOf(tester);
    final before = c.points.first;

    await tester.drag(
      find.byKey(const ValueKey('vertex_0')),
      const Offset(0, -80), // drag north
    );
    await tester.pump();

    final after = c.points.first;
    expect(after.lat == before.lat && after.lng == before.lng, isFalse,
        reason: 'the dragged vertex should have committed a new position');
    expect(c.isDirty, isTrue);
    // The move is committed through moveVertex → the save payload reflects it.
    final payload = (c.toSavePayload()['points'] as List).first as Map;
    expect(payload['lat'], closeTo(after.lat, 1e-9));
  });
}
