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
}
