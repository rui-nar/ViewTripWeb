/// Dedicated full-screen editor for a single activity's track geometry (#31).
///
/// Presents a map (full polyline always drawn; draggable vertex handles only
/// materialised for the portion currently in view, per the perf requirement)
/// above a synced elevation chart, plus a tool bar for Trim / Add / Remove /
/// Split and Save / Reset-to-Strava actions. All edit logic lives in
/// [TrackEditorController] + [TrackEditModel]; this widget is the rendering and
/// gesture layer, and persists through [ProjectNotifier].
library;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';

import '../core/design_tokens.dart';
import '../map/geo_point.dart';
import 'basemaps.dart';
import 'elevation_chart.dart';
import 'project_notifier.dart';
import 'track_edit_model.dart';
import 'track_editor_controller.dart';

/// Build the [TrackEditModel] for [activity] from its stored polyline +
/// elevation profile pairs (`[[distKm, elevM], …]`).
TrackEditModel modelForActivity(Map<String, dynamic> activity) {
  final poly = (activity['map'] as Map?)?['summary_polyline'] as String?;
  final rawEp = activity['elevation_profile'];
  List<List<double>>? pairs;
  if (rawEp is List) {
    pairs = [
      for (final p in rawEp)
        if (p is List && p.length >= 2)
          [(p[0] as num).toDouble(), (p[1] as num).toDouble()],
    ];
    if (pairs.isEmpty) pairs = null;
  }
  return TrackEditModel.fromEncoded(poly, pairs);
}

class ActivityEditorPage extends StatefulWidget {
  final ProjectNotifier notifier;
  final Map<String, dynamic> activity;

  const ActivityEditorPage({
    super.key,
    required this.notifier,
    required this.activity,
  });

  @override
  State<ActivityEditorPage> createState() => _ActivityEditorPageState();
}

class _ActivityEditorPageState extends State<ActivityEditorPage> {
  late final TrackEditorController _c;
  final MapController _map = MapController();
  final ValueNotifier<double?> _chartCursor = ValueNotifier(null);

  bool _saving = false;
  // Current visible map bounds; drives which vertex handles are materialised.
  LatLngBounds? _bounds;

  int get _activityId => (widget.activity['id'] as num).toInt();
  bool get _isEdited => widget.activity['is_edited'] == true;

  /// Test-only access to the editor controller so widget tests can drive edits
  /// without simulating map-tile gestures.
  @visibleForTesting
  TrackEditorController get editorControllerForTest => _c;

  @override
  void initState() {
    super.initState();
    _c = TrackEditorController(modelForActivity(widget.activity));
    _c.addListener(_onChange);
  }

  @override
  void dispose() {
    _c.removeListener(_onChange);
    _c.dispose();
    _chartCursor.dispose();
    super.dispose();
  }

  void _onChange() => setState(() {});

  // ── Map interactions ────────────────────────────────────────────────────

  /// Nearest vertex index to [tap] within a pixel threshold, or null.
  int? _nearestVertex(LatLng tap) {
    final pts = _c.points;
    if (pts.isEmpty) return null;
    int best = 0;
    double bestD = double.infinity;
    for (var i = 0; i < pts.length; i++) {
      final dLat = pts[i].lat - tap.latitude;
      final dLng = pts[i].lng - tap.longitude;
      final d = dLat * dLat + dLng * dLng;
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    }
    return best;
  }

  /// Index of the segment (its start vertex) nearest to [tap], for inserts.
  int _nearestSegment(LatLng tap) {
    final pts = _c.points;
    if (pts.length < 2) return -1;
    int best = 0;
    double bestD = double.infinity;
    for (var i = 0; i < pts.length - 1; i++) {
      final mLat = (pts[i].lat + pts[i + 1].lat) / 2;
      final mLng = (pts[i].lng + pts[i + 1].lng) / 2;
      final dLat = mLat - tap.latitude;
      final dLng = mLng - tap.longitude;
      final d = dLat * dLat + dLng * dLng;
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    }
    return best;
  }

  void _onMapTap(LatLng tap) {
    switch (_c.tool) {
      case EditTool.add:
        final seg = _nearestSegment(tap);
        if (seg >= 0) {
          _c.addPointAfter(seg, EditPoint(tap.latitude, tap.longitude));
        }
        break;
      case EditTool.remove:
      case EditTool.split:
        _c.selectVertex(_nearestVertex(tap));
        break;
      case EditTool.trim:
        break;
    }
  }

  // ── Actions ────────────────────────────────────────────────────────────────

