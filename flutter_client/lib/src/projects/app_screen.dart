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
    final notifier = context.watch<ProjectNotifier>();
    final title = notifier.projectName ?? widget.projectName;

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
                  child: ActivityPanel(
                    notifier: notifier,
                    mapController: _mapController,
                  ),
                ),
                Expanded(
                  child: Column(
                    children: [
                      Expanded(
                        child: MapPanel(
                          notifier: notifier,
                          mapController: _mapController,
                        ),
                      ),
                      SizedBox(
                        height: 160,
                        child: ElevationChart(activities: notifier.activities),
                      ),
                    ],
                  ),
                ),
              ],
            );
          } else {
            // ── Narrow layout: map fills screen + bottom sheet overlay ───
            return Stack(
              children: [
                MapPanel(
                  notifier: notifier,
                  mapController: _mapController,
                ),
                DraggableScrollableSheet(
                  initialChildSize: 0.35,
                  minChildSize: 0.12,
                  maxChildSize: 0.85,
                  builder: (context, scrollController) {
                    return Material(
                      elevation: 8,
                      borderRadius: const BorderRadius.vertical(
                          top: Radius.circular(16)),
                      child: ActivityPanel(
                        notifier: notifier,
                        mapController: _mapController,
                        scrollController: scrollController,
                        showElevationChart: true,
                      ),
                    );
                  },
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
  // Polyline + bounds cache — only rebuilt when geo reference changes.
  Map<String, dynamic>? _lastGeo;
  List<Polyline> _cachedPolylines = [];
  List<LatLng> _cachedAllPoints = [];
  late final NetworkTileProvider _tileProvider;

  @override
  void initState() {
    super.initState();
    _tileProvider = NetworkTileProvider();
  }

  List<Polyline> _buildPolylines(Map<String, dynamic> geo) {
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
      polylines.add(Polyline(
        points: points,
        color: isSegment
            ? const Color(0xFF888888)
            : const Color(0xFFF97316),
        strokeWidth: isSegment ? 2.0 : 3.0,
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
    // Reset fit flag when the project changes so new data gets fitted.
    if (oldWidget.notifier.projectName != widget.notifier.projectName) {
      _fittedBounds = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    final notifier = widget.notifier;

    if (notifier.isLoading) {
      return const Center(child: CircularProgressIndicator());
    }

    // Recompute polylines only when the geo reference changes.
    final geo = notifier.geo;
    if (!identical(geo, _lastGeo)) {
      _lastGeo = geo;
      _cachedPolylines = geo != null ? _buildPolylines(geo) : [];
      _cachedAllPoints = _allPoints(_cachedPolylines);
    }
    final polylines = _cachedPolylines;
    final allPoints = _cachedAllPoints;

    if (allPoints.isNotEmpty) {
      _fitBoundsOnce(allPoints);
    }

    return RepaintBoundary(
      child: FlutterMap(
        mapController: widget.mapController,
        options: const MapOptions(
          initialCenter: LatLng(0, 0),
          initialZoom: 2,
        ),
        children: [
          TileLayer(
            urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
            userAgentPackageName: 'com.viewtrip.client',
            tileProvider: _tileProvider,
          ),
          if (polylines.isNotEmpty)
            PolylineLayer(polylines: polylines),
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
    );
  }
}

// ── ActivityPanel ─────────────────────────────────────────────────────────────

class ActivityPanel extends StatefulWidget {
  final ProjectNotifier notifier;
  final MapController mapController;
  final ScrollController? scrollController;
  final bool showElevationChart;

  const ActivityPanel({
    super.key,
    required this.notifier,
    required this.mapController,
    this.scrollController,
    this.showElevationChart = false,
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
    final raw = activity['start_latlng'];
    if (raw is List && raw.length >= 2) {
      final lat = (raw[0] as num).toDouble();
      final lon = (raw[1] as num).toDouble();
      widget.mapController.move(LatLng(lat, lon), 13.0);
    }
  }

  @override
  Widget build(BuildContext context) {
    final notifier = widget.notifier;
    final theme = Theme.of(context);
    final activities = notifier.activities;
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
              Row(
                children: [
                  _StatChip(
                      label: '${(totalDistM / 1000).toStringAsFixed(1)} km'),
                  const SizedBox(width: 8),
                  _StatChip(label: _formatDuration(totalMovingSec)),
                  const SizedBox(width: 8),
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
                      return ListTile(
                        key: ValueKey('act_${item['activity_id']}'),
                        leading: Icon(
                          _iconForActivityType(type),
                          color: theme.colorScheme.primary,
                        ),
                        title:
                            Text(name, style: theme.textTheme.bodyMedium),
                        subtitle: Text(
                          '${(distM / 1000).toStringAsFixed(1)} km  •  ${_formatDuration(movingSec)}',
                          style: theme.textTheme.bodySmall,
                        ),
                        trailing: IconButton(
                          icon: const Icon(Icons.delete_outline, size: 18),
                          tooltip: 'Remove from project',
                          onPressed: () => notifier.removeItem(i),
                        ),
                        onTap: () => _flyToActivity(a),
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

        // ── Elevation chart (narrow layout only) ─────────────────────────────
        if (widget.showElevationChart)
          Padding(
            padding: const EdgeInsets.all(8),
            child: ElevationChart(activities: activities),
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

// ── ElevationChart ────────────────────────────────────────────────────────────

class ElevationChart extends StatefulWidget {
  final List<Map<String, dynamic>> activities;

  const ElevationChart({super.key, required this.activities});

  @override
  State<ElevationChart> createState() => _ElevationChartState();
}

class _ElevationChartState extends State<ElevationChart> {
  List<FlSpot> _spots = const [];
  double _minY = 0;
  double _maxY = 0;

  @override
  void initState() {
    super.initState();
    _compute(widget.activities);
  }

  @override
  void didUpdateWidget(ElevationChart oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.activities, widget.activities)) {
      _compute(widget.activities);
    }
  }

  static Widget _elevLeftTitle(double value, TitleMeta meta) =>
      Text('${value.toInt()} m', style: const TextStyle(fontSize: 9));

  static Widget _elevBottomTitle(double value, TitleMeta meta) =>
      Text('${value.toStringAsFixed(0)} km',
          style: const TextStyle(fontSize: 9));

  void _compute(List<Map<String, dynamic>> activities) {
    final spots = <FlSpot>[];
    double offsetKm = 0;
    for (final a in activities) {
      final profile = a['elevation_profile'];
      if (profile is! List || profile.isEmpty) continue;
      for (final point in profile) {
        if (point is! List || point.length < 2) continue;
        spots.add(FlSpot(
          (point[0] as num).toDouble() + offsetKm,
          (point[1] as num).toDouble(),
        ));
      }
      final last = profile.last;
      if (last is List && last.isNotEmpty) {
        offsetKm += (last[0] as num).toDouble();
      }
    }
    _spots = spots;
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

  @override
  Widget build(BuildContext context) {
    if (_spots.isEmpty) {
      return const SizedBox(
        height: 40,
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
