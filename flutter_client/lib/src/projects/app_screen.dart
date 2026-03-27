/// Main app screen — map + activity panel for an open project.
// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use
library;

// dart:html is intentional — ViewTripWeb targets Flutter Web only.
import 'dart:html' as html;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:go_router/go_router.dart';
import 'package:latlong2/latlong.dart';
import 'package:provider/provider.dart';

import '../api/client.dart';
import '../auth/auth_notifier.dart';
import '../map/polyline_decoder.dart';
import 'project_notifier.dart';
import 'segment_dialog.dart';

// ── AppScreen ─────────────────────────────────────────────────────────────────

class AppScreen extends StatefulWidget {
  final String projectName;

  const AppScreen({super.key, required this.projectName});

  @override
  State<AppScreen> createState() => _AppScreenState();
}

class _AppScreenState extends State<AppScreen> {
  final MapController _mapController = MapController();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<ProjectNotifier>().load(widget.projectName);
    });
  }

  @override
  void dispose() {
    _mapController.dispose();
    super.dispose();
  }

  Future<void> _logout() async {
    await context.read<AuthNotifier>().logout();
    if (mounted) context.go('/login');
  }

  Future<void> _exportGpx() async {
    final name = widget.projectName;
    try {
      final res = await api.getRaw(
        '/api/projects/${Uri.encodeComponent(name)}/export',
      );
      // Determine filename from Content-Disposition or fall back to project name
      String filename = '$name.gpx';
      final cd = res.headers['content-disposition'] ?? '';
      final match = RegExp(r'filename="([^"]+)"').firstMatch(cd);
      if (match != null) filename = match.group(1)!;

      // Trigger browser download via a temporary anchor element
      final blob = html.Blob([res.bodyBytes], 'application/gpx+xml');
      final url = html.Url.createObjectUrlFromBlob(blob);
      html.AnchorElement(href: url)
        ..setAttribute('download', filename)
        ..click();
      html.Url.revokeObjectUrl(url);
    } on ApiException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Export failed: ${e.body}')),
      );
    }
  }

  Future<void> _syncStrava() async {
    final name = widget.projectName;
    try {
      final result = await api.post(
        '/api/projects/${Uri.encodeComponent(name)}/strava/sync',
        {},
      ) as Map<String, dynamic>;
      if (!mounted) return;
      final added = result['added'] as int? ?? 0;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(added > 0
              ? 'Synced — added $added ${added == 1 ? 'activity' : 'activities'}'
              : 'Already up to date'),
        ),
      );
      if (added > 0) {
        // Reload the project to show the new activities
        context.read<ProjectNotifier>().load(name);
      }
    } on ApiException catch (e) {
      if (!mounted) return;
      final msg = e.statusCode == 400
          ? 'Connect Strava first (go to Projects)'
          : 'Sync failed: ${e.body}';
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
    }
  }

  @override
  Widget build(BuildContext context) {
    // Only rebuild AppScreen (AppBar + LayoutBuilder) when the title changes.
    // ActivityPanel and MapPanel subscribe to the notifier themselves via Consumer,
    // so they still react to every notifyListeners() without pulling the AppBar
    // through an unnecessary rebuild on every selectActivity() call.
    final title = context.select<ProjectNotifier, String>(
      (n) => n.projectName ?? widget.projectName,
    );

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/projects'),
        ),
        title: Text(title.isEmpty ? 'ViewTripWeb' : title),
        actions: [
          IconButton(
            icon: const Icon(Icons.download),
            tooltip: 'Export as GPX',
            onPressed: _exportGpx,
          ),
          IconButton(
            icon: const Icon(Icons.playlist_add),
            tooltip: 'Import activities from Strava',
            onPressed: () => context.push(
                '/strava-import?project=${Uri.encodeComponent(widget.projectName)}'),
          ),
          IconButton(
            icon: const Icon(Icons.sync),
            tooltip: 'Sync from Strava',
            onPressed: _syncStrava,
          ),
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: 'Logout',
            onPressed: _logout,
          ),
          const SizedBox(width: 4),
        ],
      ),
      body: LayoutBuilder(
        builder: (context, constraints) {
          if (constraints.maxWidth >= 720) {
            // ── Wide layout: side-by-side ────────────────────────────────
            return Row(
              children: [
                SizedBox(
                  width: 280,
                  child: Consumer<ProjectNotifier>(
                    builder: (_, n, __) => ActivityPanel(
                      notifier: n,
                      mapController: _mapController,
                    ),
                  ),
                ),
                Expanded(
                  child: Column(
                    children: [
                      Expanded(
                        child: Consumer<ProjectNotifier>(
                          builder: (_, n, __) => _Stage1MapPanel(
                            notifier: n,
                            mapController: _mapController,
                          ),
                        ),
                      ),
                      Selector<ProjectNotifier,
                          (List<Map<String, dynamic>>, Object?)>(
                        selector: (_, n) =>
                            (n.activities, n.selectedActivityId as Object?),
                        shouldRebuild: (a, b) =>
                            !identical(a.$1, b.$1) ||
                            a.$2?.toString() != b.$2?.toString(),
                        builder: (ctx, tuple, __) {
                          final n = ctx.read<ProjectNotifier>();
                          return ElevationChart(
                            activities: tuple.$1,
                            selectedActivityId: tuple.$2,
                            onCursorChanged: (pos) =>
                                n.elevationCursorNotifier.value = pos,
                            mapCursorNotifier: n.mapCursorDistNotifier,
                          );
                        },
                      ),
                    ],
                  ),
                ),
              ],
            );
          } else {
            // ── Narrow layout: stacked ───────────────────────────────────
            return Column(
              children: [
                Expanded(
                  child: Consumer<ProjectNotifier>(
                    builder: (_, n, __) => _Stage1MapPanel(
                      notifier: n,
                      mapController: _mapController,
                    ),
                  ),
                ),
                SizedBox(
                  height: constraints.maxHeight * 0.4,
                  child: Column(
                    children: [
                      Expanded(
                        child: Consumer<ProjectNotifier>(
                          builder: (_, n, __) => ActivityPanel(
                            notifier: n,
                            mapController: _mapController,
                          ),
                        ),
                      ),
                      Selector<ProjectNotifier,
                          (List<Map<String, dynamic>>, Object?)>(
                        selector: (_, n) =>
                            (n.activities, n.selectedActivityId as Object?),
                        shouldRebuild: (a, b) =>
                            !identical(a.$1, b.$1) ||
                            a.$2?.toString() != b.$2?.toString(),
                        builder: (ctx, tuple, __) {
                          final n = ctx.read<ProjectNotifier>();
                          return ElevationChart(
                            activities: tuple.$1,
                            selectedActivityId: tuple.$2,
                            onCursorChanged: (pos) =>
                                n.elevationCursorNotifier.value = pos,
                            mapCursorNotifier: n.mapCursorDistNotifier,
                          );
                        },
                      ),
                    ],
                  ),
                ),
              ],
            );
          }
        },
      ),
    );
  }
}

