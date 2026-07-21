/// Mixin providing Segment CRUD operations to ProjectNotifier.
///
/// Also owns the geo-patch helpers (upsertSegmentInGeo, removeSegmentFromGeo)
/// and the great-circle / segment-feature geometry, which were only ever used
/// by segment operations.
library;

import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';

import '../api/client.dart';
import '../core/project_ref.dart';
import 'project_service.dart';

mixin ProjectSegmentCrudMixin on ChangeNotifier {
  // ── Abstract: project state (satisfied by ProjectNotifier fields) ──────────
  ProjectRef? get projectRef;
  List<Map<String, dynamic>> get items;
  set items(List<Map<String, dynamic>> v);
  Map<String, dynamic>? get geo;
  set geo(Map<String, dynamic>? v);
  String? get error;
  set error(String? v);

  /// Access to the underlying ProjectService — satisfied by the notifier's
  /// `get service => _service` delegate.
  ProjectService get service;

  /// Details-only reload — thin delegate to _silentReloadDetailsOnly.
  Future<void> reloadDetailsOnly(ProjectRef ref);

  /// Format an Exception into a user-readable string — delegates to _msg.
  String errorMessage(Exception e);

  /// If [e] is a 409 optimistic-lock conflict, resync items + geo from the
  /// server (discarding the optimistic change) and surface a soft retry
  /// message. Returns true when the conflict was handled.
  Future<bool> _resyncOnConflict(Object e, ProjectRef ref) async {
    if (e is! ApiException || e.statusCode != 409) return false;
    try {
      await reloadDetailsOnly(ref);
      geo = await service.getGeo(ref);
    } catch (_) {
      // Best-effort resync; the next load will reconcile regardless.
    }
    error = 'This trip changed elsewhere — refreshed from server, please retry';
    notifyListeners();
    return true;
  }

  // ── Segment CRUD ───────────────────────────────────────────────────────────

  Future<String> addSegment({
    required String segmentType,
    required String label,
    required double startLat,
    required double startLon,
    required double endLat,
    required double endLon,
    int? insertAfterIndex,
    String? date,
    String? trainNumber,
    String? hafasProvider,
  }) async {
    final ref = projectRef;
    if (ref == null) return '';
    final placeholder = {
      'item_type': 'segment',
      'segment': {
        'id': '__optimistic__',
        'segment_type': segmentType,
        'label': label,
        'date': date,
        'start': {'lat': startLat, 'lon': startLon},
        'end':   {'lat': endLat,   'lon': endLon},
      },
    };
    final insertAt = insertAfterIndex != null
        ? (insertAfterIndex + 1).clamp(0, items.length)
        : items.length;
    // Assign a new list so identical() in the panel detects the change.
    final newItems = List<Map<String, dynamic>>.from(items);
    newItems.insert(insertAt, placeholder);
    items = newItems;
    notifyListeners();
    try {
      final result = await api.post(
        ref.path('/segments'),
        {
          'segment_type': segmentType,
          'label': label,
          'start_lat': startLat,
          'start_lon': startLon,
          'end_lat': endLat,
          'end_lon': endLon,
          if (insertAfterIndex != null) 'insert_after_index': insertAfterIndex,
          if (date != null) 'date': date,
          if (trainNumber != null) 'train_number': trainNumber,
          if (hafasProvider != null) 'hafas_provider': hafasProvider,
        },
      ) as Map<String, dynamic>;
      final newId = result['id'] as String;
      // Replace the optimistic placeholder with the confirmed segment,
      // creating a new list so identical() in the panel triggers a rebuild.
      items = [
        for (final item in items)
          if (item['item_type'] == 'segment' &&
              item['segment']?['id'] == '__optimistic__')
            {
              'item_type': 'segment',
              'segment': {
                'id': newId,
                'segment_type': segmentType,
                'label': label,
                'date': date,
                'start': {'lat': startLat, 'lon': startLon},
                'end': {'lat': endLat, 'lon': endLon},
              },
            }
          else
            item,
      ];
      upsertSegmentInGeo(newId, _segmentFeature(
          newId, segmentType, label, startLat, startLon, endLat, endLon));
      notifyListeners();
      return newId;
    } on Exception catch (e) {
      // Roll back the optimistic placeholder so a failed create leaves no ghost.
      items = items
          .where((item) => !(item['item_type'] == 'segment' &&
              item['segment']?['id'] == '__optimistic__'))
          .toList();
      removeSegmentFromGeo('__optimistic__');
      _segmentTombstones.remove('__optimistic__'); // not a real server segment
      if (await _resyncOnConflict(e, ref)) return '';
      error = errorMessage(e);
      notifyListeners();
      return '';
    }
  }

  Future<void> updateSegment(
    String segId, {
    required String segmentType,
    required String label,
    required double startLat,
    required double startLon,
    required double endLat,
    required double endLon,
    String? date,
    String? trainNumber,
    String? hafasProvider,
    String? routeMode,
  }) async {
    final ref = projectRef;
    if (ref == null) return;
    String? prevRouteMode;
    double? prevStartLat, prevStartLon, prevEndLat, prevEndLon;
    Map<String, dynamic>? prevSegment;  // full snapshot for rollback on error
    // Build a new list (new reference) so identical() in the panel fires.
    items = [
      for (final item in items)
        if (item['item_type'] == 'segment' &&
            item['segment']?['id']?.toString() == segId)
          () {
            final old = item['segment'] as Map;
            prevSegment   = Map<String, dynamic>.from(old);
            prevRouteMode = old['route_mode'] as String?;
            prevStartLat  = (old['start']?['lat'] as num?)?.toDouble();
            prevStartLon  = (old['start']?['lon'] as num?)?.toDouble();
            prevEndLat    = (old['end']?['lat'] as num?)?.toDouble();
            prevEndLon    = (old['end']?['lon'] as num?)?.toDouble();
            return {
              'item_type': 'segment',
              'segment': {
                ...Map<String, dynamic>.from(old),
                'segment_type': segmentType,
                'label': label,
                'date': date,
                'start': {'lat': startLat, 'lon': startLon},
                'end': {'lat': endLat, 'lon': endLon},
                if (routeMode != null) 'route_mode': routeMode,
              },
            };
          }()
        else
          item,
    ];
    notifyListeners();
    try {
      await api.put(
        ref.path('/segments/${Uri.encodeComponent(segId)}'),
        {
          'segment_type': segmentType,
          'label': label,
          'start_lat': startLat,
          'start_lon': startLon,
          'end_lat': endLat,
          'end_lon': endLon,
          if (date != null) 'date': date,
          if (trainNumber != null) 'train_number': trainNumber,
          if (hafasProvider != null) 'hafas_provider': hafasProvider,
          if (routeMode != null) 'route_mode': routeMode,
        },
      );
      final coordsChanged = prevStartLat != startLat || prevStartLon != startLon ||
          prevEndLat != endLat || prevEndLon != endLon;
      final resetToGreatCircle = coordsChanged || routeMode == 'great_circle';
      if (resetToGreatCircle || (prevRouteMode != 'rail' &&
                                  prevRouteMode != 'ferry' &&
                                  prevRouteMode != 'bus')) {
        upsertSegmentInGeo(segId, _segmentFeature(
            segId, segmentType, label, startLat, startLon, endLat, endLon));
      }
      notifyListeners();
    } on Exception catch (e) {
      // Roll back the optimistic edit so the UI doesn't drift from the server.
      if (prevSegment != null) {
        items = [
          for (final item in items)
            if (item['item_type'] == 'segment' &&
                item['segment']?['id']?.toString() == segId)
              {'item_type': 'segment', 'segment': prevSegment}
            else
              item,
        ];
      }
      if (await _resyncOnConflict(e, ref)) return;
      error = errorMessage(e);
      notifyListeners();
    }
  }

  /// Trigger async OSM route resolution for a train, boat, or bus segment and
  /// poll until it completes.
  ///
  /// The server marks the segment `route_status="pending"` and returns 202
  /// immediately (the HAFAS + Overpass work runs in a background task), so this
  /// method optimistically flips the segment to `pending` — driving a spinner on
  /// the tile — then polls `/meta` until it resolves or fails.
  ///
  /// Returns a result map `{route_status, …}`. Throws on a `failed` resolution
  /// so callers can surface the server's error message.
  Future<Map<String, dynamic>> resolveTrainRoute(
    String segId, {
    String routeMode = 'rail',
    String? hafasProvider,
    String? trainNumber,
    String? date,
  }) async {
    final ref = projectRef;
    if (ref == null) throw Exception('No project open');
    await service.resolveTrainRoute(
      ref, segId,
      hafasProvider: hafasProvider,
      trainNumber: trainNumber,
      date: date,
    );
    _patchSegmentFields(segId, {
      'route_status': 'pending',
      'route_error': null,
      if (trainNumber != null) 'train_number': trainNumber,
      if (hafasProvider != null) 'hafas_provider': hafasProvider,
    });
    notifyListeners();
    return pollSegmentResolution(segId);
  }

  /// Poll `/meta` until [segId] flips from `pending` to `resolved`/`failed`.
  ///
  /// Self-cancels if the user navigates to another project (projectName change)
  /// or the segment is deleted mid-resolve. On `resolved`, patches the segment's
  /// geometry into [geo]. On `failed`, throws with the server error message.
  Future<Map<String, dynamic>> pollSegmentResolution(
    String segId, {
    Duration interval = const Duration(seconds: 3),
    Duration timeout = const Duration(minutes: 2),
  }) async {
    final ref = projectRef;
    if (ref == null) return {'route_status': 'cancelled'};
    final deadline = DateTime.now().add(timeout);
    while (DateTime.now().isBefore(deadline)) {
      await Future<void>.delayed(interval);
      if (projectRef != ref) return {'route_status': 'cancelled'};
      Map<String, dynamic> meta;
      try {
        meta = await service.getDetailsMeta(ref);
      } on Exception {
        continue; // transient network error — retry on the next tick
      }
      if (projectRef != ref) return {'route_status': 'cancelled'};
      final seg = _segmentFromMeta(meta, segId);
      if (seg == null) return {'route_status': 'cancelled'}; // deleted mid-resolve
      final stat = (seg['route_status'] as String?) ?? 'idle';
      if (stat == 'resolved') {
        applyResolvedSegment(segId, seg);
        notifyListeners();
        return {
          'route_status': 'resolved',
          'stop_count': _polylineLength(seg),
          // True when the server fell back to a straight endpoint chord (no real
          // track found) — surfaced so the UI doesn't claim a detailed route.
          'degraded': seg['route_degraded'] == true,
        };
      }
      if (stat == 'failed') {
        _patchSegmentFields(segId, {
          'route_status': 'failed',
          'route_error': seg['route_error'],
        });
        notifyListeners();
        throw Exception(seg['route_error'] ?? 'Route resolution failed');
      }
      // still pending → keep polling
    }
    return {'route_status': 'pending'}; // timed out — tile keeps its spinner
  }

  /// Segment route-mode implied by each transport type.
  static const _routeModeForType = {
    'train': 'rail', 'boat': 'ferry', 'bus': 'bus',
  };

  /// A segment is treated as orphaned (its background resolve job never
  /// finished — e.g. the server restarted mid-resolve) once it has been
  /// `pending` for longer than this. Comfortably beyond the worst-case job
  /// time so an in-flight job is never re-triggered.
  static const _pendingStaleAfter = Duration(minutes: 5);

  /// Whether a `pending` segment's resolve job looks orphaned and should be
  /// re-triggered: true when its status is `pending` and [routeStartedAt] is
  /// null/garbage or older than [_pendingStaleAfter] relative to [nowUtc].
  static bool isPendingSegmentStale(
      String? routeStatus, String? routeStartedAt, DateTime nowUtc) {
    if (routeStatus != 'pending') return false;
    if (routeStartedAt == null) return true;
    final started = DateTime.tryParse(routeStartedAt)?.toUtc();
    if (started == null) return true;
    return nowUtc.difference(started) > _pendingStaleAfter;
  }

  /// Re-trigger resolution for any segment stuck in `pending` past
  /// [_pendingStaleAfter]. Called once per load so a job lost to a server
  /// restart is recovered when the user reopens the project. Fire-and-forget.
  void recoverStalePendingSegments(ProjectRef ref) {
    final now = DateTime.now().toUtc();
    for (final item in List<Map<String, dynamic>>.from(items)) {
      if (item['item_type'] != 'segment') continue;
      final seg = item['segment'] as Map?;
      if (seg == null) continue;
      if (!isPendingSegmentStale(seg['route_status'] as String?,
          seg['route_started_at'] as String?, now)) {
        continue; // not pending, or a job is plausibly still running
      }
      final segId = seg['id']?.toString();
      if (segId == null) continue;
      final segType = seg['segment_type'] as String?;
      final routeMode =
          _routeModeForType[segType] ?? (seg['route_mode'] as String? ?? 'rail');
      final hafasProvider = seg['hafas_provider'] as String?;
      final trainNumber = seg['train_number'] as String?;
      final date = seg['date'] as String?;
      () async {
        if (projectRef != ref) return; // navigated away before we started
        try {
          await resolveTrainRoute(
            segId,
            routeMode: routeMode,
            hafasProvider: routeMode == 'rail' ? hafasProvider : null,
            trainNumber: routeMode == 'rail' ? trainNumber : null,
            date: date,
          );
        } catch (_) {
          // Failure is reflected on the tile via route_status; no toast here.
        }
      }();
    }
  }

  /// Merge [fields] into the matching segment in [items], assigning a new list
  /// reference so identity-based rebuilds fire.
  void _patchSegmentFields(String segId, Map<String, dynamic> fields) {
    items = [
      for (final item in items)
        if (item['item_type'] == 'segment' &&
            item['segment']?['id']?.toString() == segId)
          {
            'item_type': 'segment',
            'segment': {
              ...Map<String, dynamic>.from(item['segment'] as Map),
              ...fields,
            },
          }
        else
          item,
    ];
  }

  /// Find the `segment` sub-map for [segId] in a `/meta` response, or null.
  Map<String, dynamic>? _segmentFromMeta(Map<String, dynamic> meta, String segId) {
    for (final item in (meta['items'] as List? ?? const [])) {
      if (item is Map &&
          item['item_type'] == 'segment' &&
          item['segment']?['id']?.toString() == segId) {
        return Map<String, dynamic>.from(item['segment'] as Map);
      }
    }
    return null;
  }

  /// Apply a resolved segment from `/meta` into [items] and [geo].
  @visibleForTesting
  void applyResolvedSegment(String segId, Map<String, dynamic> segMeta) {
    final routeMode = segMeta['route_mode'] as String? ?? 'rail';
    final degraded = segMeta['route_degraded'] == true;
    _patchSegmentFields(segId, {
      'route_mode': routeMode,
      'route_status': 'resolved',
      'route_error': null,
      'route_degraded': degraded,
      'route_polyline': segMeta['route_polyline'],
      if (segMeta['train_number'] != null) 'train_number': segMeta['train_number'],
      if (segMeta['hafas_provider'] != null) 'hafas_provider': segMeta['hafas_provider'],
    });
    final coords = _decodePolyline(segMeta['route_polyline']);
    if (coords.isEmpty) return;
    upsertSegmentInGeo(segId, {
      'type': 'Feature',
      'geometry': {'type': 'LineString', 'coordinates': coords},
      'properties': {
        'type': 'segment',
        'segment_id': segId,
        'route_mode': routeMode,
        'route_degraded': degraded,
        if (segMeta['segment_type'] != null) 'segment_type': segMeta['segment_type'],
      },
    });
  }

  /// Decode a stored `route_polyline` (JSON string `[[lon,lat],…]`) to coords.
  List<List<double>> _decodePolyline(Object? raw) {
    if (raw == null) return const [];
    final decoded = raw is String ? jsonDecode(raw) : raw;
    if (decoded is! List) return const [];
    return decoded
        .map((pt) => (pt is List && pt.length >= 2)
            ? [(pt[0] as num).toDouble(), (pt[1] as num).toDouble()]
            : null)
        .whereType<List<double>>()
        .toList();
  }

  int _polylineLength(Map<String, dynamic> segMeta) =>
      _decodePolyline(segMeta['route_polyline']).length;

  /// Immediately remove a segment from the local list and map — no server call.
  /// Replaces `items` with a new list so the identity check in
  /// _rebuildDisplayList detects the change and removes the dismissed widget
  /// from the tree before the SnackBar fires.
  void removeSegmentLocally(String segId) {
    items = items
        .where((item) =>
            !(item['item_type'] == 'segment' &&
              item['segment']?['id']?.toString() == segId))
        .toList();
    removeSegmentFromGeo(segId);
    notifyListeners();
  }

  Future<void> deleteSegment(String segId) async {
    final ref = projectRef;
    if (ref == null) return;
    // removeSegmentLocally already called via onOptimistic before the undo window.
    // No reload needed — reloading would bring back other pending-delete segments
    // (still in the DB) and cause ghost reappearances while their toasts are active.
    try {
      await api.delete(ref.path('/segments/${Uri.encodeComponent(segId)}'));
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
    }
  }

  // ── Geo patch helpers ─────────────────────────────────────────────────────
  //
  // Segment edits patch [geo] directly, but [geo] can be null during the load
  // window and is rebuilt from a (possibly stale) server snapshot by
  // _loadFullGeoProgressively. To stop patches being lost or ghost-restored,
  // every upsert/remove is also recorded in a durable overlay that is re-applied
  // whenever geo is rebuilt (see mergePendingSegmentPatches).

  /// Pending segment features keyed by segment_id, awaiting (re)application.
  final Map<String, Map<String, dynamic>> _pendingSegmentPatches = {};

  /// Segment ids the user has removed — suppressed even if a stale server geo
  /// snapshot still contains them.
  final Set<String> _segmentTombstones = {};

  /// Upsert a segment feature into [geo] by segment_id (adds if absent).
  void upsertSegmentInGeo(String segId, Map<String, dynamic> feature) {
    _pendingSegmentPatches[segId] = feature;
    _segmentTombstones.remove(segId);
    final current = geo;
    if (current == null) return; // overlay re-applies it when geo is rebuilt
    final features = List<dynamic>.from(current['features'] as List? ?? []);
    final idx = features.indexWhere(
        (f) => (f as Map)['properties']?['segment_id']?.toString() == segId);
    if (idx >= 0) {
      features[idx] = feature;
    } else {
      features.add(feature);
    }
    geo = {'type': 'FeatureCollection', 'features': features};
  }

  /// Remove a segment feature from [geo] by segment_id.
  void removeSegmentFromGeo(String segId) {
    _pendingSegmentPatches.remove(segId);
    _segmentTombstones.add(segId);
    final current = geo;
    if (current == null) return;
    final features = List<dynamic>.from(current['features'] as List? ?? []);
    features.removeWhere(
        (f) => (f as Map)['properties']?['segment_id']?.toString() == segId);
    geo = {'type': 'FeatureCollection', 'features': features};
  }

  /// Merge the durable overlay onto a freshly-rebuilt feature [list]: drop
  /// tombstoned segments and (re)apply pending segment patches. Returns a new
  /// list. Call this whenever [geo] is rebuilt from a server snapshot.
  List<dynamic> mergePendingSegmentPatches(List<dynamic> list) {
    final out = <dynamic>[
      for (final f in list)
        if (!(f is Map &&
            _segmentTombstones.contains(
                (f['properties'] as Map? ?? {})['segment_id']?.toString())))
          f,
    ];
    _pendingSegmentPatches.forEach((segId, feature) {
      final idx = out.indexWhere((f) =>
          f is Map &&
          (f['properties'] as Map? ?? {})['segment_id']?.toString() == segId);
      if (idx >= 0) {
        out[idx] = feature;
      } else {
        out.add(feature);
      }
    });
    return out;
  }

  /// Drop overlay entries the authoritative server [serverGeo] already reflects,
  /// so the overlay self-cleans once the backend has caught up. A pending patch
  /// is cleared when the server geo contains its segment_id; a tombstone is
  /// cleared when the server geo no longer contains its segment_id.
  void reconcileSegmentOverlay(Map<String, dynamic> serverGeo) {
    final serverSegIds = <String>{
      for (final f in (serverGeo['features'] as List? ?? const []))
        if (f is Map &&
            (f['properties'] as Map? ?? {})['segment_id'] != null)
          (f['properties'] as Map)['segment_id'].toString(),
    };
    _pendingSegmentPatches.keys
        .where(serverSegIds.contains)
        .toList()
        .forEach(_pendingSegmentPatches.remove);
    _segmentTombstones.removeWhere((id) => !serverSegIds.contains(id));
  }

  /// Clear the overlay — call when switching projects.
  void clearSegmentOverlay() {
    _pendingSegmentPatches.clear();
    _segmentTombstones.clear();
  }

  // ── Geometry (SLERP great-circle, mirrors src/models/great_circle.py) ─────

  static List<List<double>> _greatCircleCoords(
      double lat1, double lon1, double lat2, double lon2, {int n = 50}) {
    double r(double d) => d * math.pi / 180;
    double d(double r) => r * 180 / math.pi;

    final p1 = r(lat1), l1 = r(lon1), p2 = r(lat2), l2 = r(lon2);
    final x1 = math.cos(p1) * math.cos(l1);
    final y1 = math.cos(p1) * math.sin(l1);
    final z1 = math.sin(p1);
    final x2 = math.cos(p2) * math.cos(l2);
    final y2 = math.cos(p2) * math.sin(l2);
    final z2 = math.sin(p2);

    final dot = (x1 * x2 + y1 * y2 + z1 * z2).clamp(-1.0, 1.0);
    final omega = math.acos(dot);

    if (omega < 1e-10 || (omega - math.pi).abs() < 1e-10) {
      return [[lon1, lat1], [lon2, lat2]];
    }
    final sinOmega = math.sin(omega);
    return List.generate(n, (i) {
      final t = i / (n - 1);
      final k1 = math.sin((1 - t) * omega) / sinOmega;
      final k2 = math.sin(t * omega) / sinOmega;
      final lat = d(math.asin((k1 * z1 + k2 * z2).clamp(-1.0, 1.0)));
      final lon = d(math.atan2(k1 * y1 + k2 * y2, k1 * x1 + k2 * x2));
      return [lon, lat];
    });
  }

  static Map<String, dynamic> _segmentFeature(
      String id, String type, String label,
      double startLat, double startLon, double endLat, double endLon) {
    return {
      'type': 'Feature',
      'geometry': {
        'type': 'LineString',
        'coordinates': _greatCircleCoords(startLat, startLon, endLat, endLon),
      },
      'properties': {
        'type': 'segment',
        'segment_id': id,
        'segment_type': type,
        'label': label,
      },
    };
  }
}
