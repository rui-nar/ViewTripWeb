// Unit tests for the durable segment geo-patch overlay in
// ProjectSegmentCrudMixin. These cover the logic that fixes lost patches (when
// geo is null during load) and ghost segments (delete-then-create races with a
// stale background geo snapshot).

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:viewtrip_client/src/projects/project_segment_crud_mixin.dart';
import 'package:viewtrip_client/src/projects/project_service.dart';

/// Minimal concrete host so the mixin can be exercised in isolation. Only the
/// geo-overlay methods are tested; `service` is never called.
class _Host extends ChangeNotifier with ProjectSegmentCrudMixin {
  @override
  String? projectName = 'p';
  @override
  List<Map<String, dynamic>> items = [];
  @override
  Map<String, dynamic>? geo;
  @override
  String? error;
  @override
  final ProjectService service = ProjectService();
  @override
  Future<void> reloadDetailsOnly(String name) async {}
  @override
  String errorMessage(Exception e) => e.toString();
}

Map<String, dynamic> _segFeature(String id) => {
      'type': 'Feature',
      'geometry': {
        'type': 'LineString',
        'coordinates': [
          [0, 0],
          [1, 1],
        ],
      },
      'properties': {'type': 'segment', 'segment_id': id},
    };

List<String> _segIds(List<dynamic> features) => [
      for (final f in features)
        if (f is Map && (f['properties'] as Map?)?['segment_id'] != null)
          (f['properties'] as Map)['segment_id'].toString(),
    ];

void main() {
  group('durable segment overlay', () {
    test('upsert while geo is null is re-applied on the next merge', () {
      final h = _Host()..geo = null;
      h.upsertSegmentInGeo('s1', _segFeature('s1')); // dropped from live geo (null)

      // A fresh server snapshot without s1 (it was created during the load).
      final merged = h.mergePendingSegmentPatches([]);
      expect(_segIds(merged), ['s1']);
    });

    test('merge replaces an existing feature rather than duplicating it', () {
      final h = _Host();
      final updated = _segFeature('s1')
        ..['properties']['route_mode'] = 'rail';
      h.upsertSegmentInGeo('s1', updated);

      final merged = h.mergePendingSegmentPatches([_segFeature('s1')]);
      expect(_segIds(merged), ['s1']);
      expect(
        (merged.single as Map)['properties']['route_mode'],
        'rail',
      );
    });

    test('tombstoned segment is dropped from a stale server snapshot', () {
      final h = _Host()..geo = {'type': 'FeatureCollection', 'features': []};
      h.removeSegmentFromGeo('old');

      // Stale background geo still contains the deleted segment.
      final merged = h.mergePendingSegmentPatches([_segFeature('old')]);
      expect(_segIds(merged), isEmpty);
    });

    test('delete-then-create: old ghost dropped, new segment kept', () {
      final h = _Host()..geo = {'type': 'FeatureCollection', 'features': []};
      h.removeSegmentFromGeo('old');
      h.upsertSegmentInGeo('new', _segFeature('new'));

      // Stale fullGeo fetched before either op — still has 'old', lacks 'new'.
      final merged = h.mergePendingSegmentPatches([_segFeature('old')]);
      expect(_segIds(merged), ['new']);
    });

    test('reconcile clears overlay entries the server already reflects', () {
      final h = _Host()..geo = {'type': 'FeatureCollection', 'features': []};
      h.upsertSegmentInGeo('s1', _segFeature('s1')); // pending patch
      h.removeSegmentFromGeo('s2'); // tombstone

      // Server now contains s1 (patch caught up) and no longer contains s2
      // (deletion caught up) → both overlay entries should clear.
      h.reconcileSegmentOverlay({
        'type': 'FeatureCollection',
        'features': [_segFeature('s1')],
      });

      // With the overlay cleared, a later merge is a pure pass-through.
      final merged = h.mergePendingSegmentPatches([_segFeature('s1'), _segFeature('s2')]);
      expect(_segIds(merged)..sort(), ['s1', 's2']);
    });

    test('clearSegmentOverlay discards all pending state', () {
      final h = _Host()..geo = {'type': 'FeatureCollection', 'features': []};
      h.upsertSegmentInGeo('s1', _segFeature('s1'));
      h.removeSegmentFromGeo('s2');
      h.clearSegmentOverlay();

      final merged = h.mergePendingSegmentPatches([_segFeature('s2')]);
      expect(_segIds(merged), ['s2']); // s2 no longer tombstoned, s1 not added
    });
  });

  group('stale pending-segment recovery', () {
    final now = DateTime.parse('2026-06-10T12:00:00Z');

    test('non-pending statuses are never stale', () {
      for (final status in ['idle', 'resolved', 'failed', null]) {
        expect(
          ProjectSegmentCrudMixin.isPendingSegmentStale(
              status, now.toIso8601String(), now),
          isFalse,
        );
      }
    });

    test('recently-started pending job is left alone', () {
      final oneMinAgo = now.subtract(const Duration(minutes: 1));
      expect(
        ProjectSegmentCrudMixin.isPendingSegmentStale(
            'pending', oneMinAgo.toIso8601String(), now),
        isFalse,
      );
    });

    test('long-pending job is considered orphaned', () {
      final tenMinAgo = now.subtract(const Duration(minutes: 10));
      expect(
        ProjectSegmentCrudMixin.isPendingSegmentStale(
            'pending', tenMinAgo.toIso8601String(), now),
        isTrue,
      );
    });

    test('missing or unparseable timestamp counts as stale', () {
      expect(
        ProjectSegmentCrudMixin.isPendingSegmentStale('pending', null, now),
        isTrue,
      );
      expect(
        ProjectSegmentCrudMixin.isPendingSegmentStale('pending', 'not-a-date', now),
        isTrue,
      );
    });
  });
}