// ── MapPanel ──────────────────────────────────────────────────────────────────

class MapPanel extends StatefulWidget {
  final ProjectNotifier notifier;
  final MapController mapController;

  const MapPanel({
    super.key,
    required this.notifier,
    required this.mapController,
  });

  @override
  State<MapPanel> createState() => _MapPanelState();
}

class _MapPanelState extends State<MapPanel> {
  bool _fittedBounds = false;
  // Polyline + bounds cache — only rebuilt when geo or selection changes.
  Map<String, dynamic>? _lastGeo;
  dynamic _lastSelectedId = _sentinel;
  List<Polyline> _cachedPolylines = [];
  List<LatLng> _cachedAllPoints = [];
  late final NetworkTileProvider _tileProvider;

  static const _sentinel = Object(); // distinct from null

  @override
  void initState() {
    super.initState();
    _tileProvider = NetworkTileProvider();
  }

  List<Polyline> _buildPolylines(Map<String, dynamic> geo, dynamic selectedId) {
    final features = geo['features'];
    if (features is! List) return [];

    final polylines = <Polyline>[];
    for (final feature in features) {
      if (feature is! Map) continue;
      final props = feature['properties'] as Map? ?? {};
      final geometry = feature['geometry'] as Map? ?? {};
      final coords = geometry['coordinates'];
      if (coords is! List) continue;

      final points = <LatLng>[];
      for (final c in coords) {
        if (c is List && c.length >= 2) {
          final lon = (c[0] as num).toDouble();
          final lat = (c[1] as num).toDouble();
          points.add(LatLng(lat, lon));
        }
      }
      if (points.isEmpty) continue;

      final isSegment = props['type'] == 'segment';
      final activityId = props['activity_id'];
      final isSelected = selectedId != null &&
          activityId?.toString() == selectedId.toString();
      final hasSelection = selectedId != null;

      polylines.add(Polyline(
        points: points,
        color: isSegment
            ? const Color(0xFF888888)
            : isSelected
                ? const Color(0xFFEF4444)              // red — selected
                : hasSelection
                    ? const Color(0x60F97316)          // dimmed — others
                    : const Color(0xFFF97316),         // full orange — no selection
        strokeWidth: isSegment ? 2.0 : isSelected ? 5.0 : 2.5,
      ));
    }
    return polylines;
  }

