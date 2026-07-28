import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:viewtrip_client/src/core/project_ref.dart';
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

Map<String, dynamic> _activity({
  bool edited = false,
  int id = 111,
  int? splitParentId,
}) {
  final track = <GeoPoint>[
    (lat: 48.0, lon: 2.00),
    (lat: 48.0, lon: 2.01),
    (lat: 48.0, lon: 2.02),
    (lat: 48.0, lon: 2.03),
  ];
  return {
    'id': id,
    'name': 'Test Ride',
    'is_edited': edited,
    'split_parent_id': splitParentId,
    'map': {'summary_polyline': _encode(track)},
    'elevation_profile': [
      [0.0, 100.0],
      [1.0, 110.0],
      [2.0, 120.0],
      [3.0, 130.0],
    ],
  };
}

/// A longer fixture (6 points, lon 2.00..2.05) for the split/cut tests: after a
/// deletion the track must still leave a valid "Cut & add transport" boundary,
/// which needs index <= length - 3.
Map<String, dynamic> _longActivity() {
  final track = <GeoPoint>[
    for (var i = 0; i < 6; i++) (lat: 48.0, lon: 2.0 + i * 0.01),
  ];
  return {
    'id': 111,
    'name': 'Test Ride',
    'is_edited': false,
    'map': {'summary_polyline': _encode(track)},
    'elevation_profile': [for (var i = 0; i < 6; i++) [i.toDouble(), 100.0 + i * 10]],
  };
}

/// Captures the split/reset calls the page makes instead of reaching the network.
class _RecordingNotifier extends ProjectNotifier {
  _RecordingNotifier() : super(ProjectService()) {
    ref = const ProjectRef(name: 'Trip');
  }

  final List<({int index, bool dropBoundary, Map<String, dynamic>? payload})>
      splits = [];
  final List<int> resets = [];

  @override
  Future<void> splitActivity(
    int activityId,
    int splitIndex, {
    bool dropBoundary = false,
    Map<String, dynamic>? payload,
  }) async {
    splits.add(
        (index: splitIndex, dropBoundary: dropBoundary, payload: payload));
  }

  @override
  Future<void> resetActivityTrack(int activityId) async {
    resets.add(activityId);
  }
}

/// A notifier holding a flat split family: root 111 with [pieces] children.
_RecordingNotifier _familyNotifier(int pieces) => _RecordingNotifier()
  ..activities = [
    {'id': 111, 'split_parent_id': null},
    for (var i = 1; i <= pieces; i++) {'id': -i, 'split_parent_id': 111},
  ];

/// A notifier holding a CHAIN: 111 → -1 → -2, each cut out of the one before.
/// The flat fixture cannot tell a transitive walk from a single-level one.
_RecordingNotifier _chainNotifier() => _RecordingNotifier()
  ..activities = [
    {'id': 111, 'split_parent_id': null},
    {'id': -1, 'split_parent_id': 111},
    {'id': -2, 'split_parent_id': -1},
  ];

/// Push the editor onto a route (as ActivityPanel does) so the page's pop-on-
/// success has a route to return to.
Future<void> _pumpPushed(
  WidgetTester tester,
  Map<String, dynamic> activity,
  ProjectNotifier notifier,
) async {
  tester.view.physicalSize = const Size(1200, 1000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: Builder(
        builder: (ctx) => TextButton(
          onPressed: () => Navigator.of(ctx).push(MaterialPageRoute(
            builder: (_) =>
                ActivityEditorPage(notifier: notifier, activity: activity),
          )),
          child: const Text('open editor'),
        ),
      ),
    ),
  ));
  await tester.tap(find.text('open editor'));
  await tester.pumpAndSettle();
}

/// Long-press the vertex handle at [index] and choose [label] from its menu.
Future<void> _pointMenu(WidgetTester tester, int index, String label) async {
  await tester.longPress(find.byKey(ValueKey('vertex_$index')));
  await tester.pumpAndSettle();
  await tester.tap(find.text(label));
  await tester.pumpAndSettle();
}

