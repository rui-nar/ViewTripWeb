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

/// Actions offered by the per-point context menu (long-press / right-click).
enum _PointAction { trimFrom, trimTo, split, delete }

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
  // Anchors screen→LatLng conversions for vertex drags to the map's own box.
  final GlobalKey _mapKey = GlobalKey();
  final ValueNotifier<double?> _chartCursor = ValueNotifier(null);

  bool _saving = false;
  // When on, tapping the map inserts a point; point-specific edits (trim / split
  // / delete) are always available via a per-point long-press / right-click menu.
  bool _addMode = false;
  // Current visible map bounds; drives which vertex handles are materialised.
  LatLngBounds? _bounds;
  // Live drag state: the vertex being dragged and its provisional position, so
  // the handle and its adjacent polyline segments follow the finger before the
  // move is committed on drop via [TrackEditorController.moveVertex]. The drag is
  // driven by raw pointer events (a [Listener]) rather than a pan gesture so it
  // wins over flutter_map's own scale/drag recognizer; the map is locked for the
  // duration so it can't pan underneath the moving vertex.
  int? _dragIndex;
  LatLng? _dragLatLng;
  int? _dragPointer;
  Offset? _dragStartGlobal;
  bool _dragging = false;
  // True while a pointer is down on a vertex handle: disables map interaction so
  // grabbing a vertex never pans/zooms the map.
  bool _mapLocked = false;

  // Distance (logical px) a pointer must travel before a press becomes a drag,
  // so a stationary long-press still opens the context menu instead of moving.
  static const double _dragSlop = 8;

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
    if (!_addMode) return;
    final seg = _nearestSegment(tap);
    if (seg >= 0) {
      _c.addPointAfter(seg, EditPoint(tap.latitude, tap.longitude));
    }
  }

  // ── Vertex drag (issue #36) ──────────────────────────────────────────────

  /// Convert a drag's global position to a map [LatLng] using the map camera.
  /// Coordinates are taken relative to the map's own render box so the marker's
  /// tiny handle box does not skew the unprojection.
  LatLng? _globalToLatLng(Offset globalPos) {
    final box = _mapKey.currentContext?.findRenderObject() as RenderBox?;
    if (box == null) return null;
    return _map.camera.offsetToCrs(box.globalToLocal(globalPos));
  }

  void _onVertexPointerDown(int index, PointerDownEvent e) {
    _dragPointer = e.pointer;
    _dragStartGlobal = e.position;
    _dragIndex = index;
    _dragging = false;
    // Lock the map immediately so it cannot pan out from under a grabbed vertex.
    setState(() => _mapLocked = true);
  }

  void _onVertexPointerMove(PointerMoveEvent e) {
    if (e.pointer != _dragPointer || _dragIndex == null) return;
    if (!_dragging) {
      if ((e.position - _dragStartGlobal!).distance < _dragSlop) return;
      _dragging = true; // crossed the slop → this is a drag, not a long-press
    }
    final ll = _globalToLatLng(e.position);
    if (ll == null) return;
    setState(() => _dragLatLng = ll);
  }

  void _onVertexPointerUp(PointerEvent e) {
    if (e.pointer != _dragPointer) return;
    final index = _dragIndex;
    final ll = _dragLatLng;
    final moved = _dragging;
    _dragPointer = null;
    _dragStartGlobal = null;
    _dragging = false;
    setState(() {
      _mapLocked = false;
      _dragIndex = null;
      _dragLatLng = null;
    });
    if (moved && index != null && ll != null) {
      _c.moveVertex(index, ll.latitude, ll.longitude);
    }
  }

  /// Per-point context menu (long-press on touch, right-click on web/desktop):
  /// Trim / Split / Delete for the vertex at [index], anchored at [globalPos].
  Future<void> _showPointMenu(int index, Offset globalPos) async {
    final overlay =
        Overlay.of(context).context.findRenderObject() as RenderBox;
    final last = _c.points.length - 1;
    final action = await showMenu<_PointAction>(
      context: context,
      position: RelativeRect.fromLTRB(
        globalPos.dx,
        globalPos.dy,
        overlay.size.width - globalPos.dx,
        overlay.size.height - globalPos.dy,
      ),
      items: [
        _menuItem(_PointAction.trimFrom, Icons.first_page,
            'Trim: keep from here', index > 0),
        _menuItem(_PointAction.trimTo, Icons.last_page,
            'Trim: keep up to here', index < last),
        _menuItem(_PointAction.split, Icons.call_split, 'Split here',
            _c.canSplitAt(index)),
        const PopupMenuDivider(),
        _menuItem(_PointAction.delete, Icons.delete_outline, 'Delete point',
            _c.points.length > 2,
            color: kAccent),
      ],
    );
    if (action == null || !mounted) return;
    switch (action) {
      case _PointAction.trimFrom:
        _c.trimFrom(index);
        break;
      case _PointAction.trimTo:
        _c.trimTo(index);
        break;
      case _PointAction.split:
        await _confirmSplit(index);
        break;
      case _PointAction.delete:
        _c.removeSelected(index);
        break;
    }
  }

  PopupMenuItem<_PointAction> _menuItem(
    _PointAction value,
    IconData icon,
    String label,
    bool enabled, {
    Color? color,
  }) =>
      PopupMenuItem<_PointAction>(
        value: value,
        enabled: enabled,
        child: Row(
          children: [
            Icon(icon, size: 18, color: color),
            const SizedBox(width: 12),
            Flexible(
              child: Text(
                label,
                style: TextStyle(color: color),
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ],
        ),
      );

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
    // Live-preview the dragged vertex so its adjacent segments follow the finger.
    final polyline = [
      for (var i = 0; i < pts.length; i++)
        (i == _dragIndex && _dragLatLng != null)
            ? _dragLatLng!
            : LatLng(pts[i].lat, pts[i].lng),
    ];
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
              style: TextButton.styleFrom(
                foregroundColor: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
            child: _MetallicSaveButton(
              enabled: _c.canSave && !_saving,
              saving: _saving,
              onPressed: _save,
            ),
          ),
        ],
      ),
      body: Column(
        children: [
          _ToolBar(
            addMode: _addMode,
            onAddModeChanged: (v) => setState(() => _addMode = v),
          ),
          Expanded(
            child: Stack(
              children: [
                FlutterMap(
                  key: _mapKey,
                  mapController: _map,
                  options: MapOptions(
                    initialCenter: center,
                    initialZoom: 12,
                    interactionOptions: InteractionOptions(
                      // Locked while a vertex is being dragged so the map can't
                      // pan/zoom out from under the grabbed handle.
                      flags: _mapLocked
                          ? InteractiveFlag.none
                          : InteractiveFlag.all & ~InteractiveFlag.rotate,
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
    for (final i in _visibleVertexIndices()) {
      final point = (i == _dragIndex && _dragLatLng != null)
          ? _dragLatLng!
          : LatLng(pts[i].lat, pts[i].lng);
      markers.add(Marker(
        point: point,
        width: 22,
        height: 22,
        child: Listener(
          key: ValueKey('vertex_$i'),
          onPointerDown: (e) => _onVertexPointerDown(i, e),
          onPointerMove: _onVertexPointerMove,
          onPointerUp: _onVertexPointerUp,
          onPointerCancel: _onVertexPointerUp,
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onLongPressStart: (d) => _showPointMenu(i, d.globalPosition),
            onSecondaryTapDown: (d) => _showPointMenu(i, d.globalPosition),
            child: const _VertexHandle(),
          ),
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
  final bool addMode;
  final ValueChanged<bool> onAddModeChanged;
  const _ToolBar({required this.addMode, required this.onAddModeChanged});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Material(
      color: theme.colorScheme.surfaceContainerHighest,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
        child: Row(
          children: [
            FilterChip(
              avatar: const Icon(Icons.add_location_alt_outlined, size: 18),
              label: const Text('Add points'),
              selected: addMode,
              showCheckmark: false,
              selectedColor: kAccentSoft,
              onSelected: onAddModeChanged,
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                addMode
                    ? 'Tap the map to insert a point'
                    : 'Long-press or right-click a point to trim, split or delete',
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _VertexHandle extends StatelessWidget {
  const _VertexHandle();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Container(
        width: 14,
        height: 14,
        decoration: BoxDecoration(
          color: Colors.white,
          shape: BoxShape.circle,
          border: Border.all(color: kAccent, width: 2),
        ),
      ),
    );
  }
}

// ── Save button (metallic, per design system) ────────────────────────────────

class _MetallicSaveButton extends StatelessWidget {
  final bool enabled;
  final bool saving;
  final VoidCallback onPressed;

  const _MetallicSaveButton({
    required this.enabled,
    required this.saving,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final fg = enabled ? Colors.white : cs.onSurfaceVariant;
    return DecoratedBox(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(8),
        gradient: enabled ? metallicBlue(Theme.of(context).brightness) : null,
        color: enabled ? null : cs.surfaceContainerHighest,
      ),
      child: TextButton.icon(
        onPressed: enabled ? onPressed : null,
        icon: saving
            ? SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(strokeWidth: 2, color: fg),
              )
            : Icon(Icons.check, size: 17, color: fg),
        label: Text('Save',
            style: TextStyle(color: fg, fontWeight: FontWeight.w600)),
        style: TextButton.styleFrom(
          minimumSize: const Size(0, 36),
          padding: const EdgeInsets.symmetric(horizontal: 16),
        ),
      ),
    );
  }
}