  List<LatLng> _allPoints(List<Polyline> polylines) {
    return polylines.expand((p) => p.points).toList();
  }

  void _fitBoundsOnce(List<LatLng> points) {
    if (_fittedBounds || points.isEmpty) return;
    _fittedBounds = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      double minLat = points.first.latitude;
      double maxLat = points.first.latitude;
      double minLon = points.first.longitude;
      double maxLon = points.first.longitude;
      for (final p in points) {
        if (p.latitude < minLat) minLat = p.latitude;
        if (p.latitude > maxLat) maxLat = p.latitude;
        if (p.longitude < minLon) minLon = p.longitude;
        if (p.longitude > maxLon) maxLon = p.longitude;
      }
      widget.mapController.fitCamera(
        CameraFit.bounds(
          bounds: LatLngBounds(
            LatLng(minLat, minLon),
            LatLng(maxLat, maxLon),
          ),
          padding: const EdgeInsets.all(32),
        ),
      );
    });
  }

  @override
  void didUpdateWidget(MapPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    // Reset fit flag when a different notifier instance is passed (new project).
    if (oldWidget.notifier != widget.notifier) {
      _fittedBounds = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    final notifier = widget.notifier;

    // Recompute polylines only when geo or selection changes.
    final geo = notifier.geo;
    final selectedId = notifier.selectedActivityId;
    if (!identical(geo, _lastGeo) || selectedId != _lastSelectedId) {
      _lastGeo = geo;
      _lastSelectedId = selectedId;
      _cachedPolylines = geo != null ? _buildPolylines(geo, selectedId) : [];
      _cachedAllPoints = _allPoints(_cachedPolylines);
    }
    final polylines = _cachedPolylines;
    final allPoints = _cachedAllPoints;

    if (allPoints.isNotEmpty && !notifier.isLoading) {
      _fitBoundsOnce(allPoints);
    }

    // FlutterMap stays mounted throughout loading so the MapController stays
    // attached and tiles don't get torn down on every load.  A spinner is
    // overlaid on top while data is in flight.
    return Stack(
      children: [
        FlutterMap(
          mapController: widget.mapController,
          options: const MapOptions(
            initialCenter: LatLng(0, 0),
            initialZoom: 2,
          ),
          children: [
            TileLayer(
              urlTemplate:
                  'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
              userAgentPackageName: 'com.viewtrip.client',
              tileProvider: _tileProvider,
              maxNativeZoom: 19,
            ),
            if (polylines.isNotEmpty)
              PolylineLayer(
                polylines: polylines,
                // Reduce GPU path vertices at low zoom — detail preserved when zoomed in.
                simplificationTolerance: 0.5,
              ),
            // Preview arc uses ValueListenableBuilder so only this layer rebuilds
            // when the segment dialog updates coordinates — not the whole map.
            ValueListenableBuilder<List<LatLng>?>(
              valueListenable: notifier.previewArcNotifier,
              builder: (_, arc, __) {
                if (arc == null) return const SizedBox.shrink();
                return PolylineLayer(
                  polylines: [
                    Polyline(
                      points: arc,
                      color: const Color(0xCC6366F1),
                      strokeWidth: 2.5,
                    ),
                  ],
                );
              },
            ),
          ],
        ),
        if (notifier.isLoading)
          const Center(child: CircularProgressIndicator()),
      ],
    );
  }
}

// ── ActivityPanel ─────────────────────────────────────────────────────────────

class ActivityPanel extends StatefulWidget {
  final ProjectNotifier notifier;
  final MapController? mapController;
  final ScrollController? scrollController;
  const ActivityPanel({
    super.key,
    required this.notifier,
    this.mapController,
    this.scrollController,
  });

  @override
  State<ActivityPanel> createState() => _ActivityPanelState();
}

