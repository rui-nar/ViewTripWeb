/// Dedicated full-screen editor for a transport segment's route geometry
/// (ferry/rail/bus, issue #150).
///
/// Mirrors [ActivityEditorPage]: same map/gesture chrome via [TrackMapEditor],
/// same [TrackEditorController]/[TrackEditModel] edit model, same Save button.
/// Differences are deliberate and narrow — no elevation chart (segments carry
/// no elevation data) and no split/cut-for-transport (segments have fixed
/// start/end anchors, not an independently splittable track), so the point
/// menu only offers trim and delete.
library;

import 'dart:convert';

import 'package:flutter/material.dart';

import '../core/design_tokens.dart';
import 'project_notifier.dart';
import 'track_edit_model.dart';
import 'track_editor_controller.dart';
import 'track_map_editor.dart';

/// Build the [TrackEditModel] for [segment] from its stored `route_polyline`
/// (`[[lon,lat],…]`, no elevation). Falls back to a straight two-point line
/// between the segment's `start`/`end` anchors when no route has been
/// resolved or drawn yet — the "route doesn't exist" case from issue #150,
/// not just "malformed".
TrackEditModel modelForSegment(Map<String, dynamic> segment) {
  final polyStr = segment['route_polyline'] as String?;
  if (polyStr != null && polyStr.isNotEmpty) {
    List<List<double>>? coords;
    try {
      final decoded = jsonDecode(polyStr);
      if (decoded is List) {
        coords = [
          for (final pt in decoded)
            if (pt is List && pt.length >= 2)
              [(pt[0] as num).toDouble(), (pt[1] as num).toDouble()],
        ];
      }
    } catch (_) {
      coords = null;
    }
    if (coords != null && coords.length >= 2) {
      return TrackEditModel.fromLonLat(coords);
    }
  }

  final start = segment['start'] as Map?;
  final end = segment['end'] as Map?;
  final sLat = (start?['lat'] as num?)?.toDouble();
  final sLon = (start?['lon'] as num?)?.toDouble();
  final eLat = (end?['lat'] as num?)?.toDouble();
  final eLon = (end?['lon'] as num?)?.toDouble();
  if (sLat == null || sLon == null || eLat == null || eLon == null) {
    return TrackEditModel.fromLonLat(const []);
  }
  return TrackEditModel.fromLonLat([
    [sLon, sLat],
    [eLon, eLat],
  ]);
}

class SegmentTrackEditorPage extends StatefulWidget {
  final ProjectNotifier notifier;
  final Map<String, dynamic> segment;

  const SegmentTrackEditorPage({
    super.key,
    required this.notifier,
    required this.segment,
  });

  @override
  State<SegmentTrackEditorPage> createState() =>
      _SegmentTrackEditorPageState();
}

class _SegmentTrackEditorPageState extends State<SegmentTrackEditorPage> {
  late final TrackEditorController _c;
  bool _saving = false;

  String get _segId => widget.segment['id'] as String;

  /// Test-only access to the editor controller, mirroring
  /// [ActivityEditorPage.editorControllerForTest].
  @visibleForTesting
  TrackEditorController get editorControllerForTest => _c;

  @override
  void initState() {
    super.initState();
    _c = TrackEditorController(modelForSegment(widget.segment));
    _c.addListener(_onChange);
  }

  @override
  void dispose() {
    _c.removeListener(_onChange);
    _c.dispose();
    super.dispose();
  }

  void _onChange() => setState(() {});

  // ── Per-point context menu ───────────────────────────────────────────────

  List<PointMenuAction> _actionsForPoint(int index) {
    final last = _c.points.length - 1;
    return [
      PointMenuAction(
        label: 'Trim: keep from here',
        icon: Icons.first_page,
        enabled: index > 0,
        onSelected: (ctx, i) async => _c.trimFrom(i),
      ),
      PointMenuAction(
        label: 'Trim: keep up to here',
        icon: Icons.last_page,
        enabled: index < last,
        onSelected: (ctx, i) async => _c.trimTo(i),
      ),
      PointMenuAction(
        label: 'Delete point',
        icon: Icons.delete_outline,
        enabled: _c.points.length > 2,
        color: kAccent,
        dividerBefore: true,
        onSelected: (ctx, i) async => _c.removeSelected(i),
      ),
    ];
  }

  // ── Actions ────────────────────────────────────────────────────────────────

  Future<void> _save() async {
    if (!_c.canSave || _saving) return;
    setState(() => _saving = true);
    final messenger = ScaffoldMessenger.of(context);
    final navigator = Navigator.of(context);
    try {
      await widget.notifier.saveSegmentTrack(_segId, _c.toSavePayload());
      if (!mounted) return;
      navigator.pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() => _saving = false);
      messenger.showSnackBar(SnackBar(content: Text('Save failed: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final label = (widget.segment['label'] as String?)?.trim();
    final title = (label != null && label.isNotEmpty)
        ? label
        : (widget.segment['segment_type'] as String? ?? 'Segment');

    return Scaffold(
      appBar: AppBar(
        title: Text('Edit route — $title', style: theme.textTheme.titleMedium),
        actions: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
            child: TrackEditorSaveButton(
              enabled: _c.canSave && !_saving,
              saving: _saving,
              onPressed: _save,
            ),
          ),
        ],
      ),
      body: TrackMapEditor(
        controller: _c,
        actionsForPoint: _actionsForPoint,
        pointMenuHint: 'Long-press or right-click a point to trim or delete',
      ),
    );
  }
}