  Future<void> _save() async {
    if (!_c.canSave || _saving) return;
    setState(() => _saving = true);
    final messenger = ScaffoldMessenger.of(context);
    final navigator = Navigator.of(context);
    try {
      await widget.notifier.saveActivityTrack(_activityId, _c.toSavePayload());
      if (!mounted) return;
      navigator.pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() => _saving = false);
      messenger.showSnackBar(SnackBar(content: Text('Save failed: $e')));
    }
  }

  Future<void> _reset() async {
    setState(() => _saving = true);
    final messenger = ScaffoldMessenger.of(context);
    final navigator = Navigator.of(context);
    try {
      await widget.notifier.resetActivityTrack(_activityId);
      if (!mounted) return;
      navigator.pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() => _saving = false);
      messenger.showSnackBar(SnackBar(content: Text('Reset failed: $e')));
    }
  }

  Future<void> _confirmSplit(int index) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Split activity'),
        content: Text(
          'Split into two activities at point ${index + 1}? '
          'The second half becomes a new local activity.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Split'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => _saving = true);
    final messenger = ScaffoldMessenger.of(context);
    final navigator = Navigator.of(context);
    try {
      await widget.notifier.splitActivity(_activityId, index);
      if (!mounted) return;
      navigator.pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() => _saving = false);
      messenger.showSnackBar(SnackBar(content: Text('Split failed: $e')));
    }
  }

  // ── Handle materialisation (perf) ────────────────────────────────────────

  /// Vertex indices whose points fall within the current map bounds. Only
  /// these are turned into draggable handles so a thousands-point track stays
  /// responsive; the full polyline is always drawn regardless.
  List<int> _visibleVertexIndices() {
    final b = _bounds;
    final pts = _c.points;
    if (b == null) return [for (var i = 0; i < pts.length; i++) i];
    final out = <int>[];
    for (var i = 0; i < pts.length; i++) {
      if (b.contains(LatLng(pts[i].lat, pts[i].lng))) out.add(i);
    }
    return out;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final pts = _c.points;
    final polyline = [for (final p in pts) LatLng(p.lat, p.lng)];
    final center = polyline.isNotEmpty ? polyline.first : const LatLng(0, 0);

    return Scaffold(
      appBar: AppBar(
        title: Text(
          'Edit — ${widget.activity['name'] ?? 'Activity'}',
          style: theme.textTheme.titleMedium,
        ),
        actions: [
          if (_isEdited)
            TextButton.icon(
              onPressed: _saving ? null : _reset,
              icon: const Icon(Icons.restore, size: 18),
              label: const Text('Reset to Strava'),
            ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8),
            child: FilledButton(
              onPressed: (_c.canSave && !_saving) ? _save : null,
              child: _saving
                  ? const SizedBox(
                      width: 16, height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2))
                  : const Text('Save'),
            ),
          ),
        ],
      ),
      body: Column(
        children: [
          _ToolBar(controller: _c),
          Expanded(
            child: Stack(
              children: [
                FlutterMap(
                  mapController: _map,
                  options: MapOptions(
                    initialCenter: center,
                    initialZoom: 12,
                    interactionOptions: const InteractionOptions(
                      flags:
                          InteractiveFlag.all & ~InteractiveFlag.rotate,
                    ),
                    onTap: (_, latlng) => _onMapTap(latlng),
                    onPositionChanged: (camera, _) =>
                        setState(() => _bounds = camera.visibleBounds),
                  ),
                  children: [
                    TileLayer(
                      urlTemplate: kActiveManageBasemapUrl,
                      subdomains: kActiveManageSubdomains,
                      userAgentPackageName: 'com.viewtrip.client',
                      maxNativeZoom: 20,
                    ),
                    if (polyline.length >= 2)
                      PolylineLayer(
                        polylines: [
                          Polyline(
                            points: polyline,
                            color: kAccent,
                            strokeWidth: 3,
                          ),
                        ],
                        simplificationTolerance: 0.5,
                      ),
                    MarkerLayer(markers: _buildHandleMarkers()),
                  ],
                ),
                if (_c.tool == EditTool.split && _c.selectedIndex != null)
                  _SplitConfirmBanner(
                    index: _c.selectedIndex!,
                    canSplit: _c.canSplitAt(_c.selectedIndex!),
                    onConfirm: () => _confirmSplit(_c.selectedIndex!),
                  ),
              ],
            ),
          ),
          // Elevation chart synced to the current point list.
          Container(
            padding: const EdgeInsets.fromLTRB(8, 4, 8, 8),
            color: theme.colorScheme.surface,
            child: ElevationChart(
              activities: [_chartActivity(pts)],
              track: _chartTrack(pts),
              mapCursorNotifier: _chartCursor,
              color: kAccent,
            ),
          ),
        ],
      ),
    );
  }

  List<Marker> _buildHandleMarkers() {
    final pts = _c.points;
    final markers = <Marker>[];
    final tool = _c.tool;
    for (final i in _visibleVertexIndices()) {
      final selected = _c.selectedIndex == i;
      final trimEdge = tool == EditTool.trim &&
          (i == _c.trimStart || i == _c.trimEnd);
      final handle = _VertexHandle(
        selected: selected || trimEdge,
        onTap: () {
          if (tool == EditTool.remove || tool == EditTool.split) {
            _c.selectVertex(i);
          }
        },
      );
      markers.add(Marker(
        point: LatLng(pts[i].lat, pts[i].lng),
        width: 18,
        height: 18,
        child: (tool == EditTool.trim)
            ? handle
            : Draggable<int>(
                data: i,
                feedback: const SizedBox.shrink(),
                onDragEnd: (_) {},
                child: handle,
              ),
      ));
    }
    return markers;
  }

  /// Wrap the current points as a pseudo-activity for [ElevationChart], which
  /// reads `elevation_profile` as `[[distKm, elevM], …]`.
  Map<String, dynamic> _chartActivity(List<EditPoint> pts) {
    final profile = <List<double>>[];
    double cum = 0;
    for (var i = 0; i < pts.length; i++) {
      if (i > 0) {
        cum += _haversineKm(pts[i - 1], pts[i]);
      }
      profile.add([cum, pts[i].elev ?? 0]);
    }
    return {
      'id': _activityId,
      'elevation_profile': profile,
    };
  }

  List<(double, GeoPoint)> _chartTrack(List<EditPoint> pts) {
    final track = <(double, GeoPoint)>[];
    double cum = 0;
    for (var i = 0; i < pts.length; i++) {
      if (i > 0) cum += _haversineKm(pts[i - 1], pts[i]);
      track.add((cum, (lat: pts[i].lat, lon: pts[i].lng)));
    }
    return track;
  }

  static double _haversineKm(EditPoint a, EditPoint b) {
    const distance = Distance();
    return distance.as(
          LengthUnit.Meter,
          LatLng(a.lat, a.lng),
          LatLng(b.lat, b.lng),
        ) /
        1000.0;
  }
}