class _ActivityPanelState extends State<ActivityPanel> {
  // activityById cache — rebuilt only when the activities list reference changes.
  List<Map<String, dynamic>>? _lastActivities;
  Map<dynamic, Map<String, dynamic>> _activityById = {};

  // Theme-derived styles cached in didChangeDependencies so copyWith is not
  // called on every build().
  TextStyle? _segmentTitleStyle;
  TextStyle? _projectTitleStyle;

  void _refreshActivityById(List<Map<String, dynamic>> activities) {
    if (identical(activities, _lastActivities)) return;
    _lastActivities = activities;
    _activityById = {for (final a in activities) a['id']: a};
  }

  @override
  void initState() {
    super.initState();
    _refreshActivityById(widget.notifier.activities);
  }

  @override
  void didUpdateWidget(ActivityPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    _refreshActivityById(widget.notifier.activities);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final theme = Theme.of(context);
    _segmentTitleStyle =
        theme.textTheme.bodyMedium?.copyWith(fontStyle: FontStyle.italic);
    _projectTitleStyle =
        theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold);
  }

  static IconData _iconForActivityType(String? type) {
    switch (type?.toLowerCase()) {
      case 'run':
        return Icons.directions_run;
      case 'ride':
        return Icons.directions_bike;
      case 'hike':
        return Icons.hiking;
      default:
        return Icons.map;
    }
  }

  static IconData _iconForSegmentType(String? type) {
    switch (type?.toLowerCase()) {
      case 'flight':
        return Icons.flight;
      case 'train':
        return Icons.train;
      case 'bus':
        return Icons.directions_bus;
      case 'boat':
        return Icons.directions_boat;
      default:
        return Icons.route;
    }
  }

  static String _formatDuration(dynamic seconds) {
    if (seconds == null) return '--';
    final total = (seconds as num).toInt();
    final h = total ~/ 3600;
    final m = (total % 3600) ~/ 60;
    if (h > 0) return '${h}h ${m}m';
    return '${m}m';
  }

  void _flyToActivity(Map<String, dynamic> activity) {
    // Highlight the tapped activity on the map (toggle if already selected).
    widget.notifier.selectActivity(activity['id']);
    final raw = activity['start_latlng'];
    if (raw is! List || raw.length < 2) return;
    final target = LatLng((raw[0] as num).toDouble(), (raw[1] as num).toDouble());
    final mc = widget.mapController;
    if (mc == null) return;
    if (!mc.camera.visibleBounds.contains(target)) {
      mc.move(target, mc.camera.zoom.clamp(10.0, 15.0));
    }
  }

  @override
  Widget build(BuildContext context) {
    final notifier = widget.notifier;
    final theme = Theme.of(context);
    final items = notifier.items;

    final activityById = _activityById;

    // Styles are pre-computed in didChangeDependencies() — no copyWith in build().

    // Aggregate stats are pre-computed in ProjectNotifier._updateStats().
    final totalDistM    = notifier.totalDistanceM;
    final totalMovingSec = notifier.totalMovingSeconds;
    final totalElevGain = notifier.totalElevationGainM;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // ── Header ────────────────────────────────────────────────────────────
        Container(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
          decoration: BoxDecoration(
            border: Border(
              bottom: BorderSide(color: theme.dividerColor),
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                notifier.projectName ?? '',
                style: _projectTitleStyle,
              ),
              const SizedBox(height: 6),
              Wrap(
                spacing: 8,
                runSpacing: 4,
                children: [
                  _StatChip(
                      label: '${(totalDistM / 1000).toStringAsFixed(1)} km'),
                  _StatChip(label: _formatDuration(totalMovingSec)),
                  _StatChip(
                      label: '${totalElevGain.toStringAsFixed(0)} m elev'),
                ],
              ),
            ],
          ),
        ),

        // ── Items list (activities + segments, reorderable) ───────────────────
        Expanded(
          child: items.isEmpty && !notifier.isLoading
              ? Center(
                  child: Text(
                    notifier.error != null
                        ? 'Error: ${notifier.error}'
                        : 'No activities — use sync or import',
                    style: theme.textTheme.bodySmall,
                    textAlign: TextAlign.center,
                  ),
                )
              : ReorderableListView.builder(
                  scrollController: widget.scrollController,
                  onReorder: (oldIndex, newIndex) {
                    // ReorderableListView passes newIndex after removal,
                    // but our backend uses the original "before" semantics.
                    final to = newIndex > oldIndex ? newIndex - 1 : newIndex;
                    notifier.reorderItems(oldIndex, to);
                  },
                  itemCount: items.length,
                  itemBuilder: (context, i) {
                    final item = items[i];
                    final isActivity = item['item_type'] == 'activity';

                    if (isActivity) {
                      final a = activityById[item['activity_id']];
                      if (a == null) {
                        return ListTile(
                          key: ValueKey('act_${item['activity_id']}'),
                          leading: const Icon(Icons.help_outline),
                          title: const Text('Unknown activity'),
                          trailing: IconButton(
                            icon: const Icon(Icons.delete_outline, size: 18),
                            onPressed: () => notifier.removeItem(i),
                          ),
                        );
                      }
                      final type = a['type'] as String?;
                      final name = a['name'] as String? ?? 'Activity';
                      final distM = (a['distance'] as num? ?? 0).toDouble();
                      final movingSec = a['moving_time'];
                      final activityId = item['activity_id'];
                      return Selector<ProjectNotifier, bool>(
                        key: ValueKey('act_$activityId'),
                        selector: (_, n) =>
                            activityId?.toString() ==
                            n.selectedActivityId?.toString(),
                        builder: (_, isSelected, __) => ListTile(
                          tileColor: isSelected
                              ? theme.colorScheme.primaryContainer
                                  .withValues(alpha: 0.45)
                              : null,
                          leading: Icon(
                            _iconForActivityType(type),
                            color: isSelected
                                ? theme.colorScheme.primary
                                : theme.colorScheme.primary
                                    .withValues(alpha: 0.7),
                          ),
                          title:
                              Text(name, style: theme.textTheme.bodyMedium),
                          subtitle: Text(
                            '${(distM / 1000).toStringAsFixed(1)} km  •  ${_formatDuration(movingSec)}',
                            style: theme.textTheme.bodySmall,
                          ),
                          trailing: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              IconButton(
                                icon: const Icon(Icons.refresh, size: 18),
                                tooltip: 'Re-fetch from Strava',
                                onPressed: activityId == null
                                    ? null
                                    : () => notifier.refreshActivity(
                                          activityId as int,
                                        ),
                              ),
                              IconButton(
                                icon: const Icon(Icons.delete_outline, size: 18),
                                tooltip: 'Remove from project',
                                onPressed: () => notifier.removeItem(i),
                              ),
                            ],
                          ),
                          onTap: () => _flyToActivity(a),
                        ),
                      );
                    } else {
                      // Segment item
                      final seg = item['segment'] as Map<String, dynamic>? ?? {};
                      final segId = seg['id'] as String? ?? '';
                      final segType = seg['segment_type'] as String?;
                      final label = seg['label'] as String? ?? segType ?? 'Segment';
                      return ListTile(
                        key: ValueKey('seg_$segId'),
                        leading: Icon(
                          _iconForSegmentType(segType),
                          color: theme.colorScheme.secondary,
                        ),
                        title: Text(label, style: _segmentTitleStyle),
                        subtitle: Text(segType ?? '',
                            style: theme.textTheme.bodySmall),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            IconButton(
                              icon: const Icon(Icons.edit_outlined, size: 18),
                              tooltip: 'Edit segment',
                              onPressed: () => _showSegmentDialog(
                                context,
                                notifier,
                                editSegment: seg,
                                insertAfterIndex: null,
                              ),
                            ),
                            IconButton(
                              icon: const Icon(Icons.delete_outline, size: 18),
                              tooltip: 'Delete segment',
                              onPressed: () =>
                                  notifier.deleteSegment(segId),
                            ),
                          ],
                        ),
                      );
                    }
                  },
                ),
        ),

        // ── "Add segment" button between items ────────────────────────────────
        if (items.isNotEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
            child: OutlinedButton.icon(
              icon: const Icon(Icons.add, size: 16),
              label: const Text('Add connecting segment'),
              onPressed: () => _showSegmentDialog(
                context,
                notifier,
                insertAfterIndex: items.length - 1,
              ),
            ),
          ),

      ],
    );
  }
}

