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

import 'package:flutter/services.dart';

import '../api/client.dart';
import '../auth/auth_notifier.dart';
import '../map/polyline_decoder.dart';
import 'project_notifier.dart';
import 'project_settings_dialog.dart';
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
  bool _panelOpen = false;
  void _togglePanel() => setState(() => _panelOpen = !_panelOpen);

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


  Future<void> _showRenameDialog(BuildContext context) async {
    final notifier = context.read<ProjectNotifier>();
    final ctrl = TextEditingController(text: notifier.projectName ?? '');
    await showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Rename project'),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          decoration: const InputDecoration(
            labelText: 'Project name',
            border: OutlineInputBorder(),
          ),
          onSubmitted: (_) => Navigator.of(ctx).pop(),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('Rename'),
          ),
        ],
      ),
    );
    final newName = ctrl.text.trim();
    ctrl.dispose();
    if (newName.isEmpty || newName == notifier.projectName) return;
    final result = await notifier.renameProject(newName);
    if (!context.mounted) return;
    if (result != null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Renamed to "$result"')),
      );
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(notifier.error ?? 'Rename failed')),
      );
    }
  }

  Future<void> _showShareDialog() async {
    final name = widget.projectName;
    // Capture before any await so the messenger is available inside the dialog.
    final messenger = ScaffoldMessenger.of(context);
    try {
      final result = await api.post(
        '/api/projects/${Uri.encodeComponent(name)}/share',
        {},
      ) as Map<String, dynamic>;
      final token = result['share_token'] as String? ?? '';
      if (!mounted) return;

      final shareUrl = '${Uri.base.origin}/share/$token';

      await showDialog<void>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Share project'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text('Anyone with this link can view the project read-only:'),
              const SizedBox(height: 12),
              SelectableText(shareUrl),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () async {
                await Clipboard.setData(ClipboardData(text: shareUrl));
                messenger.showSnackBar(
                  const SnackBar(content: Text('Link copied to clipboard')),
                );
              },
              child: const Text('Copy link'),
            ),
            TextButton(
              onPressed: () async {
                Navigator.of(ctx).pop();
                await api.delete(
                    '/api/projects/${Uri.encodeComponent(name)}/share');
                messenger.showSnackBar(
                  const SnackBar(content: Text('Share link revoked')),
                );
              },
              child: const Text('Revoke'),
            ),
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(),
              child: const Text('Close'),
            ),
          ],
        ),
      );
    } on ApiException catch (e) {
      if (!mounted) return;
      messenger.showSnackBar(
        SnackBar(content: Text('Share failed: ${e.body}')),
      );
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
        title: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Flexible(
              child: Text(
                title.isEmpty ? 'ViewTripWeb' : title,
                overflow: TextOverflow.ellipsis,
              ),
            ),
            IconButton(
              icon: const Icon(Icons.edit_outlined, size: 18),
              tooltip: 'Rename project',
              visualDensity: VisualDensity.compact,
              onPressed: () => _showRenameDialog(context),
            ),
          ],
        ),
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
            icon: const Icon(Icons.share_outlined),
            tooltip: 'Share project',
            onPressed: _showShareDialog,
          ),
          IconButton(
            icon: const Icon(Icons.bar_chart_outlined),
            tooltip: 'Statistics',
            onPressed: () => context.push(
                '/stats?project=${Uri.encodeComponent(widget.projectName)}'),
          ),
          IconButton(
            icon: const Icon(Icons.tune),
            tooltip: 'Project settings',
            onPressed: () => showDialog<void>(
              context: context,
              useRootNavigator: true,
              builder: (_) => ProjectSettingsDialog(
                notifier: context.read<ProjectNotifier>(),
              ),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.settings_outlined),
            tooltip: 'Settings',
            onPressed: () => context.push('/settings'),
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
          // Auto-close the panel when switching to wide layout.
          if (constraints.maxWidth >= 720 && _panelOpen) {
            WidgetsBinding.instance.addPostFrameCallback((_) {
              if (mounted && _panelOpen) setState(() => _panelOpen = false);
            });
          }
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
                          (List<Map<String, dynamic>>, Object?, String?)>(
                        selector: (_, n) => (
                          n.activities,
                          n.selectedActivityId as Object?,
                          n.selectedDay,
                        ),
                        shouldRebuild: (a, b) =>
                            !identical(a.$1, b.$1) ||
                            a.$2?.toString() != b.$2?.toString() ||
                            a.$3 != b.$3,
                        builder: (ctx, tuple, __) {
                          final n = ctx.read<ProjectNotifier>();
                          final allActivities = tuple.$1;
                          final selActId = tuple.$2;
                          final selDay = tuple.$3;
                          final activities = selDay != null
                              ? allActivities.where((a) =>
                                  (a['start_date_local'] as String? ?? '')
                                      .split('T').first == selDay).toList()
                              : allActivities;
                          return ElevationChart(
                            activities: activities,
                            selectedActivityId: selActId,
                            onCursorChanged: (pos) =>
                                n.elevationCursorNotifier.value = pos,
                            mapCursorNotifier: n.mapCursorDistNotifier,
                            track: selActId != null
                                ? n.perActivityTracks[selActId.toString()] ?? n.fullTrack
                                : n.fullTrack,
                          );
                        },
                      ),
                    ],
                  ),
                ),
              ],
            );
          } else {
            // ── Narrow layout: full-screen map + slide-in activity panel ──
            final mapHeight = constraints.maxHeight - 160;
            return Stack(
              children: [
                // Base: full-height map + pinned elevation chart
                Column(
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
                        (List<Map<String, dynamic>>, Object?, String?)>(
                      selector: (_, n) => (
                        n.activities,
                        n.selectedActivityId as Object?,
                        n.selectedDay,
                      ),
                      shouldRebuild: (a, b) =>
                          !identical(a.$1, b.$1) ||
                          a.$2?.toString() != b.$2?.toString() ||
                          a.$3 != b.$3,
                      builder: (ctx, tuple, __) {
                        final n = ctx.read<ProjectNotifier>();
                        final allActivities = tuple.$1;
                        final selActId = tuple.$2;
                        final selDay = tuple.$3;
                        final activities = selDay != null
                            ? allActivities.where((a) =>
                                (a['start_date_local'] as String? ?? '')
                                    .split('T').first == selDay).toList()
                            : allActivities;
                        return ElevationChart(
                          activities: activities,
                          selectedActivityId: selActId,
                          onCursorChanged: (pos) =>
                              n.elevationCursorNotifier.value = pos,
                          mapCursorNotifier: n.mapCursorDistNotifier,
                          track: selActId != null
                              ? n.perActivityTracks[selActId.toString()] ?? n.fullTrack
                              : n.fullTrack,
                        );
                      },
                    ),
                  ],
                ),

                // Overlay: activity panel slides in from the left
                AnimatedSlide(
                  offset: _panelOpen ? Offset.zero : const Offset(-1.0, 0),
                  duration: const Duration(milliseconds: 280),
                  curve: Curves.easeInOut,
                  child: Align(
                    alignment: Alignment.topLeft,
                    child: Consumer<ProjectNotifier>(
                      builder: (_, n, __) => _MobileActivityPanelOverlay(
                        notifier: n,
                        mapController: _mapController,
                        height: mapHeight,
                      ),
                    ),
                  ),
                ),

                // Toggle FAB: sits just above the elevation chart
                Positioned(
                  left: 12,
                  bottom: 172,
                  child: Builder(builder: (ctx) {
                    final theme = Theme.of(ctx);
                    return FloatingActionButton.small(
                      heroTag: 'activityPanelToggle',
                      backgroundColor: theme.colorScheme.surface,
                      foregroundColor: theme.colorScheme.onSurface,
                      onPressed: _togglePanel,
                      child: AnimatedRotation(
                        turns: _panelOpen ? 0.5 : 0.0,
                        duration: const Duration(milliseconds: 280),
                        child: const Icon(Icons.chevron_right),
                      ),
                    );
                  }),
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
  dynamic _lastSelectedSegId = _sentinel;
  List<Polyline> _cachedPolylines = [];
  List<LatLng> _cachedAllPoints = [];
  List<Marker> _cachedSegmentMarkers = [];
  late final NetworkTileProvider _tileProvider;

  static const _sentinel = Object(); // distinct from null

  @override
  void initState() {
    super.initState();
    _tileProvider = NetworkTileProvider();
  }

  List<Polyline> _buildPolylines(
    Map<String, dynamic> geo,
    dynamic selectedActivityId,
    dynamic selectedSegmentId,
  ) {
    final features = geo['features'];
    if (features is! List) return [];

    final polylines = <Polyline>[];
    final hasSelection = selectedActivityId != null || selectedSegmentId != null;
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
      final isSelAct = selectedActivityId != null &&
          props['activity_id']?.toString() == selectedActivityId.toString();
      final isSelSeg = selectedSegmentId != null &&
          props['segment_id']?.toString() == selectedSegmentId.toString();

      final Color color;
      final double strokeWidth;
      if (isSegment) {
        if (isSelSeg) {
          color = const Color(0xFF44AAFF);   // bright blue — selected segment
          strokeWidth = 4.0;
        } else if (hasSelection) {
          color = const Color(0x60888888);   // dimmed grey
          strokeWidth = 2.0;
        } else {
          color = const Color(0xFF888888);   // normal grey
          strokeWidth = 2.0;
        }
      } else {
        if (isSelAct) {
          color = const Color(0xFFEF4444);   // red — selected activity
          strokeWidth = 5.0;
        } else if (hasSelection) {
          color = const Color(0x60F97316);   // dimmed orange
          strokeWidth = 2.5;
        } else {
          color = const Color(0xFFF97316);   // full orange
          strokeWidth = 2.5;
        }
      }
      polylines.add(Polyline(points: points, color: color, strokeWidth: strokeWidth));
    }
    return polylines;
  }

  static IconData _iconForSegmentType(String? type) {
    switch (type?.toLowerCase()) {
      case 'flight': return Icons.flight;
      case 'train':  return Icons.train;
      case 'bus':    return Icons.directions_bus;
      case 'boat':   return Icons.directions_boat;
      default:       return Icons.route;
    }
  }

  List<Marker> _buildSegmentMarkers(
    Map<String, dynamic> geo,
    dynamic selectedSegmentId,
    bool hasSelection,
  ) {
    final features = geo['features'];
    if (features is! List) return [];
    final markers = <Marker>[];
    for (final feature in features) {
      if (feature is! Map) continue;
      final props = feature['properties'] as Map? ?? {};
      if (props['type'] != 'segment') continue;
      final coords = (feature['geometry'] as Map? ?? {})['coordinates'];
      if (coords is! List || coords.isEmpty) continue;

      final mid = coords[coords.length ~/ 2];
      if (mid is! List || mid.length < 2) continue;
      final point = LatLng((mid[1] as num).toDouble(), (mid[0] as num).toDouble());

      final segId = props['segment_id']?.toString();
      final isSelected = selectedSegmentId != null &&
          segId == selectedSegmentId.toString();

      final bgColor = isSelected
          ? const Color(0xFF44AAFF)
          : hasSelection
              ? const Color(0x60888888)
              : const Color(0xFF888888);

      markers.add(Marker(
        point: point,
        width: 22,
        height: 22,
        child: Container(
          decoration: BoxDecoration(color: bgColor, shape: BoxShape.circle),
          child: Icon(
            _iconForSegmentType(props['segment_type'] as String?),
            color: Colors.white,
            size: 13,
          ),
        ),
      ));
    }
    return markers;
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

  @override
  Widget build(BuildContext context) {
    final notifier = widget.notifier;

    // Recompute polylines only when geo or selection changes.
    final geo = notifier.geo;
    final selActId = notifier.selectedActivityId;
    final selSegId = notifier.selectedSegmentId;
    if (!identical(geo, _lastGeo) || selActId != _lastSelectedId ||
        selSegId.toString() != (_lastSelectedSegId ?? '').toString()) {
      _lastGeo = geo;
      _lastSelectedId = selActId;
      _lastSelectedSegId = selSegId;
      _cachedPolylines = geo != null ? _buildPolylines(geo, selActId, selSegId) : [];
      _cachedAllPoints = _allPoints(_cachedPolylines);
      final hasSelection = selActId != null || selSegId != null;
      _cachedSegmentMarkers = geo != null
          ? _buildSegmentMarkers(geo, selSegId, hasSelection)
          : [];
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
          options: MapOptions(
            initialCenter: const LatLng(0, 0),
            initialZoom: 2,
            interactionOptions: const InteractionOptions(
              flags: InteractiveFlag.all & ~InteractiveFlag.rotate,
            ),
            onTap: (_, latlng) => _onMapTap(latlng),
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
            if (_cachedSegmentMarkers.isNotEmpty)
              MarkerLayer(markers: _cachedSegmentMarkers),
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
            // Elevation cursor — driven by chart hover/tap and by map taps.
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

// ── Day-grouping display list helpers ─────────────────────────────────────────

class _DayHeader {
  final int dayNumber;
  final DateTime date;
  final String dateKey; // "YYYY-MM-DD"
  const _DayHeader(this.dayNumber, this.date, this.dateKey);
}

class _PanelItem {
  final int originalIndex;
  final Map<String, dynamic> item;
  final String? dateKey;
  const _PanelItem(this.originalIndex, this.item, this.dateKey);
}

// ─────────────────────────────────────────────────────────────────────────────

class _ActivityPanelState extends State<ActivityPanel> {
  // activityById cache — rebuilt only when the activities list reference changes.
  List<Map<String, dynamic>>? _lastActivities;
  Map<dynamic, Map<String, dynamic>> _activityById = {};

  // Day grouping state
  Set<int> _collapsedDays = {};
  String? _selectedDay; // "YYYY-MM-DD"

  // Display list cache — rebuilt when items or activities change.
  List<Map<String, dynamic>>? _lastItems;
  List<Object> _displayList = [];

  // Theme-derived styles cached in didChangeDependencies so copyWith is not
  // called on every build().
  TextStyle? _segmentTitleStyle;

  static const _months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  static String _fmtGroupDate(DateTime d) => '${_months[d.month - 1]} ${d.day}';

  void _refreshActivityById(List<Map<String, dynamic>> activities) {
    if (identical(activities, _lastActivities)) return;
    _lastActivities = activities;
    _activityById = {for (final a in activities) a['id']: a};
  }

  void _rebuildDisplayList(
    List<Map<String, dynamic>> items,
    String? tripStartOverride,
  ) {
    if (identical(items, _lastItems) && tripStartOverride == _lastTripStart) return;
    _lastItems = items;
    _lastTripStart = tripStartOverride;
    _displayList = _buildDisplayList(items, _activityById, tripStartOverride);
  }

  String? _lastTripStart;

  List<Object> _buildDisplayList(
    List<Map<String, dynamic>> items,
    Map<dynamic, Map<String, dynamic>> activityById,
    String? tripStartOverride,
  ) {
    if (items.isEmpty) return [];

    // Assign each item a date ("YYYY-MM-DD"), propagating forward.
    final itemDates = <String?>[];
    String? lastDate;
    for (final item in items) {
      String? d;
      if (item['item_type'] == 'activity') {
        final a = activityById[item['activity_id']];
        final ds = a?['start_date_local'] as String?;
        d = ds?.split('T').first;
        if (d != null) lastDate = d;
      } else {
        d = item['segment']?['date'] as String? ?? lastDate;
      }
      itemDates.add(d);
    }

    // Determine trip start: use override if set, else earliest date in items.
    final allDates = itemDates.whereType<String>().toSet().toList()..sort();
    if (allDates.isEmpty) {
      return [for (int i = 0; i < items.length; i++) _PanelItem(i, items[i], null)];
    }
    final tripStartStr = tripStartOverride ?? allDates.first;
    final ts = DateTime.parse(tripStartStr);
    final tripStartDate = DateTime(ts.year, ts.month, ts.day);

    // Sort unique date keys ascending, then build display list in that order.
    final sortedDates = allDates.toList(); // already sorted ascending

    // Build a map from dateKey → list of (originalIndex, item) pairs.
    final byDate = <String, List<(int, Map<String, dynamic>)>>{};
    final undated = <(int, Map<String, dynamic>)>[];
    for (int i = 0; i < items.length; i++) {
      final dk = itemDates[i];
      if (dk == null) {
        undated.add((i, items[i]));
      } else {
        byDate.putIfAbsent(dk, () => []).add((i, items[i]));
      }
    }

    final result = <Object>[];
    for (final dk in sortedDates) {
      final d = DateTime.parse(dk);
      final groupDate = DateTime(d.year, d.month, d.day);
      final dayNum = groupDate.difference(tripStartDate).inDays + 1;
      result.add(_DayHeader(dayNum, d, dk));
      if (!_collapsedDays.contains(dayNum)) {
        for (final (int idx, Map<String, dynamic> item) in byDate[dk] ?? []) {
          result.add(_PanelItem(idx, item, dk));
        }
      }
    }
    // Undated items always appear at the end, uncollapsible.
    for (final (int idx, Map<String, dynamic> item) in undated) {
      result.add(_PanelItem(idx, item, null));
    }
    return result;
  }

  @override
  void initState() {
    super.initState();
    _refreshActivityById(widget.notifier.activities);
    _rebuildDisplayList(widget.notifier.items, widget.notifier.tripStart);
  }

  @override
  void didUpdateWidget(ActivityPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    _refreshActivityById(widget.notifier.activities);
    _rebuildDisplayList(widget.notifier.items, widget.notifier.tripStart);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final theme = Theme.of(context);
    _segmentTitleStyle =
        theme.textTheme.bodyMedium?.copyWith(fontStyle: FontStyle.italic);
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

  void _dismissWithUndo({
    required BuildContext context,
    required ProjectNotifier notifier,
    required String label,
    required Future<void> Function() onConfirm,
  }) {
    final messenger = ScaffoldMessenger.of(context);
    messenger.clearSnackBars();
    final controller = messenger.showSnackBar(SnackBar(
      content: Text(label),
      duration: const Duration(seconds: 5),
      action: SnackBarAction(
        label: 'Undo',
        onPressed: () {
          final name = notifier.projectName;
          if (name != null) notifier.load(name);
        },
      ),
    ));
    controller.closed.then((reason) {
      if (reason != SnackBarClosedReason.action) {
        onConfirm();
      }
    });
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

  void _flyToSegment(Map<String, dynamic> seg) {
    widget.notifier.selectSegment(seg['id']);
    final start = seg['start'] as Map?;
    final end   = seg['end']   as Map?;
    if (start == null || end == null) return;
    final lat = ((start['lat'] as num? ?? 0) + (end['lat'] as num? ?? 0)) / 2;
    final lon = ((start['lon'] as num? ?? 0) + (end['lon'] as num? ?? 0)) / 2;
    final target = LatLng(lat, lon);
    final mc = widget.mapController;
    if (mc == null) return;
    if (!mc.camera.visibleBounds.contains(target)) {
      mc.move(target, mc.camera.zoom.clamp(4.0, 10.0));
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

        // ── Items list (activities + segments, reorderable, day-grouped) ────────
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
              : Builder(builder: (context) {
                  // Rebuild display list if items changed.
                  _rebuildDisplayList(items, notifier.tripStart);
                  final displayList = _displayList;
                  return ReorderableListView.builder(
                    scrollController: widget.scrollController,
                    buildDefaultDragHandles: false,
                    onReorder: (fromV, toV) {
                      final fromEntry = fromV < displayList.length
                          ? displayList[fromV] : null;
                      if (fromEntry is! _PanelItem) return;
                      final fromOrig = fromEntry.originalIndex;
                      final adjToV = toV > fromV ? toV - 1 : toV;
                      int origCount = 0;
                      int? toOrig;
                      for (int k = 0; k < displayList.length; k++) {
                        if (k == adjToV) { toOrig = origCount; break; }
                        if (displayList[k] is _PanelItem) origCount++;
                      }
                      toOrig ??= notifier.items.length - 1;
                      notifier.reorderItems(fromOrig, toOrig);
                    },
                    itemCount: displayList.length,
                    itemBuilder: (context, vi) {
                      final entry = displayList[vi];

                      // ── Day header ──────────────────────────────────────────
                      if (entry is _DayHeader) {
                        final h = entry;
                        final isSelected = _selectedDay == h.dateKey;
                        final isCollapsed = _collapsedDays.contains(h.dayNumber);
                        return InkWell(
                          key: ValueKey('header_${h.dayNumber}'),
                          onTap: () {
                            final newDay = isSelected ? null : h.dateKey;
                            setState(() => _selectedDay = newDay);
                            notifier.selectDay(newDay);
                          },
                          child: Container(
                            color: isSelected
                                ? theme.colorScheme.primaryContainer
                                    .withValues(alpha: 0.4)
                                : null,
                            padding: const EdgeInsets.fromLTRB(4, 4, 8, 2),
                            child: Row(children: [
                              IconButton(
                                icon: Icon(
                                  isCollapsed
                                      ? Icons.chevron_right
                                      : Icons.expand_more,
                                  size: 20,
                                ),
                                visualDensity: VisualDensity.compact,
                                onPressed: () => setState(() {
                                  if (isCollapsed) {
                                    _collapsedDays.remove(h.dayNumber);
                                  } else {
                                    _collapsedDays.add(h.dayNumber);
                                  }
                                  // Force rebuild of display list.
                                  _lastItems = null;
                                }),
                              ),
                              Text(
                                'Day ${h.dayNumber} · ${_fmtGroupDate(h.date)}',
                                style: theme.textTheme.labelMedium?.copyWith(
                                  color: isSelected
                                      ? theme.colorScheme.primary
                                      : theme.colorScheme.onSurfaceVariant,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ]),
                          ),
                        );
                      }

                      // ── Activity or segment item ─────────────────────────────
                      final panelItem = entry as _PanelItem;
                      final i = panelItem.originalIndex;
                      final item = panelItem.item;
                      final isActivity = item['item_type'] == 'activity';
                      final dragHandle = ReorderableDragStartListener(
                        index: vi,
                        child: const Icon(Icons.drag_handle,
                            size: 18, color: Colors.grey),
                      );

                      if (isActivity) {
                        final a = activityById[item['activity_id']];
                        if (a == null) {
                          return Dismissible(
                            key: ValueKey('act_${item['activity_id']}'),
                            direction: DismissDirection.endToStart,
                            onDismissed: (_) => _dismissWithUndo(
                              context: context,
                              notifier: notifier,
                              label: 'Activity removed',
                              onConfirm: () => notifier.removeItem(i),
                            ),
                            background: Container(
                              color: theme.colorScheme.error,
                              alignment: Alignment.centerRight,
                              padding: const EdgeInsets.only(right: 20),
                              child: Icon(Icons.delete_outline,
                                  color: theme.colorScheme.onError),
                            ),
                            child: ListTile(
                              leading: dragHandle,
                              title: const Text('Unknown activity'),
                              trailing: const Icon(Icons.help_outline),
                            ),
                          );
                        }
                        final type = a['type'] as String?;
                        final name = a['name'] as String? ?? 'Activity';
                        final distM = (a['distance'] as num? ?? 0).toDouble();
                        final movingSec = a['moving_time'];
                        final activityId = item['activity_id'];
                        return Dismissible(
                          key: ValueKey('act_$activityId'),
                          direction: DismissDirection.endToStart,
                          onDismissed: (_) => _dismissWithUndo(
                            context: context,
                            notifier: notifier,
                            label: 'Removed "$name"',
                            onConfirm: () => notifier.removeItem(i),
                          ),
                          background: Container(
                            color: theme.colorScheme.error,
                            alignment: Alignment.centerRight,
                            padding: const EdgeInsets.only(right: 20),
                            child: Icon(Icons.delete_outline,
                                color: theme.colorScheme.onError),
                          ),
                          child: Selector<ProjectNotifier, bool>(
                            selector: (_, n) =>
                                activityId?.toString() ==
                                n.selectedActivityId?.toString(),
                            builder: (_, isSelected, __) => ListTile(
                              tileColor: isSelected
                                  ? theme.colorScheme.primaryContainer
                                      .withValues(alpha: 0.45)
                                  : null,
                              leading: dragHandle,
                              title: Row(children: [
                                Icon(
                                  _iconForActivityType(type),
                                  size: 16,
                                  color: isSelected
                                      ? theme.colorScheme.primary
                                      : theme.colorScheme.primary
                                          .withValues(alpha: 0.7),
                                ),
                                const SizedBox(width: 8),
                                Flexible(
                                  child: Text(name,
                                      style: theme.textTheme.bodyMedium),
                                ),
                              ]),
                              subtitle: Text(
                                '${(distM / 1000).toStringAsFixed(1)} km  •  ${_formatDuration(movingSec)}',
                                style: theme.textTheme.bodySmall,
                              ),
                              trailing: IconButton(
                                icon: const Icon(Icons.add_road, size: 18),
                                tooltip: 'Add connecting segment after',
                                onPressed: () => _showSegmentDialog(
                                  context,
                                  notifier,
                                  insertAfterIndex: i,
                                ),
                              ),
                              onTap: () => _flyToActivity(a),
                            ),
                          ),
                        );
                      } else {
                        // Segment item
                        final seg =
                            item['segment'] as Map<String, dynamic>? ?? {};
                        final segId = seg['id'] as String? ?? '';
                        final segType = seg['segment_type'] as String?;
                        final label =
                            seg['label'] as String? ?? segType ?? 'Segment';
                        return Dismissible(
                          key: ValueKey('seg_$segId'),
                          direction: DismissDirection.endToStart,
                          onDismissed: (_) => _dismissWithUndo(
                            context: context,
                            notifier: notifier,
                            label: 'Removed "$label"',
                            onConfirm: () => notifier.deleteSegment(segId),
                          ),
                          background: Container(
                            color: theme.colorScheme.error,
                            alignment: Alignment.centerRight,
                            padding: const EdgeInsets.only(right: 20),
                            child: Icon(Icons.delete_outline,
                                color: theme.colorScheme.onError),
                          ),
                          child: Selector<ProjectNotifier, bool>(
                            selector: (_, n) =>
                                n.selectedSegmentId?.toString() == segId,
                            builder: (_, isSelected, __) => ListTile(
                              tileColor: isSelected
                                  ? theme.colorScheme.secondaryContainer
                                      .withValues(alpha: 0.45)
                                  : null,
                              leading: dragHandle,
                              title: Row(children: [
                                Icon(
                                  _iconForSegmentType(segType),
                                  size: 16,
                                  color: isSelected
                                      ? theme.colorScheme.secondary
                                      : theme.colorScheme.secondary
                                          .withValues(alpha: 0.7),
                                ),
                                const SizedBox(width: 8),
                                Flexible(
                                  child: Text(label,
                                      style: _segmentTitleStyle),
                                ),
                              ]),
                              subtitle: Text(segType ?? '',
                                  style: theme.textTheme.bodySmall),
                              trailing: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  IconButton(
                                    icon: const Icon(Icons.edit_outlined,
                                        size: 18),
                                    tooltip: 'Edit segment',
                                    onPressed: () => _showSegmentDialog(
                                      context,
                                      notifier,
                                      editSegment: seg,
                                      insertAfterIndex: null,
                                    ),
                                  ),
                                  IconButton(
                                    icon: const Icon(Icons.add_road, size: 18),
                                    tooltip: 'Add connecting segment after',
                                    onPressed: () => _showSegmentDialog(
                                      context,
                                      notifier,
                                      insertAfterIndex: i,
                                    ),
                                  ),
                                ],
                              ),
                              onTap: () => _flyToSegment(seg),
                            ),
                          ),
                        );
                      }
                    },
                  );
                }),
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

  // Polyline + marker cache — only rebuilt when geo or selection changes.
  Map<String, dynamic>? _lastGeo;
  dynamic _lastSelectedId = _sentinel;
  dynamic _lastSelectedSegId = _sentinel;
  String? _lastSelectedDay = '';   // '' = sentinel (distinct from null)
  List<Polyline> _cachedPolylines = [];
  List<Marker> _cachedSegmentMarkers = [];

  static const _sentinel = Object();

  static IconData _iconForSegmentType(String? type) {
    switch (type?.toLowerCase()) {
      case 'flight': return Icons.flight;
      case 'train':  return Icons.train;
      case 'bus':    return Icons.directions_bus;
      case 'boat':   return Icons.directions_boat;
      default:       return Icons.route;
    }
  }

  List<Marker> _buildSegmentMarkers(
    Map<String, dynamic> geo,
    dynamic selectedSegmentId,
    bool hasSelection,
  ) {
    final features = geo['features'];
    if (features is! List) return [];
    final markers = <Marker>[];
    for (final feature in features) {
      if (feature is! Map) continue;
      final props = feature['properties'] as Map? ?? {};
      if (props['type'] != 'segment') continue;
      final coords = (feature['geometry'] as Map? ?? {})['coordinates'];
      if (coords is! List || coords.isEmpty) continue;

      final mid = coords[coords.length ~/ 2];
      if (mid is! List || mid.length < 2) continue;
      final point = LatLng((mid[1] as num).toDouble(), (mid[0] as num).toDouble());

      final segId = props['segment_id']?.toString();
      final isSelected = selectedSegmentId != null &&
          segId == selectedSegmentId.toString();

      final bgColor = isSelected
          ? const Color(0xFF44AAFF)
          : hasSelection
              ? const Color(0x60888888)
              : const Color(0xFF888888);

      markers.add(Marker(
        point: point,
        width: 22,
        height: 22,
        child: Container(
          decoration: BoxDecoration(color: bgColor, shape: BoxShape.circle),
          child: Icon(
            _iconForSegmentType(props['segment_type'] as String?),
            color: Colors.white,
            size: 13,
          ),
        ),
      ));
    }
    return markers;
  }

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

  /// Compute the set of activity_ids and segment_ids that belong to [dateKey].
  static ({Set<String> actIds, Set<String> segIds}) _dayItemIds(
    List<Map<String, dynamic>> items,
    Map<dynamic, Map<String, dynamic>> activityById,
    String dateKey,
  ) {
    final actIds = <String>{};
    final segIds = <String>{};
    String? lastDate;
    for (final item in items) {
      if (item['item_type'] == 'activity') {
        final a = activityById[item['activity_id']];
        final ds = (a?['start_date_local'] as String?)?.split('T').first;
        if (ds != null) lastDate = ds;
        if ((ds ?? lastDate) == dateKey) {
          final id = item['activity_id']?.toString();
          if (id != null) actIds.add(id);
        }
      } else {
        final ds = item['segment']?['date'] as String? ?? lastDate;
        if (ds == dateKey) {
          final id = item['segment']?['id']?.toString();
          if (id != null) segIds.add(id);
        }
      }
    }
    return (actIds: actIds, segIds: segIds);
  }

  List<Polyline> _buildPolylines(
    Map<String, dynamic> geo,
    dynamic selectedActivityId,
    dynamic selectedSegmentId,
    String? selectedDay,
    Map<dynamic, Map<String, dynamic>> activityById,
    List<Map<String, dynamic>> items,
  ) {
    final features = geo['features'];
    if (features is! List) return [];

    // For day selection, compute which ids are in that day.
    Set<String>? dayActIds;
    Set<String>? daySegIds;
    if (selectedDay != null) {
      final r = _dayItemIds(items, activityById, selectedDay);
      dayActIds = r.actIds;
      daySegIds = r.segIds;
    }

    final polylines = <Polyline>[];
    final hasSelection = selectedActivityId != null ||
        selectedSegmentId != null ||
        selectedDay != null;
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
      final featureId = isSegment
          ? props['segment_id']?.toString()
          : props['activity_id']?.toString();

      final bool isHighlighted;
      if (selectedDay != null) {
        isHighlighted = isSegment
            ? (daySegIds?.contains(featureId) ?? false)
            : (dayActIds?.contains(featureId) ?? false);
      } else if (isSegment) {
        isHighlighted = selectedSegmentId != null &&
            featureId == selectedSegmentId.toString();
      } else {
        isHighlighted = selectedActivityId != null &&
            featureId == selectedActivityId.toString();
      }

      final Color color;
      final double strokeWidth;
      if (isSegment) {
        if (isHighlighted) {
          color = const Color(0xFF44AAFF);
          strokeWidth = 4.0;
        } else if (hasSelection) {
          color = const Color(0x60888888);
          strokeWidth = 2.0;
        } else {
          color = const Color(0xFF888888);
          strokeWidth = 2.0;
        }
      } else {
        if (isHighlighted) {
          color = const Color(0xFFEF4444);
          strokeWidth = 5.0;
        } else if (hasSelection) {
          color = const Color(0x60F97316);
          strokeWidth = 2.5;
        } else {
          color = const Color(0xFFF97316);
          strokeWidth = 2.5;
        }
      }
      polylines.add(Polyline(points: points, color: color, strokeWidth: strokeWidth));
    }
    return polylines;
  }

  @override
  Widget build(BuildContext context) {
    final notifier = widget.notifier;
    final geo = notifier.geo;
    final selActId = notifier.selectedActivityId;
    final selSegId = notifier.selectedSegmentId;
    final selDay = notifier.selectedDay;
    if (!identical(geo, _lastGeo) || selActId != _lastSelectedId ||
        selSegId.toString() != (_lastSelectedSegId ?? '').toString() ||
        selDay != _lastSelectedDay) {
      if (!identical(geo, _lastGeo)) _fittedBounds = false;
      _lastGeo = geo;
      _lastSelectedId = selActId;
      _lastSelectedSegId = selSegId;
      _lastSelectedDay = selDay;
      // Build activityById for day-selection polyline colouring.
      final actById = <dynamic, Map<String, dynamic>>{
        for (final a in notifier.activities) a['id']: a
      };
      _cachedPolylines = geo != null
          ? _buildPolylines(geo, selActId, selSegId, selDay, actById, notifier.items)
          : [];
      final hasSelection = selActId != null || selSegId != null || selDay != null;
      _cachedSegmentMarkers = geo != null
          ? _buildSegmentMarkers(geo, selSegId, hasSelection)
          : [];
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
            if (_cachedSegmentMarkers.isNotEmpty)
              MarkerLayer(markers: _cachedSegmentMarkers),
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

  /// Pre-built distance-indexed track (cumulative km → LatLng).
  /// Built by ProjectNotifier from GeoJSON so Flutter never needs to decode
  /// the polyline.  Pass fullTrack when no activity is selected, or the
  /// per-activity track (0-based distances) when one is selected.
  final List<(double, LatLng)> track;

  const ElevationChart({
    super.key,
    required this.activities,
    required this.track,
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
    double offsetKm = 0;
    for (final a in source) {
      final profile = a['elevation_profile'];
      if (profile is! List || profile.isEmpty) continue;
      final lastPt = profile.last;
      final elevTotalKm = (lastPt is List && lastPt.isNotEmpty)
          ? (lastPt[0] as num).toDouble()
          : 0.0;
      for (int i = 0; i < profile.length; i++) {
        final point = profile[i];
        if (point is! List || point.length < 2) continue;
        spots.add(FlSpot(
            (point[0] as num).toDouble() + offsetKm,
            (point[1] as num).toDouble()));
      }
      if (elevTotalKm > 0) offsetKm += elevTotalKm;
    }
    if (spots.isNotEmpty) {
      // Compute min/max over full data before downsampling — LTTB may not
      // select the global peak or valley, but the y-axis must contain them.
      double minY = spots.first.y, maxY = spots.first.y;
      for (final s in spots) {
        if (s.y < minY) minY = s.y;
        if (s.y > maxY) maxY = s.y;
      }
      _minY = minY;
      _maxY = maxY;
    }
    _spots = spots.length > _kMaxChartPoints ? _lttb(spots, _kMaxChartPoints) : spots;
  }

  /// Maximum number of FlSpot points rendered by fl_chart.
  /// LTTB downsampling preserves visual shape; cursor uses the full-resolution
  /// [widget.track] so accuracy is unaffected.
  static const _kMaxChartPoints = 300;

  /// Largest-Triangle-Three-Buckets downsampling.  O(n) — selects [threshold]
  /// points from [data] that best preserve the visual shape of the series.
  static List<FlSpot> _lttb(List<FlSpot> data, int threshold) {
    final n = data.length;
    assert(n > threshold);
    final out = <FlSpot>[data.first];
    int a = 0;
    final every = (n - 2) / (threshold - 2);
    for (int i = 0; i < threshold - 2; i++) {
      // Centroid of the next bucket — used as the "future" anchor.
      final nS = ((i + 1) * every + 1).floor();
      final nE = ((i + 2) * every + 1).floor().clamp(0, n);
      double avgX = 0, avgY = 0;
      for (int j = nS; j < nE; j++) { avgX += data[j].x; avgY += data[j].y; }
      final cnt = nE - nS;
      avgX /= cnt; avgY /= cnt;
      // Current bucket — pick the point that forms the largest triangle
      // with the previously selected point (a) and the next-bucket centroid.
      final cS = (i * every + 1).floor();
      final cE = ((i + 1) * every + 1).floor().clamp(0, n);
      final ax = data[a].x, ay = data[a].y;
      double maxArea = -1; int best = cS;
      for (int j = cS; j < cE; j++) {
        final area = ((ax - avgX) * (data[j].y - ay)
                    - (ax - data[j].x) * (avgY - ay)).abs();
        if (area > maxArea) { maxArea = area; best = j; }
      }
      out.add(data[best]);
      a = best;
    }
    out.add(data.last);
    return out;
  }

  void _onTouch(FlTouchEvent event, LineTouchResponse? response) {
    // Do NOT clear on FlPointerExitEvent — the cursor should persist at the
    // last hovered/clicked position so the user can inspect it after moving
    // the mouse off the chart.
    final spots = response?.lineBarSpots;
    if (spots == null || spots.isEmpty) return;
    final pos = latLonAtDistance(widget.track, spots.first.x);
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

// ── _MobileActivityPanelOverlay ───────────────────────────────────────────────
// Slide-in activity panel for narrow (mobile) layout. Rendered as a Material
// surface with elevation so it casts a shadow over the map behind it.

class _MobileActivityPanelOverlay extends StatelessWidget {
  final ProjectNotifier notifier;
  final MapController mapController;
  final double height;

  const _MobileActivityPanelOverlay({
    required this.notifier,
    required this.mapController,
    required this.height,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      elevation: 4,
      color: Theme.of(context).colorScheme.surface,
      child: SizedBox(
        width: 280,
        height: height,
        child: ActivityPanel(
          notifier: notifier,
          mapController: mapController,
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