Future<void> _pump(WidgetTester tester, Map<String, dynamic> activity) async {
  tester.view.physicalSize = const Size(1200, 1000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final notifier = ProjectNotifier(ProjectService())..ref = const ProjectRef(name: 'Trip');
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

  testWidgets('a local activity gets the non-Strava reset label',
      (tester) async {
    // Split tails and added transport carry a synthetic negative id and never
    // came from Strava, so reset only undoes their own edits (issue #131).
    await _pump(tester, _activity(edited: true, id: -1));
    expect(find.text('Reset to Strava'), findsNothing);
    expect(find.text('Reset track'), findsOneWidget);
  });

  // ── Reset on a split root warns first (issue #141) ────────────────────────
  //
  // Resetting the root restores the whole pre-split track, so the server undoes
  // the split rather than leave the pieces duplicating it. That destroys those
  // pieces and any edits on them, so the editor must say so before calling.

  testWidgets('resetting a split root warns that the pieces will be removed',
      (tester) async {
    final notifier = _familyNotifier(1);
    await _pumpPushed(tester, _activity(edited: true), notifier);

    await tester.tap(find.text('Reset to Strava'));
    await tester.pumpAndSettle();

    expect(find.textContaining('before it was split'), findsOneWidget);
    expect(find.textContaining('The piece cut out of it'), findsOneWidget);
    expect(find.textContaining('cannot be undone'), findsOneWidget);
    expect(notifier.resets, isEmpty); // nothing sent until confirmed
  });

  testWidgets('cancelling the warning leaves the split alone', (tester) async {
    final notifier = _familyNotifier(2);
    await _pumpPushed(tester, _activity(edited: true), notifier);

    await tester.tap(find.text('Reset to Strava'));
    await tester.pumpAndSettle();
    expect(find.textContaining('The 2 pieces cut out of it'), findsOneWidget);

    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(notifier.resets, isEmpty);
  });

  testWidgets('confirming the warning sends the reset', (tester) async {
    final notifier = _familyNotifier(1);
    await _pumpPushed(tester, _activity(edited: true), notifier);

    await tester.tap(find.text('Reset to Strava'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Reset'));
    await tester.pumpAndSettle();

    expect(notifier.resets, [111]);
  });

  testWidgets('resetting a piece with nothing under it does not warn',
      (tester) async {
    // A leaf piece takes nothing with it — reset just undoes its edits (#131).
    final notifier = _familyNotifier(1);
    await _pumpPushed(
        tester, _activity(edited: true, id: -1, splitParentId: 111), notifier);

    await tester.tap(find.text('Reset track'));
    await tester.pumpAndSettle();

    expect(find.byType(AlertDialog), findsNothing);
    expect(notifier.resets, [-1]);
  });

  testWidgets('resetting a piece that was split again warns about its child',
      (tester) async {
    // Issue #143: -1 grows back over -2, so -2 goes with it — and only -2. The
    // root above the reset is not below it and must not be counted.
    final notifier = _chainNotifier();
    await _pumpPushed(
        tester, _activity(edited: true, id: -1, splitParentId: 111), notifier);

    await tester.tap(find.text('Reset track'));
    await tester.pumpAndSettle();

    expect(find.textContaining('The piece cut out of it'), findsOneWidget);
    expect(notifier.resets, isEmpty);
  });

  testWidgets('resetting the root of a chain counts the grandchild too',
      (tester) async {
    // The walk is transitive: 111 → -1 → -2 is two pieces, not one.
    final notifier = _chainNotifier();
    await _pumpPushed(tester, _activity(edited: true), notifier);

    await tester.tap(find.text('Reset to Strava'));
    await tester.pumpAndSettle();

    expect(find.textContaining('The 2 pieces cut out of it'), findsOneWidget);
  });

  testWidgets('resetting an activity that was never split does not warn',
      (tester) async {
    final notifier = _familyNotifier(0);
    await _pumpPushed(tester, _activity(edited: true), notifier);

    await tester.tap(find.text('Reset to Strava'));
    await tester.pumpAndSettle();

    expect(find.byType(AlertDialog), findsNothing);
    expect(notifier.resets, [111]);
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

  // ── Edits compound with Split / Cut (issue #127) ───────────────────────────
  // The editor holds edits locally until Save, so a split that sent only an
  // index discarded them — and applied that index to a different point list
  // than the one on screen. Both actions now carry the current points.

  List<double> lngsOf(Map<String, dynamic>? payload) => [
        for (final p in (payload?['points'] as List? ?? [])) (p as Map)['lng'] as double,
      ];

  testWidgets('Cut & add transport carries the points left after a deletion',
      (tester) async {
    final notifier = _RecordingNotifier();
    await _pumpPushed(tester, _longActivity(), notifier);

    // Delete the vertex at index 1 (lon 2.01), then cut at index 2 of what's left.
    await _pointMenu(tester, 1, 'Delete point');
    await _pointMenu(tester, 2, 'Cut & add transport');
    await tester.tap(find.widgetWithText(FilledButton, 'Cut'));
    await tester.pumpAndSettle();

    expect(notifier.splits, hasLength(1));
    final call = notifier.splits.single;
    expect(call.dropBoundary, isTrue);
    expect(call.index, 2);
    // The cut carries the post-deletion track: 5 points, without lon 2.01.
    expect(lngsOf(call.payload), hasLength(5));
    expect(lngsOf(call.payload).any((l) => (l - 2.01).abs() < 1e-6), isFalse,
        reason: 'the deleted point must not come back with the cut');
  });

  testWidgets('Split here carries the edited points too', (tester) async {
    final notifier = _RecordingNotifier();
    await _pumpPushed(tester, _longActivity(), notifier);

    await _pointMenu(tester, 1, 'Delete point');
    await _pointMenu(tester, 2, 'Split here');
    await tester.tap(find.widgetWithText(FilledButton, 'Split'));
    await tester.pumpAndSettle();

    final call = notifier.splits.single;
    expect(call.dropBoundary, isFalse);
    expect(lngsOf(call.payload), hasLength(5));
    expect(lngsOf(call.payload).any((l) => (l - 2.01).abs() < 1e-6), isFalse);
  });

  testWidgets('the confirmation says pending edits are applied, only when dirty',
      (tester) async {
    final notifier = _RecordingNotifier();
    await _pumpPushed(tester, _longActivity(), notifier);

    // Clean editor: no note.
    await tester.longPress(find.byKey(const ValueKey('vertex_2')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cut & add transport'));
    await tester.pumpAndSettle();
    expect(find.textContaining('unsaved point edits'), findsNothing);
    await tester.tap(find.widgetWithText(TextButton, 'Cancel'));
    await tester.pumpAndSettle();

    // After an edit, the same confirmation warns that it will be applied.
    await _pointMenu(tester, 1, 'Delete point');
    await _pointMenu(tester, 2, 'Cut & add transport');
    expect(find.textContaining('unsaved point edits'), findsOneWidget);
  });
}