Future<void> _showSegmentDialog(
  BuildContext context,
  ProjectNotifier notifier, {
  Map<String, dynamic>? editSegment,
  int? insertAfterIndex,
}) async {
  await showDialog<void>(
    context: context,
    builder: (ctx) => SegmentDialog(
      notifier: notifier,
      editSegment: editSegment,
      insertAfterIndex: insertAfterIndex,
    ),
  );
}

// ── _Stage1MapPanel — bare TileLayer, no controller, no polylines ─────────────

class _Stage1MapPanel extends StatefulWidget {
  final ProjectNotifier notifier;
  final MapController mapController;

  const _Stage1MapPanel({required this.notifier, required this.mapController});

  @override
  State<_Stage1MapPanel> createState() => _Stage1MapPanelState();
}

class _Stage1MapPanelState extends State<_Stage1MapPanel> {
  late final NetworkTileProvider _tileProvider;
  bool _fittedBounds = false;

  // Polyline cache — only rebuilt when geo or selection changes.
  Map<String, dynamic>? _lastGeo;
  dynamic _lastSelectedId = _sentinel;
  List<Polyline> _cachedPolylines = [];

  static const _sentinel = Object();

  @override
  void initState() {
    super.initState();
    _tileProvider = NetworkTileProvider();
  }