// ── Tool bar ─────────────────────────────────────────────────────────────────

class _ToolBar extends StatelessWidget {
  final TrackEditorController controller;
  const _ToolBar({required this.controller});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Material(
      color: theme.colorScheme.surfaceContainerHighest,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        child: Row(
          children: [
            SegmentedButton<EditTool>(
              showSelectedIcon: false,
              segments: const [
                ButtonSegment(
                    value: EditTool.trim,
                    icon: Icon(Icons.content_cut, size: 18),
                    label: Text('Trim')),
                ButtonSegment(
                    value: EditTool.add,
                    icon: Icon(Icons.add_location_alt_outlined, size: 18),
                    label: Text('Add')),
                ButtonSegment(
                    value: EditTool.remove,
                    icon: Icon(Icons.wrong_location_outlined, size: 18),
                    label: Text('Remove')),
                ButtonSegment(
                    value: EditTool.split,
                    icon: Icon(Icons.call_split, size: 18),
                    label: Text('Split')),
              ],
              selected: {controller.tool},
              onSelectionChanged: (s) => controller.tool = s.first,
            ),
            const Spacer(),
            if (controller.tool == EditTool.trim)
              TextButton.icon(
                onPressed: controller.model.isValid ? controller.applyTrim : null,
                icon: const Icon(Icons.check, size: 18),
                label: const Text('Apply trim'),
              ),
            if (controller.tool == EditTool.remove)
              TextButton.icon(
                onPressed: controller.selectedIndex != null
                    ? () => controller.removeSelected()
                    : null,
                icon: const Icon(Icons.delete_outline, size: 18),
                label: const Text('Delete point'),
              ),
          ],
        ),
      ),
    );
  }
}

class _VertexHandle extends StatelessWidget {
  final bool selected;
  final VoidCallback onTap;
  const _VertexHandle({required this.selected, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        decoration: BoxDecoration(
          color: selected ? kAccent : Colors.white,
          shape: BoxShape.circle,
          border: Border.all(color: kAccent, width: 2),
        ),
      ),
    );
  }
}

class _SplitConfirmBanner extends StatelessWidget {
  final int index;
  final bool canSplit;
  final VoidCallback onConfirm;
  const _SplitConfirmBanner({
    required this.index,
    required this.canSplit,
    required this.onConfirm,
  });

  @override
  Widget build(BuildContext context) {
    return Positioned(
      left: 12,
      right: 12,
      bottom: 12,
      child: Material(
        elevation: 4,
        borderRadius: BorderRadius.circular(8),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          child: Row(
            children: [
              Expanded(
                child: Text(canSplit
                    ? 'Split here (point ${index + 1})?'
                    : 'Pick an interior point to split'),
              ),
              FilledButton(
                onPressed: canSplit ? onConfirm : null,
                child: const Text('Split'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
