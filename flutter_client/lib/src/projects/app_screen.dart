/// Main app screen — map + activity panel for an open project.
library;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_map_cancellable_tile_provider/flutter_map_cancellable_tile_provider.dart';
import 'package:go_router/go_router.dart';
import 'package:latlong2/latlong.dart';
import 'package:provider/provider.dart';

import '../auth/auth_notifier.dart';
import 'project_notifier.dart';

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
                  child: MapPanel(
                    notifier: notifier,
                    mapController: _mapController,
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

    final geo = notifier.geo;
    final polylines = geo != null ? _buildPolylines(geo) : <Polyline>[];
    final allPoints = _allPoints(polylines);

    if (allPoints.isNotEmpty) {
      _fitBoundsOnce(allPoints);
    }

    return FlutterMap(
      mapController: widget.mapController,
      options: const MapOptions(
        initialCenter: LatLng(0, 0),
        initialZoom: 2,
      ),
      children: [
        TileLayer(
          urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
          userAgentPackageName: 'com.viewtrip.client',
          tileProvider: CancellableNetworkTileProvider(),
        ),
        if (polylines.isNotEmpty)
          PolylineLayer(polylines: polylines),
      ],
    );
  }
}

// ── ActivityPanel ─────────────────────────────────────────────────────────────

class ActivityPanel extends StatelessWidget {
  final ProjectNotifier notifier;
  final MapController mapController;
  final ScrollController? scrollController;

  const ActivityPanel({
    super.key,
    required this.notifier,
    required this.mapController,
    this.scrollController,
  });

  IconData _iconForType(String? type) {
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

  String _formatDuration(dynamic seconds) {
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
      mapController.move(LatLng(lat, lon), 13.0);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final activities = notifier.activities;

    // ── Aggregate stats ───────────────────────────────────────────────────────
    double totalDistM = 0;
    int totalMovingSec = 0;
    double totalElevGain = 0;
    for (final a in activities) {
      totalDistM += (a['distance'] as num? ?? 0).toDouble();
      totalMovingSec += (a['moving_time'] as num? ?? 0).toInt();
      totalElevGain += (a['total_elevation_gain'] as num? ?? 0).toDouble();
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // ── Header ────────────────────────────────────────────────────────────
        Container(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
          decoration: BoxDecoration(
            border: Border(
              bottom: BorderSide(
                color: theme.dividerColor,
              ),
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                notifier.projectName ?? '',
                style: theme.textTheme.titleMedium
                    ?.copyWith(fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 6),
              Row(
                children: [
                  _StatChip(
                      label:
                          '${(totalDistM / 1000).toStringAsFixed(1)} km'),
                  const SizedBox(width: 8),
                  _StatChip(label: _formatDuration(totalMovingSec)),
                  const SizedBox(width: 8),
                  _StatChip(
                      label:
                          '${totalElevGain.toStringAsFixed(0)} m elev'),
                ],
              ),
            ],
          ),
        ),

        // ── Activity list ─────────────────────────────────────────────────────
        Expanded(
          child: activities.isEmpty && !notifier.isLoading
              ? Center(
                  child: Text(
                    notifier.error != null
                        ? 'Error: ${notifier.error}'
                        : 'No activities',
                    style: theme.textTheme.bodySmall,
                  ),
                )
              : ListView.separated(
                  controller: scrollController,
                  itemCount: activities.length,
                  separatorBuilder: (_, __) =>
                      const Divider(height: 1, indent: 56),
                  itemBuilder: (context, i) {
                    final a = activities[i];
                    final type = a['type'] as String?;
                    final name =
                        a['name'] as String? ?? 'Activity ${i + 1}';
                    final distM =
                        (a['distance'] as num? ?? 0).toDouble();
                    final movingSec = a['moving_time'];
                    return ListTile(
                      leading: Icon(
                        _iconForType(type),
                        color: theme.colorScheme.primary,
                      ),
                      title: Text(name,
                          style: theme.textTheme.bodyMedium),
                      subtitle: Text(
                        '${(distM / 1000).toStringAsFixed(1)} km  •  ${_formatDuration(movingSec)}',
                        style: theme.textTheme.bodySmall,
                      ),
                      onTap: () => _flyToActivity(a),
                    );
                  },
                ),
        ),

        // ── Elevation chart ───────────────────────────────────────────────────
        Padding(
          padding: const EdgeInsets.all(8),
          child: ElevationChart(activities: activities),
        ),
      ],
    );
  }
}

// ── ElevationChart ────────────────────────────────────────────────────────────

class ElevationChart extends StatelessWidget {
  final List<Map<String, dynamic>> activities;

  const ElevationChart({super.key, required this.activities});

  @override
  Widget build(BuildContext context) {
    // Concatenate elevation profiles from all activities.
    // elevation_profile shape: list of [distance_km, elevation_m] pairs.
    final spots = <FlSpot>[];
    double offsetKm = 0;

    for (final a in activities) {
      final profile = a['elevation_profile'];
      if (profile is! List || profile.isEmpty) continue;

      for (final point in profile) {
        if (point is! List || point.length < 2) continue;
        final distKm = (point[0] as num).toDouble() + offsetKm;
        final elevM = (point[1] as num).toDouble();
        spots.add(FlSpot(distKm, elevM));
      }

      // Advance offset by the last distance in this activity's profile.
      final last = profile.last;
      if (last is List && last.isNotEmpty) {
        offsetKm += (last[0] as num).toDouble();
      }
    }

    if (spots.isEmpty) {
      return const SizedBox(
        height: 40,
        child: Center(child: Text('No elevation data')),
      );
    }

    final minY = spots.map((s) => s.y).reduce((a, b) => a < b ? a : b);
    final maxY = spots.map((s) => s.y).reduce((a, b) => a > b ? a : b);
    final yPad = ((maxY - minY) * 0.1).clamp(10.0, double.infinity);

    return SizedBox(
      height: 160,
      child: LineChart(
        LineChartData(
          minY: minY - yPad,
          maxY: maxY + yPad,
          gridData: const FlGridData(show: false),
          borderData: FlBorderData(show: false),
          titlesData: FlTitlesData(
            leftTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 40,
                getTitlesWidget: (value, meta) => Text(
                  '${value.toInt()} m',
                  style: const TextStyle(fontSize: 9),
                ),
              ),
            ),
            bottomTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 22,
                getTitlesWidget: (value, meta) => Text(
                  '${value.toStringAsFixed(0)} km',
                  style: const TextStyle(fontSize: 9),
                ),
              ),
            ),
            topTitles: const AxisTitles(
                sideTitles: SideTitles(showTitles: false)),
            rightTitles: const AxisTitles(
                sideTitles: SideTitles(showTitles: false)),
          ),
          lineBarsData: [
            LineChartBarData(
              spots: spots,
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

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(label, style: theme.textTheme.labelSmall),
    );
  }
}