  @override
  void dispose() {
    super.dispose();
  }

  void _fitBoundsOnce(List<LatLng> points) {
    if (_fittedBounds || points.isEmpty) return;
    _fittedBounds = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      double minLat = points.first.latitude, maxLat = points.first.latitude;
      double minLon = points.first.longitude, maxLon = points.first.longitude;
      for (final p in points) {
        if (p.latitude < minLat) minLat = p.latitude;
        if (p.latitude > maxLat) maxLat = p.latitude;
        if (p.longitude < minLon) minLon = p.longitude;
        if (p.longitude > maxLon) maxLon = p.longitude;
      }
      widget.mapController.fitCamera(
        CameraFit.bounds(
          bounds: LatLngBounds(LatLng(minLat, minLon), LatLng(maxLat, maxLon)),
          padding: const EdgeInsets.all(32),
        ),
      );
    });
  }

  void _onMapTap(LatLng latlng) {
    final track = widget.notifier.fullTrack;
    if (track.isEmpty) return;
    int nearest = 0;
    double minDist = double.infinity;
    for (int i = 0; i < track.length; i++) {
      final dLat = track[i].$2.latitude  - latlng.latitude;
      final dLon = track[i].$2.longitude - latlng.longitude;
      final d = dLat * dLat + dLon * dLon;
      if (d < minDist) { minDist = d; nearest = i; }
    }
    widget.notifier.elevationCursorNotifier.value = track[nearest].$2;
    widget.notifier.mapCursorDistNotifier.value   = track[nearest].$1;
  }

  List<Polyline> _buildPolylines(Map<String, dynamic> geo, dynamic selectedId) {
    final features = geo['features'];
    if (features is! List) return [];
    final polylines = <Polyline>[];
    final hasSelection = selectedId != null;
    for (final feature in features) {
      if (feature is! Map) continue;
      final props = feature['properties'] as Map? ?? {};
      final geometry = feature['geometry'] as Map? ?? {};
      final coords = geometry['coordinates'];
      if (coords is! List) continue;
      final points = <LatLng>[];
      for (final c in coords) {
        if (c is List && c.length >= 2) {
          points.add(LatLng((c[1] as num).toDouble(), (c[0] as num).toDouble()));
        }
      }
      if (points.isEmpty) continue;
      final isSegment = props['type'] == 'segment';
      final isSelected = hasSelection &&
          props['activity_id']?.toString() == selectedId.toString();
      polylines.add(Polyline(
        points: points,
        color: isSegment
            ? const Color(0xFF888888)
            : isSelected
                ? const Color(0xFFEF4444)
                : hasSelection
                    ? const Color(0x60F97316)
                    : const Color(0xFFF97316),
        strokeWidth: isSegment ? 2.0 : isSelected ? 5.0 : 2.5,
      ));
    }
    return polylines;
  }

  @override
  Widget build(BuildContext context) {
    final notifier = widget.notifier;
    final geo = notifier.geo;
    final selectedId = notifier.selectedActivityId;
    if (!identical(geo, _lastGeo) || selectedId != _lastSelectedId) {
      if (!identical(geo, _lastGeo)) _fittedBounds = false; // refit on new geo
      _lastGeo = geo;
      _lastSelectedId = selectedId;
      _cachedPolylines = geo != null ? _buildPolylines(geo, selectedId) : [];
    }

    if (!notifier.isLoading) {
      _fitBoundsOnce(_cachedPolylines.expand((p) => p.points).toList());
    }

    return Stack(
      children: [
        FlutterMap(
          mapController: widget.mapController,
          options: MapOptions(
            initialCenter: const LatLng(48.0, 10.0),
            initialZoom: 4,
            interactionOptions: const InteractionOptions(
              flags: InteractiveFlag.all & ~InteractiveFlag.rotate,
            ),
            onTap: (_, latlng) => _onMapTap(latlng),
          ),
          children: [
            TileLayer(
              urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
              userAgentPackageName: 'com.viewtrip.client',
              tileProvider: _tileProvider,
              maxNativeZoom: 19,
            ),
            if (_cachedPolylines.isNotEmpty)
              PolylineLayer(
                polylines: _cachedPolylines,
                simplificationTolerance: 0.5,
              ),
            ValueListenableBuilder<List<LatLng>?>(
              valueListenable: notifier.previewArcNotifier,
              builder: (_, arc, __) {
                if (arc == null) return const SizedBox.shrink();
                return PolylineLayer(
                  polylines: [
                    Polyline(
                      points: arc,
                      color: const Color(0xCC6366F1),
                      strokeWidth: 2.5,
                    ),
                  ],
                );
              },
            ),
            ValueListenableBuilder<LatLng?>(
              valueListenable: notifier.elevationCursorNotifier,
              builder: (_, cursor, __) {
                if (cursor == null) return const SizedBox.shrink();
                return MarkerLayer(
                  markers: [
                    Marker(
                      point: cursor,
                      width: 16,
                      height: 16,
                      child: Container(
                        decoration: BoxDecoration(
                          color: const Color(0xFFF97316),
                          shape: BoxShape.circle,
                          border: Border.all(color: Colors.white, width: 2),
                        ),
                      ),
                    ),
                  ],
                );
              },
            ),
          ],
        ),
        if (notifier.isLoading)
          const Center(child: CircularProgressIndicator()),
      ],
    );
  }
}

