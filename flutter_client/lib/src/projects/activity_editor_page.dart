/// Dedicated full-screen editor for a single activity's track geometry (#31).
///
/// Presents a map (full polyline always drawn; draggable vertex handles only
/// materialised for the portion currently in view, per the perf requirement)
/// above a synced elevation chart, plus a tool bar for Trim / Add / Remove /
/// Split and Save / Reset-to-Strava actions. All edit logic lives in
/// [TrackEditorController] + [TrackEditModel]; the map/gesture chrome lives in
/// [TrackMapEditor] (shared with the segment track editor, issue #150); this
/// widget supplies the activity-specific menu actions and persists through
/// [ProjectNotifier].
library;

import 'package:flutter/material.dart';
import 'package:latlong2/latlong.dart';

import '../api/client.dart';
import '../core/design_tokens.dart';
import '../map/geo_point.dart';
import 'elevation_chart.dart';
import 'project_notifier.dart';
import 'track_edit_model.dart';
import 'track_editor_controller.dart';
import 'track_map_editor.dart';

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
  final ValueNotifier<double?> _chartCursor = ValueNotifier(null);

  bool _saving = false;

  int get _activityId => (widget.activity['id'] as num).toInt();
  bool get _isEdited => widget.activity['is_edited'] == true;

  /// The project's lock_version as of when this activity was fetched for
  /// editing (see GET .../track) — sent back on save/split so the server can
  /// reject a stale write with 409 if the project changed elsewhere since
  /// (issue #31). Null on an older cached payload that predates the field,
  /// in which case the save/split proceeds unconditionally.
  int? get _lockVersion => (widget.activity['lock_version'] as num?)?.toInt();

  /// Local activities (split tails, added transport) carry a synthetic negative
  /// id and never came from Strava, so there is no Strava original to reset to —
  /// reset only undoes edits made since the piece was created (issue #131).
  bool get _isLocal => _activityId < 0;

  /// How many pieces resetting this activity would destroy.
  ///
  /// Reset restores the track this activity held before its last edit, which on
  /// anything that has been split spans the pieces cut out of it — so the server
  /// deletes them rather than leave them duplicating the restored track. That is
  /// the whole family on a root (issue #141) and just its own children on a piece
  /// that was itself split again (issue #143), which is exactly the transitive
  /// walk of split_parent_id below. An activity with no pieces under it returns
  /// 0 and resets silently, undoing only its own edits (issue #131).
  int get _splitPiecesRemovedByReset {
    final acts = widget.notifier.activities;
    final removed = <int>{};
    var frontier = {_activityId};
    while (frontier.isNotEmpty) {
      final children = <int>{};
      for (final a in acts) {
        final id = (a['id'] as num?)?.toInt();
        final parent = (a['split_parent_id'] as num?)?.toInt();
        if (id != null &&
            parent != null &&
            frontier.contains(parent) &&
            id != _activityId &&
            removed.add(id)) {
          children.add(id);
        }
      }
      frontier = children;
    }
    return removed.length;
  }

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
        label: 'Split here',
        icon: Icons.call_split,
        enabled: _c.canSplitAt(index),
        onSelected: (ctx, i) => _confirmSplit(i),
      ),
      PointMenuAction(
        label: 'Cut & add transport',
        icon: Icons.alt_route,
        enabled: _c.canCutForTransport(index),
        onSelected: (ctx, i) => _confirmCutForTransport(i),
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

  /// True for the 409 the server returns when this activity's project changed
  /// elsewhere since the editor loaded it (issue #31) — TrackEditRequest /
  /// SplitRequest.lock_version mismatched.
  bool _isStaleVersionConflict(Object e) => e is ApiException && e.statusCode == 409;

  /// Tell the user their edit was rejected because the activity changed
  /// elsewhere, and close the editor: it's holding a now-stale copy, and
  /// reopening it (activity_panel.dart always re-fetches on open) is the only
  /// way to see the latest version before trying again. Mirrors
  /// ProjectNotifier's segment-conflict handling (_resyncOnConflict in
  /// project_segment_crud_mixin.dart).
  void _handleStaleVersionConflict(
    ScaffoldMessengerState messenger, NavigatorState navigator,
  ) {
    messenger.showSnackBar(const SnackBar(
      content: Text('This activity changed elsewhere. Close and reopen the '
          'editor to see the latest version, then try again.'),
    ));
    navigator.pop(false);
  }

  Future<void> _save() async {
    if (!_c.canSave || _saving) return;
    setState(() => _saving = true);
    final messenger = ScaffoldMessenger.of(context);
    final navigator = Navigator.of(context);
    try {
      await widget.notifier.saveActivityTrack(
          _activityId, _c.toSavePayload(), lockVersion: _lockVersion);
      if (!mounted) return;
      navigator.pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() => _saving = false);
      if (_isStaleVersionConflict(e)) {
        _handleStaleVersionConflict(messenger, navigator);
        return;
      }
      messenger.showSnackBar(SnackBar(content: Text('Save failed: $e')));
    }
  }

  /// Warn before a reset that also removes the pieces this activity was split
  /// into — restoring the full track destroys them and any edits they carry, so
  /// that has to be a choice rather than a surprise (issue #141).
  Future<bool> _confirmResetRemovesPieces(int pieces) async {
    // Worded to hold for a root (restoring the whole Strava track, undoing the
    // split outright) and for a piece that was itself split again (#143).
    final one = pieces == 1;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(_isLocal ? 'Reset track' : 'Reset to Strava'),
        content: Text(
          'This restores the track this activity had before it was split.\n\n'
          '${one ? 'The piece' : 'The $pieces pieces'} cut out of it will be '
          'removed from the trip, along with any track edits made to '
          '${one ? 'it' : 'them'}. This cannot be undone.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Reset'),
          ),
        ],
      ),
    );
    return ok == true;
  }

  Future<void> _reset() async {
    final pieces = _splitPiecesRemovedByReset;
    if (pieces > 0 && !await _confirmResetRemovesPieces(pieces)) return;
    if (!mounted) return;
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

  /// Note appended to the Split / Cut confirmations when the editor holds
  /// unsaved changes: those points are what gets cut (#127), so say so rather
  /// than let the user assume the stored track is being split.
  String get _pendingEditsNote => _c.isDirty
      ? '\n\nYour unsaved point edits will be applied as part of this.'
      : '';

  Future<void> _confirmSplit(int index) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Split activity'),
        content: Text(
          'Split into two activities at point ${index + 1}? '
          'The second half becomes a new local activity.$_pendingEditsNote',
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
      await widget.notifier.splitActivity(_activityId, index,
          payload: _c.toSavePayload(), lockVersion: _lockVersion);
      if (!mounted) return;
      navigator.pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() => _saving = false);
      if (_isStaleVersionConflict(e)) {
        _handleStaleVersionConflict(messenger, navigator);
        return;
      }
      messenger.showSnackBar(SnackBar(content: Text('Split failed: $e')));
    }
  }

  /// Cut the track at [index] and drop the shared boundary point from the new
  /// tail activity, leaving a gap for a transportation segment to bridge (#104).
  /// Pops with a request for the caller to open the Add Transportation dialog,
  /// pre-filled from this activity's (now-shorter) end point.
  Future<void> _confirmCutForTransport(int index) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Cut for transportation'),
        content: Text(
          'Cut the track at point ${index + 1}? The portion after this point '
          'becomes a new local activity, and you\'ll be prompted to add a '
          'transportation segment to bridge the gap.$_pendingEditsNote',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Cut'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => _saving = true);
    final messenger = ScaffoldMessenger.of(context);
    final navigator = Navigator.of(context);
    try {
      await widget.notifier.splitActivity(_activityId, index,
          dropBoundary: true,
          payload: _c.toSavePayload(),
          lockVersion: _lockVersion);
      if (!mounted) return;
      navigator.pop({'openSegmentFor': _activityId});
    } catch (e) {
      if (!mounted) return;
      setState(() => _saving = false);
      if (_isStaleVersionConflict(e)) {
        _handleStaleVersionConflict(messenger, navigator);
        return;
      }
      messenger.showSnackBar(SnackBar(content: Text('Cut failed: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final pts = _c.points;

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
              label: Text(_isLocal ? 'Reset track' : 'Reset to Strava'),
              style: TextButton.styleFrom(
                foregroundColor: theme.colorScheme.onSurfaceVariant,
              ),
            ),
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
      body: Column(
        children: [
          Expanded(
            child: TrackMapEditor(
              controller: _c,
              actionsForPoint: _actionsForPoint,
              pointMenuHint:
                  'Long-press or right-click a point to trim, split or delete',
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