// ── ElevationChart ────────────────────────────────────────────────────────────

class ElevationChart extends StatefulWidget {
  final List<Map<String, dynamic>> activities;
  final dynamic selectedActivityId;

  /// Called with the map position under the chart cursor, or null when the
  /// user lifts / exits. Drives the elevation cursor marker on the map.
  final void Function(LatLng?)? onCursorChanged;

  /// Driven by map taps — shows a vertical line at this distance (km).
  final ValueNotifier<double?>? mapCursorNotifier;

  const ElevationChart({
    super.key,
    required this.activities,
    this.selectedActivityId,
    this.onCursorChanged,
    this.mapCursorNotifier,
  });

  @override
  State<ElevationChart> createState() => _ElevationChartState();
}

class _ElevationChartState extends State<ElevationChart> {
  List<FlSpot> _spots = const [];
  double _minY = 0;
  double _maxY = 0;

  /// Distance-indexed track: (cumulativeDistKm, LatLng) pairs, parallel to
  /// the elevation profile. Built from each activity's summary_polyline.
  List<(double, LatLng)> _track = const [];

  @override
  void initState() {
    super.initState();
    _compute(widget.activities, widget.selectedActivityId);
    widget.mapCursorNotifier?.addListener(_onMapCursor);
  }

  @override
  void didUpdateWidget(ElevationChart oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.mapCursorNotifier != widget.mapCursorNotifier) {
      oldWidget.mapCursorNotifier?.removeListener(_onMapCursor);
      widget.mapCursorNotifier?.addListener(_onMapCursor);
    }
    if (!identical(oldWidget.activities, widget.activities) ||
        oldWidget.selectedActivityId?.toString() !=
            widget.selectedActivityId?.toString()) {
      _compute(widget.activities, widget.selectedActivityId);
    }
  }

  @override
  void dispose() {
    widget.mapCursorNotifier?.removeListener(_onMapCursor);
    super.dispose();
  }

  void _onMapCursor() => setState(() {});

  static Widget _elevLeftTitle(double value, TitleMeta meta) =>
      Text('${value.toInt()} m', style: const TextStyle(fontSize: 9));

  static Widget _elevBottomTitle(double value, TitleMeta meta) =>
      Text('${value.toStringAsFixed(0)} km',
          style: const TextStyle(fontSize: 9));

  void _compute(List<Map<String, dynamic>> activities, dynamic selectedId) {
    final source = selectedId == null
        ? activities
        : activities
            .where((a) => a['id']?.toString() == selectedId.toString())
            .toList();

    final spots = <FlSpot>[];
    final track = <(double, LatLng)>[];
    double offsetKm = 0;
    for (final a in source) {
      final profile = a['elevation_profile'];
      if (profile is! List || profile.isEmpty) continue;

      // Decode this activity's polyline so we can map distance → lat/lon.
      List<LatLng>? decoded;
      final encoded = (a['map'] as Map?)?['summary_polyline'] as String?;
      if (encoded != null && encoded.isNotEmpty) {
        decoded = decodePolyline(encoded);
      }

      for (int i = 0; i < profile.length; i++) {
        final point = profile[i];
        if (point is! List || point.length < 2) continue;
        final distKm = (point[0] as num).toDouble() + offsetKm;
        spots.add(FlSpot(distKm, (point[1] as num).toDouble()));
        if (decoded != null && i < decoded.length) {
          track.add((distKm, decoded[i]));
        }
      }

      final last = profile.last;
      if (last is List && last.isNotEmpty) {
        offsetKm += (last[0] as num).toDouble();
      }
    }
    _spots = spots;
    _track = track;
    if (spots.isNotEmpty) {
      double minY = spots.first.y, maxY = spots.first.y;
      for (final s in spots) {
        if (s.y < minY) minY = s.y;
        if (s.y > maxY) maxY = s.y;
      }
      _minY = minY;
      _maxY = maxY;
    }
  }

  void _onTouch(FlTouchEvent event, LineTouchResponse? response) {
    // Clear the map cursor only when the pointer fully leaves the chart
    // (desktop mouse exit). On mobile, pan-end must NOT clear — a short tap
    // is delivered as FlPanStart→FlPanEnd, so clearing on FlPanEndEvent would
    // erase the marker before the user even sees it.
    if (event is FlPointerExitEvent) {
      widget.onCursorChanged?.call(null);
      return;
    }
    final spots = response?.lineBarSpots;
    if (spots == null || spots.isEmpty) return;
    final pos = latLonAtDistance(_track, spots.first.x);
    if (pos != null) widget.onCursorChanged?.call(pos);
  }

  @override
  Widget build(BuildContext context) {
    if (_spots.isEmpty) {
      return const SizedBox(
        height: 160,
        child: Center(child: Text('No elevation data')),
      );
    }

    final yPad = ((_maxY - _minY) * 0.1).clamp(10.0, double.infinity);

    return SizedBox(
      height: 160,
      child: LineChart(
        LineChartData(
          minY: _minY - yPad,
          maxY: _maxY + yPad,
          gridData: const FlGridData(show: false),
          borderData: FlBorderData(show: false),
          titlesData: FlTitlesData(
            leftTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 40,
                getTitlesWidget: _elevLeftTitle,
              ),
            ),
            bottomTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 22,
                getTitlesWidget: _elevBottomTitle,
              ),
            ),
            topTitles: const AxisTitles(
                sideTitles: SideTitles(showTitles: false)),
            rightTitles: const AxisTitles(
                sideTitles: SideTitles(showTitles: false)),
          ),
          extraLinesData: () {
            final d = widget.mapCursorNotifier?.value;
            if (d == null) return null;
            return ExtraLinesData(verticalLines: [
              VerticalLine(
                x: d,
                color: const Color(0xFFF97316),
                strokeWidth: 1.5,
                dashArray: [4, 4],
              ),
            ]);
          }(),
          lineTouchData: LineTouchData(
            touchCallback: _onTouch,
            handleBuiltInTouches: true,
          ),
          lineBarsData: [
            LineChartBarData(
              spots: _spots,
              isCurved: true,
              color: const Color(0xFFF97316),
              barWidth: 2,
              dotData: const FlDotData(show: false),
              belowBarData: BarAreaData(
                show: true,
                color: const Color(0xFFF97316).withValues(alpha: 0.2),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ── _StatChip ─────────────────────────────────────────────────────────────────

class _StatChip extends StatelessWidget {
  final String label;

  const _StatChip({required this.label});

  static const _borderRadius = BorderRadius.all(Radius.circular(12));
  static const _padding = EdgeInsets.symmetric(horizontal: 8, vertical: 3);

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: _padding,
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest,
        borderRadius: _borderRadius,
      ),
      child: Text(label, style: theme.textTheme.labelSmall),
    );
  }
}
