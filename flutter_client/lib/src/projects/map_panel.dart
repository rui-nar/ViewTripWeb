library;

import 'dart:math' show pow;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_map_animations/flutter_map_animations.dart';
import 'package:latlong2/latlong.dart';
import 'package:vector_map_tiles/vector_map_tiles.dart';

import '../map/geo_point.dart';
import 'activity_panel.dart';
import 'basemaps.dart';
import 'memory_detail_modal.dart';
import 'project_notifier.dart';
LatLng _ll(GeoPoint p) => LatLng(p.lat, p.lon);

// ── MapPanel ──────────────────────────────────────────────────────────────────

class MapPanel extends StatefulWidget {
  final ProjectNotifier notifier;
  final AnimatedMapController mapController;
  final String basemapUrl;
  final List<String> basemapSubdomains;
  final String? labelsUrl;
  /// Mapbox vector style URI (e.g. `mapbox://styles/mapbox/satellite-streets-v12`).
  /// When set and non-null, a VectorTileLayer replaces the raster TileLayer.
  final String? basemapStyleUri;

  /// When set, a raster TileLayer is added for the track base layer and
  /// the PolylineLayer is filtered to the selected item only (for highlights).
  /// Template variables `{z}`, `{x}`, `{y}` are filled in by flutter_map.
  final String? trackTileUrlTemplate;

  const MapPanel({
    super.key,
    required this.notifier,
    required this.mapController,
    required this.basemapUrl,
    this.basemapSubdomains = const [],
    this.labelsUrl,
    this.basemapStyleUri,
    this.trackTileUrlTemplate,
  });

  @override
  State<MapPanel> createState() => _MapPanelState();
}

class _MapPanelState extends State<MapPanel> {
  bool _fittedBounds = false;
  // Polyline + bounds cache — only rebuilt when geo, selection, or style changes.
  Map<String, dynamic>? _lastGeo;
  dynamic _lastSelectedId = _sentinel;
  dynamic _lastSelectedSegId = _sentinel;
  dynamic _lastSelectedMemId = _sentinel;
  dynamic _lastSelectedJournalId = _sentinel;
  List<Map<String, dynamic>>? _lastItems;
  Color? _lastTrackColor;
  double? _lastTrackWidth;
  bool? _lastAlternating;
  bool? _lastShowJournals;
  List<Polyline> _cachedPolylines = [];
  List<LatLng> _cachedAllPoints = [];
  List<Marker> _cachedSegmentMarkers = [];
  List<Marker> _cachedMemoryMarkers = [];
  List<Marker> _cachedJournalMarkers = [];
  bool _showMemories = true;
  NetworkTileProvider? _tileProvider;
  Style? _vectorStyle;

  static const _sentinel = Object(); // distinct from null

  @override
  void initState() {
    super.initState();
    if (widget.basemapStyleUri != null) {
      () async {
        try {
          final s = await StyleReader(
                  uri: widget.basemapStyleUri!,
                  apiKey: kMapboxToken)
              .read();
          if (!mounted) return;
          setState(() => _vectorStyle = s);
        } catch (e) {
          debugPrint('[MapPanel] StyleReader error: $e');
        }
      }();
    } else {
      _tileProvider = NetworkTileProvider();
    }
  }

  static Color _alternateColor(Color base) {
    final hsl = HSLColor.fromColor(base);
    return hsl
        .withSaturation((hsl.saturation * 0.42).clamp(0.0, 1.0))
        .withLightness((hsl.lightness * 1.18).clamp(0.0, 1.0))
        .toColor();
  }

  List<LatLng> _allPointsFromGeo(Map<String, dynamic> geo) {
    final features = geo['features'];
    if (features is! List) return [];
    final pts = <LatLng>[];
    for (final f in features) {
      if (f is! Map) continue;
      final coords = (f['geometry'] as Map? ?? {})['coordinates'];
      if (coords is! List) continue;
      for (final c in coords) {
        if (c is List && c.length >= 2) {
          pts.add(LatLng((c[1] as num).toDouble(), (c[0] as num).toDouble()));
        }
      }
    }
    return pts;
  }

  List<Polyline> _buildPolylines(
    Map<String, dynamic> geo,
    dynamic selectedActivityId,
    dynamic selectedSegmentId,
    Color trackColor,
    double trackWidth,
    bool alternating,
    List<Map<String, dynamic>> items, {
    bool selectedOnly = false,
    Color? trackSecondaryColor,
  }) {
    final features = geo['features'];
    if (features is! List) return [];

    // Build activity-index map for alternating colours.
    final actIdx = <String, int>{};
    int ai = 0;
    for (final item in items) {
      if (item['item_type'] == 'activity') {
        final id = item['activity_id']?.toString();
        if (id != null) actIdx[id] = ai++;
      }
    }
    final altColor = trackSecondaryColor ?? _alternateColor(trackColor);

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
          points.add(LatLng((c[1] as num).toDouble(), (c[0] as num).toDouble()));
        }
      }
      if (points.isEmpty) continue;

      final isSegment = props['type'] == 'segment';
      final actId = props['activity_id']?.toString();
      final isSelAct = selectedActivityId != null &&
          actId == selectedActivityId.toString();
      final isSelSeg = selectedSegmentId != null &&
          props['segment_id']?.toString() == selectedSegmentId.toString();

      // When tile layer handles the base rendering, only draw the selected item.
      if (selectedOnly && !isSelAct && !isSelSeg) continue;
      final isOdd = alternating && actId != null && (actIdx[actId] ?? 0).isOdd;

      final Color color;
      final double strokeWidth;
      if (isSegment) {
        if (isSelSeg) {
          color = trackColor;
          strokeWidth = (trackWidth * 1.9).clamp(4.0, 8.0);
        } else if (hasSelection) {
          color = trackColor.withAlpha(0x60);
          strokeWidth = trackWidth;
        } else {
          color = trackColor;
          strokeWidth = trackWidth;
        }
      } else {
        if (isSelAct) {
          color = trackColor;
          strokeWidth = (trackWidth * 1.9).clamp(4.0, 8.0);
        } else if (hasSelection) {
          color = trackColor.withAlpha(0x60);
          strokeWidth = trackWidth;
        } else {
          color = isOdd ? altColor : trackColor;
          strokeWidth = trackWidth;
        }
      }
      polylines.add(Polyline(
        points: points,
        color: color,
        strokeWidth: strokeWidth,
        pattern: isSegment
            ? StrokePattern.dashed(segments: const [12, 8])
            : const StrokePattern.solid(),
      ));
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
    Color trackColor,
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
          ? trackColor
          : hasSelection
              ? trackColor.withAlpha(0x60)
              : trackColor;

      markers.add(Marker(
        point: point,
        width: 22,
        height: 22,
        child: Container(
          decoration: BoxDecoration(color: bgColor, shape: BoxShape.circle),
          child: Icon(
            _iconForSegmentType(
              (props['segment_type'] as String?) ??
              (props['route_mode'] == 'rail' ? 'train' : null),
            ),
            color: Colors.white,
            size: 13,
          ),
        ),
      ));
    }
    return markers;
  }

  List<Marker> _buildMemoryMarkers(
    List<Map<String, dynamic>> items,
    dynamic selectedMemoryId,
    bool hasSelection,
    BuildContext context,
  ) {
    final markers = <Marker>[];
    final authHeaders = widget.notifier.photoAuthHeaders;
    for (final item in items) {
      if (item['item_type'] != 'memory') continue;
      final mem = item['memory'] as Map<String, dynamic>?;
      if (mem == null) continue;
      final lat = (mem['lat'] as num?)?.toDouble();
      final lon = (mem['lon'] as num?)?.toDouble();
      if (lat == null || lon == null) continue;
      final memId = mem['id']?.toString() ?? '';
      final photos = (mem['photos'] as List?)?.cast<String>() ?? [];
      final isSelected = selectedMemoryId?.toString() == memId;
      final size = isSelected ? 34.0 : 28.0;
      final bgColor = isSelected
          ? const Color(0xFFEA580C)
          : hasSelection
              ? const Color(0xA0F97316)
              : const Color(0xFFF97316);
      Widget inner;
      if (photos.isNotEmpty) {
        final thumbUrl = widget.notifier.photoThumbUrl(memId, photos.first);
        inner = ClipOval(
          child: Image.network(
            thumbUrl,
            width: size,
            height: size,
            fit: BoxFit.cover,
            headers: authHeaders,
            errorBuilder: (_, __, ___) =>
                Icon(Icons.photo_camera, size: size * 0.45, color: Colors.white),
          ),
        );
      } else {
        inner = Icon(Icons.photo_camera, size: size * 0.45, color: Colors.white);
      }
      markers.add(Marker(
        point: LatLng(lat, lon),
        width: size,
        height: size,
        child: GestureDetector(
          onTap: () {
            widget.notifier.selectMemory(mem['id']);
            showMemoryDetail(context, widget.notifier, mem, readOnly: true);
          },
          child: Container(
            decoration: BoxDecoration(
              color: bgColor,
              shape: BoxShape.circle,
              border: isSelected ? Border.all(color: Colors.white, width: 2) : null,
            ),
            child: Center(child: inner),
          ),
        ),
      ));
    }
    return markers;
  }

  List<Marker> _buildJournalMarkers(
    List<Map<String, dynamic>> items,
    dynamic selectedJournalId,
    bool hasSelection,
    BuildContext context,
  ) {
    final markers = <Marker>[];
    for (final item in items) {
      if (item['item_type'] != 'journal') continue;
      final j = item['journal'] as Map<String, dynamic>?;
      if (j == null) continue;
      final lat = (j['lat'] as num?)?.toDouble();
      final lon = (j['lon'] as num?)?.toDouble();
      if (lat == null || lon == null) continue;
      final jId = j['id']?.toString() ?? '';
      final isSelected = selectedJournalId?.toString() == jId;
      const size = 22.0;
      final bgColor = isSelected
          ? const Color(0xFF44AAFF)
          : hasSelection
              ? const Color(0xA064748B)
              : const Color(0xFF64748B);
      markers.add(Marker(
        point: LatLng(lat, lon),
        width: size,
        height: size,
        child: GestureDetector(
          onTap: () => widget.notifier.selectJournal(j['id']),
          child: Container(
            decoration: BoxDecoration(
              color: bgColor,
              shape: BoxShape.circle,
              border: isSelected ? Border.all(color: Colors.white, width: 2) : null,
            ),
            child: const Center(
              child: Icon(Icons.book_outlined, size: 12, color: Colors.white),
            ),
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
      widget.mapController.animatedFitCamera(
        cameraFit: CameraFit.bounds(
          bounds: LatLngBounds(
            LatLng(minLat, minLon),
            LatLng(maxLat, maxLon),
          ),
          padding: const EdgeInsets.fromLTRB(32, 32, 32, 32 + 160),
        ),
        curve: Curves.easeInOut,
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
    // ── Activity + segment hit-test ──────────────────────────────────────────
    // Single pass over all GeoJSON features; pick the closest one within a
    // 15-pixel radius. Activity and segment hits both select their panel item.
    final geo = widget.notifier.geo;
    if (geo != null) {
      final zoom = widget.mapController.mapController.camera.zoom;
      final pixelDeg = 360.0 / (pow(2.0, zoom) * 256.0);
      final threshold = pow(15.0 * pixelDeg, 2).toDouble();
      double minHit = threshold;
      dynamic hitActivityId;
      String? hitSegmentId;

      final features = geo['features'];
      if (features is List) {
        for (final f in features) {
          if (f is! Map) continue;
          final props = f['properties'] as Map? ?? {};
          final type = props['type'] as String?;
          if (type != 'activity' && type != 'segment') continue;
          final coords = (f['geometry'] as Map? ?? {})['coordinates'];
          if (coords is! List) continue;
          for (final c in coords) {
            if (c is! List || c.length < 2) continue;
            final dLat = (c[1] as num).toDouble() - latlng.latitude;
            final dLon = (c[0] as num).toDouble() - latlng.longitude;
            final d = dLat * dLat + dLon * dLon;
            if (d < minHit) {
              minHit = d;
              if (type == 'activity') {
                hitActivityId = props['activity_id'];
                hitSegmentId = null;
              } else {
                hitSegmentId = props['segment_id']?.toString();
                hitActivityId = null;
              }
            }
          }
        }
      }

      if (hitActivityId != null) {
        widget.notifier.selectActivity(hitActivityId);
        return;
      }
      if (hitSegmentId != null) {
        widget.notifier.selectSegment(hitSegmentId);
        return;
      }
    }

    // ── Elevation cursor ─────────────────────────────────────────────────────
    final track = widget.notifier.fullTrack;
    if (track.isEmpty) return;
    int nearest = 0;
    double minDist = double.infinity;
    for (int i = 0; i < track.length; i++) {
      final dLat = track[i].$2.lat - latlng.latitude;
      final dLon = track[i].$2.lon - latlng.longitude;
      final d = dLat * dLat + dLon * dLon;
      if (d < minDist) { minDist = d; nearest = i; }
    }
    widget.notifier.elevationCursorNotifier.value = track[nearest].$2;
    widget.notifier.mapCursorDistNotifier.value   = track[nearest].$1;
  }

  @override
  Widget build(BuildContext context) {
    final notifier = widget.notifier;

    // Recompute polylines only when geo, selection, or track style changes.
    final geo = notifier.geo;
    final selActId = notifier.selectedActivityId;
    final selSegId = notifier.selectedSegmentId;
    final selMemId = notifier.selectedMemoryId;
    final selJournalId = notifier.selectedJournalId;
    final showJournals = notifier.showJournals;
    final items = notifier.items;
    final trackColor = notifier.trackColor;
    final trackSecondaryColor = notifier.trackSecondaryColor;
    final trackWidth = notifier.trackWidth;
    final alternating = notifier.alternatingTrackColors;
    final selectionChanged = selActId != _lastSelectedId ||
        selSegId?.toString() != _lastSelectedSegId?.toString() ||
        selMemId?.toString() != _lastSelectedMemId?.toString() ||
        selJournalId?.toString() != _lastSelectedJournalId?.toString();
    final styleChanged = trackColor != _lastTrackColor ||
        trackWidth != _lastTrackWidth || alternating != _lastAlternating;
    if (!identical(geo, _lastGeo) || selectionChanged || styleChanged ||
        !identical(items, _lastItems) || showJournals != _lastShowJournals) {
      _lastGeo = geo;
      _lastSelectedId = selActId;
      _lastSelectedSegId = selSegId;
      _lastSelectedMemId = selMemId;
      _lastSelectedJournalId = selJournalId;
      _lastItems = items;
      _lastTrackColor = trackColor;
      _lastTrackWidth = trackWidth;
      _lastAlternating = alternating;
      _lastShowJournals = showJournals;
      final tilesActive = widget.trackTileUrlTemplate != null;
      _cachedPolylines = geo != null
          ? _buildPolylines(geo, selActId, selSegId, trackColor, trackWidth,
              alternating, items,
              selectedOnly: tilesActive, trackSecondaryColor: trackSecondaryColor)
          : [];
      _cachedAllPoints = tilesActive && geo != null
          ? _allPointsFromGeo(geo)
          : _allPoints(_cachedPolylines);
      final hasSelection = selActId != null || selSegId != null ||
          selMemId != null || selJournalId != null;
      _cachedSegmentMarkers = geo != null
          ? _buildSegmentMarkers(geo, selSegId, hasSelection, trackColor)
          : [];
      _cachedMemoryMarkers =
          _buildMemoryMarkers(items, selMemId, hasSelection, context);
      _cachedJournalMarkers =
          _buildJournalMarkers(items, selJournalId, hasSelection, context);
      // Only re-fit when the selection changes (user picks a different
      // activity/segment). A geo update from progressive track loading
      // should never reset the viewport the user has already panned/zoomed.
      if (selectionChanged) _fittedBounds = false;
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
          mapController: widget.mapController.mapController,
          options: MapOptions(
            initialCenter: const LatLng(0, 0),
            initialZoom: 2,
            interactionOptions: const InteractionOptions(
              flags: InteractiveFlag.all & ~InteractiveFlag.rotate,
            ),
            onTap: (_, latlng) => _onMapTap(latlng),
          ),
          children: [
            if (_vectorStyle != null)
              VectorTileLayer(
                tileProviders: _vectorStyle!.providers,
                theme: _vectorStyle!.theme,
                sprites: _vectorStyle!.sprites,
                tileOffset: TileOffset.mapbox,
                layerMode: VectorTileLayerMode.vector,
                maximumZoom: 22,
              )
            else if (_tileProvider != null) ...[
              TileLayer(
                urlTemplate: widget.basemapUrl,
                subdomains: widget.basemapSubdomains,
                userAgentPackageName: 'com.viewtrip.client',
                tileProvider: _tileProvider!,
                maxNativeZoom: 22,
                retinaMode: RetinaMode.isHighDensity(context),
              ),
              if (widget.labelsUrl != null)
                ColorFiltered(
                  colorFilter: ColorFilter.matrix(<double>[
                    1, 0, 0, 0, 0,
                    0, 1, 0, 0, 0,
                    0, 0, 1, 0, 0,
                    0, 0, 0, 0.5, 0,
                  ]),
                  child: TileLayer(
                    urlTemplate: widget.labelsUrl!,
                    subdomains: kActiveViewLabelsSubdomains,
                    userAgentPackageName: 'com.viewtrip.client',
                    tileProvider: _tileProvider!,
                    maxNativeZoom: 22,
                  ),
                ),
            ],
            if (widget.trackTileUrlTemplate != null)
              TileLayer(
                urlTemplate: widget.trackTileUrlTemplate!,
                userAgentPackageName: 'com.viewtrip.client',
                maxNativeZoom: 15,
              ),
            if (polylines.isNotEmpty)
              PolylineLayer(
                polylines: polylines,
                // Reduce GPU path vertices at low zoom — detail preserved when zoomed in.
                simplificationTolerance: 0.5,
              ),
            if (_cachedSegmentMarkers.isNotEmpty)
              MarkerLayer(markers: _cachedSegmentMarkers),
            if (_showMemories && _cachedMemoryMarkers.isNotEmpty)
              MarkerLayer(markers: _cachedMemoryMarkers),
            if (notifier.showJournals && _cachedJournalMarkers.isNotEmpty)
              MarkerLayer(markers: _cachedJournalMarkers),
            // Preview arc uses ValueListenableBuilder so only this layer rebuilds
            // when the segment dialog updates coordinates — not the whole map.
            ValueListenableBuilder<List<GeoPoint>?>(
              valueListenable: notifier.previewArcNotifier,
              builder: (_, arc, __) {
                if (arc == null) return const SizedBox.shrink();
                return PolylineLayer(
                  polylines: [
                    Polyline(
                      points: arc.map(_ll).toList(),
                      color: const Color(0xCC6366F1),
                      strokeWidth: 2.5,
                    ),
                  ],
                );
              },
            ),
            // Elevation cursor — driven by chart hover/tap and by map taps.
            ValueListenableBuilder<GeoPoint?>(
              valueListenable: notifier.elevationCursorNotifier,
              builder: (_, cursor, __) {
                if (cursor == null) return const SizedBox.shrink();
                return MarkerLayer(
                  markers: [
                    Marker(
                      point: _ll(cursor),
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
        if (_cachedMemoryMarkers.isNotEmpty)
          Positioned(
            top: 12,
            left: 12,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  'Memories',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Colors.white,
                  ),
                ),
                Transform.scale(
                  scale: 0.7, // Adjust this value to set the size
                  child: Switch(
                    value: _showMemories,
                    onChanged: (v) => setState(() => _showMemories = v),
                    materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

// ── ManageMapPanel — bare TileLayer, no controller, no polylines ─────────────

class ManageMapPanel extends StatefulWidget {
  final ProjectNotifier notifier;
  final AnimatedMapController mapController;
  final bool autoZoom;
  final String basemapUrl;
  final List<String> basemapSubdomains;
  final ValueNotifier<bool> fittedNotifier;
  /// Mapbox vector style URI. When set, a VectorTileLayer replaces the raster TileLayer.
  final String? basemapStyleUri;

  const ManageMapPanel({
    super.key,
    required this.notifier,
    required this.mapController,
    required this.basemapUrl,
    required this.fittedNotifier,
    this.autoZoom = false,
    this.basemapSubdomains = const [],
    this.basemapStyleUri,
  });

  @override
  State<ManageMapPanel> createState() => ManageMapPanelState();
}

class ManageMapPanelState extends State<ManageMapPanel> {
  NetworkTileProvider? _tileProvider;
  Style? _vectorStyle;

  // Polyline + marker cache — only rebuilt when geo or selection changes.
  Map<String, dynamic>? _lastGeo;
  dynamic _lastSelectedId = _sentinel;
  dynamic _lastSelectedSegId = _sentinel;
  String? _lastSelectedDay = '';   // '' = sentinel (distinct from null)
  Set<String> _lastSelectedDays = const {};
  dynamic _lastSelectedMemId = _sentinel;
  dynamic _lastSelectedJournalId = _sentinel;
  List<Map<String, dynamic>>? _lastItems;
  List<Polyline> _cachedPolylines = [];
  List<Marker> _cachedSegmentMarkers = [];
  List<Marker> _cachedMemoryMarkers = [];
  List<Marker> _cachedJournalMarkers = [];
  bool _showMemories = true;
  // Points queued for auto-zoom on the next frame; null = nothing pending.
  List<LatLng>? _pendingAutoZoomPts;
  // Track-style cache fields.
  Color? _lastTrackColor;
  double? _lastTrackWidth;
  bool? _lastAlternating;
  bool? _lastShowJournals;

  static const _sentinel = Object();

  static bool setEquals(Set<String> a, Set<String> b) =>
      a.length == b.length && a.containsAll(b);

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
    Color trackColor,
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
          ? trackColor
          : hasSelection
              ? trackColor.withAlpha(0x60)
              : trackColor;

      markers.add(Marker(
        point: point,
        width: 22,
        height: 22,
        child: Container(
          decoration: BoxDecoration(color: bgColor, shape: BoxShape.circle),
          child: Icon(
            _iconForSegmentType(
              (props['segment_type'] as String?) ??
              (props['route_mode'] == 'rail' ? 'train' : null),
            ),
            color: Colors.white,
            size: 13,
          ),
        ),
      ));
    }
    return markers;
  }

  List<Marker> _buildMemoryMarkers(
    List<Map<String, dynamic>> items,
    dynamic selectedMemoryId,
    bool hasSelection,
    BuildContext context,
  ) {
    final markers = <Marker>[];
    final authHeaders = widget.notifier.photoAuthHeaders;
    for (final item in items) {
      if (item['item_type'] != 'memory') continue;
      final mem = item['memory'] as Map<String, dynamic>?;
      if (mem == null) continue;
      final lat = (mem['lat'] as num?)?.toDouble();
      final lon = (mem['lon'] as num?)?.toDouble();
      if (lat == null || lon == null) continue;
      final memId = mem['id']?.toString() ?? '';
      final photos = (mem['photos'] as List?)?.cast<String>() ?? [];
      final isSelected = selectedMemoryId?.toString() == memId;
      final size = isSelected ? 34.0 : 28.0;
      final bgColor = isSelected
          ? const Color(0xFFEA580C)
          : hasSelection
              ? const Color(0xA0F97316)
              : const Color(0xFFF97316);

      Widget inner;
      if (photos.isNotEmpty) {
        final thumbUrl = widget.notifier.photoThumbUrl(memId, photos.first);
        inner = ClipOval(
          child: Image.network(
            thumbUrl,
            width: size,
            height: size,
            fit: BoxFit.cover,
            headers: authHeaders,
            errorBuilder: (_, __, ___) => Icon(Icons.photo_camera,
                size: size * 0.45, color: Colors.white),
          ),
        );
      } else {
        inner = Icon(Icons.photo_camera, size: size * 0.45, color: Colors.white);
      }

      markers.add(Marker(
        point: LatLng(lat, lon),
        width: size,
        height: size,
        child: GestureDetector(
          onTap: () {
            widget.notifier.selectMemory(mem['id']);
            showMemoryDetail(context, widget.notifier, mem);
          },
          child: Container(
            decoration: BoxDecoration(
              color: bgColor,
              shape: BoxShape.circle,
              border: isSelected
                  ? Border.all(color: Colors.white, width: 2)
                  : null,
            ),
            child: Center(child: inner),
          ),
        ),
      ));
    }
    return markers;
  }

  List<Marker> _buildJournalMarkers(
    List<Map<String, dynamic>> items,
    dynamic selectedJournalId,
    bool hasSelection,
    BuildContext context,
  ) {
    final markers = <Marker>[];
    for (final item in items) {
      if (item['item_type'] != 'journal') continue;
      final j = item['journal'] as Map<String, dynamic>?;
      if (j == null) continue;
      final lat = (j['lat'] as num?)?.toDouble();
      final lon = (j['lon'] as num?)?.toDouble();
      if (lat == null || lon == null) continue;
      final jId = j['id']?.toString() ?? '';
      final isSelected = selectedJournalId?.toString() == jId;
      const size = 22.0;
      final bgColor = isSelected
          ? const Color(0xFF44AAFF)
          : hasSelection
              ? const Color(0xA064748B)
              : const Color(0xFF64748B);
      markers.add(Marker(
        point: LatLng(lat, lon),
        width: size,
        height: size,
        child: GestureDetector(
          onTap: () => widget.notifier.selectJournal(j['id']),
          child: Container(
            decoration: BoxDecoration(
              color: bgColor,
              shape: BoxShape.circle,
              border: isSelected ? Border.all(color: Colors.white, width: 2) : null,
            ),
            child: const Center(
              child: Icon(Icons.book_outlined, size: 12, color: Colors.white),
            ),
          ),
        ),
      ));
    }
    return markers;
  }

  @override
  void initState() {
    super.initState();
    if (widget.basemapStyleUri != null) {
      () async {
        try {
          final s = await StyleReader(
                  uri: widget.basemapStyleUri!,
                  apiKey: kMapboxToken)
              .read();
          if (!mounted) return;
          setState(() => _vectorStyle = s);
        } catch (e) {
          debugPrint('[ManageMapPanel] StyleReader error: $e');
        }
      }();
    } else {
      _tileProvider = NetworkTileProvider();
    }
    // Initialise "last" selection state from the current notifier values so that
    // a spurious selectionChanged2=true (which resets the fit flag) is never
    // triggered when this state is (re)created while a fit has already happened.
    _lastSelectedId = widget.notifier.selectedActivityId;
    _lastSelectedSegId = widget.notifier.selectedSegmentId;
    _lastSelectedDay = widget.notifier.selectedDay;
    _lastSelectedDays = Set.from(widget.notifier.selectedDays);
    _lastSelectedMemId = widget.notifier.selectedMemoryId;
  }

  @override
  void dispose() {
    super.dispose();
  }

  void _fitBoundsOnce(List<LatLng> points) {
    if (widget.fittedNotifier.value || points.isEmpty) return;
    widget.fittedNotifier.value = true;
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
      widget.mapController.animatedFitCamera(
        cameraFit: CameraFit.bounds(
          bounds: LatLngBounds(LatLng(minLat, minLon), LatLng(maxLat, maxLon)),
          padding: const EdgeInsets.fromLTRB(32, 32, 32, 32 + 160),
        ),
        curve: Curves.easeInOut,
      );
    });
  }

  void _onMapTap(LatLng latlng) {
    // ── Activity + segment hit-test ──────────────────────────────────────────
    final geo = widget.notifier.geo;
    if (geo != null) {
      final zoom = widget.mapController.mapController.camera.zoom;
      final pixelDeg = 360.0 / (pow(2.0, zoom) * 256.0);
      final threshold = pow(15.0 * pixelDeg, 2).toDouble();
      double minHit = threshold;
      dynamic hitActivityId;
      String? hitSegmentId;

      final features = geo['features'];
      if (features is List) {
        for (final f in features) {
          if (f is! Map) continue;
          final props = f['properties'] as Map? ?? {};
          final type = props['type'] as String?;
          if (type != 'activity' && type != 'segment') continue;
          final coords = (f['geometry'] as Map? ?? {})['coordinates'];
          if (coords is! List) continue;
          for (final c in coords) {
            if (c is! List || c.length < 2) continue;
            final dLat = (c[1] as num).toDouble() - latlng.latitude;
            final dLon = (c[0] as num).toDouble() - latlng.longitude;
            final d = dLat * dLat + dLon * dLon;
            if (d < minHit) {
              minHit = d;
              if (type == 'activity') {
                hitActivityId = props['activity_id'];
                hitSegmentId = null;
              } else {
                hitSegmentId = props['segment_id']?.toString();
                hitActivityId = null;
              }
            }
          }
        }
      }

      if (hitActivityId != null) {
        widget.notifier.selectActivity(hitActivityId);
        return;
      }
      if (hitSegmentId != null) {
        widget.notifier.selectSegment(hitSegmentId);
        return;
      }
    }

    // ── Elevation cursor ─────────────────────────────────────────────────────
    final track = widget.notifier.fullTrack;
    if (track.isEmpty) return;
    int nearest = 0;
    double minDist = double.infinity;
    for (int i = 0; i < track.length; i++) {
      final dLat = track[i].$2.lat - latlng.latitude;
      final dLon = track[i].$2.lon - latlng.longitude;
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

  List<LatLng> _extractSelectedPoints(
    Map<String, dynamic> geo,
    dynamic selActId,
    dynamic selSegId,
    Set<String>? dayActIds,
    Set<String>? daySegIds,
  ) {
    final points = <LatLng>[];
    final features = geo['features'];
    if (features is! List) return points;
    for (final feature in features) {
      if (feature is! Map) continue;
      final props = feature['properties'] as Map? ?? {};
      final isSegment = props['type'] == 'segment';
      final featureId = isSegment
          ? props['segment_id']?.toString()
          : props['activity_id']?.toString();
      final bool match;
      if (dayActIds != null || daySegIds != null) {
        match = isSegment
            ? (daySegIds?.contains(featureId) ?? false)
            : (dayActIds?.contains(featureId) ?? false);
      } else if (isSegment) {
        match = selSegId != null && featureId == selSegId.toString();
      } else {
        match = selActId != null && featureId == selActId.toString();
      }
      if (!match) continue;
      final coords = (feature['geometry'] as Map? ?? {})['coordinates'];
      if (coords is! List) continue;
      for (final c in coords) {
        if (c is List && c.length >= 2) {
          points.add(LatLng((c[1] as num).toDouble(), (c[0] as num).toDouble()));
        }
      }
    }
    return points;
  }

  List<Polyline> _buildPolylines(
    Map<String, dynamic> geo,
    dynamic selectedActivityId,
    dynamic selectedSegmentId,
    Set<String> effectiveDays,
    Map<dynamic, Map<String, dynamic>> activityById,
    List<Map<String, dynamic>> items,
    Color trackColor,
    double trackWidth,
    bool alternating, {
    Color? trackSecondaryColor,
  }) {
    final features = geo['features'];
    if (features is! List) return [];

    // Build activity-index map for alternating colours.
    final actIdx = <String, int>{};
    int ai = 0;
    for (final item in items) {
      if (item['item_type'] == 'activity') {
        final id = item['activity_id']?.toString();
        if (id != null) actIdx[id] = ai++;
      }
    }
    final altColor = trackSecondaryColor ?? _MapPanelState._alternateColor(trackColor);

    // For day selection, union ids across all selected days.
    Set<String>? dayActIds;
    Set<String>? daySegIds;
    if (effectiveDays.isNotEmpty) {
      dayActIds = {};
      daySegIds = {};
      for (final dk in effectiveDays) {
        final r = _dayItemIds(items, activityById, dk);
        dayActIds.addAll(r.actIds);
        daySegIds.addAll(r.segIds);
      }
    }

    final polylines = <Polyline>[];
    final hasSelection = selectedActivityId != null ||
        selectedSegmentId != null ||
        effectiveDays.isNotEmpty;
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
      if (effectiveDays.isNotEmpty) {
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

      final isOdd = alternating && !isSegment && featureId != null &&
          (actIdx[featureId] ?? 0).isOdd;

      final Color color;
      final double strokeWidth;
      if (isSegment) {
        if (isHighlighted) {
          color = trackColor;
          strokeWidth = 4.0;
        } else if (hasSelection) {
          color = trackColor.withAlpha(0x60);
          strokeWidth = 2.0;
        } else {
          color = trackColor;
          strokeWidth = 2.0;
        }
      } else {
        if (isHighlighted) {
          color = trackColor;
          strokeWidth = (trackWidth * 1.9).clamp(4.0, 8.0);
        } else if (hasSelection) {
          color = trackColor.withAlpha(0x60);
          strokeWidth = trackWidth;
        } else {
          color = isOdd ? altColor : trackColor;
          strokeWidth = trackWidth;
        }
      }
      polylines.add(Polyline(
        points: points,
        color: color,
        strokeWidth: strokeWidth,
        pattern: isSegment
            ? StrokePattern.dashed(segments: const [12, 8])
            : const StrokePattern.solid(),
      ));
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
    final selDays = notifier.selectedDays;
    final selMemId = notifier.selectedMemoryId;
    final selJournalId2 = notifier.selectedJournalId;
    final showJournals2 = notifier.showJournals;
    final items = notifier.items;
    final trackColor = notifier.trackColor;
    final trackSecondaryColor2 = notifier.trackSecondaryColor;
    final trackWidth = notifier.trackWidth;
    final alternating = notifier.alternatingTrackColors;
    final selectionChanged2 = selActId != _lastSelectedId ||
        selSegId?.toString() != _lastSelectedSegId?.toString() ||
        selDay != _lastSelectedDay ||
        !setEquals(selDays, _lastSelectedDays) ||
        selMemId?.toString() != (_lastSelectedMemId as dynamic)?.toString() ||
        selJournalId2?.toString() != _lastSelectedJournalId?.toString();
    final styleChanged2 = trackColor != _lastTrackColor ||
        trackWidth != _lastTrackWidth || alternating != _lastAlternating;
    if (!identical(geo, _lastGeo) || selectionChanged2 ||
        !identical(items, _lastItems) || styleChanged2 ||
        showJournals2 != _lastShowJournals) {
      if (selectionChanged2) widget.fittedNotifier.value = false;
      _lastGeo = geo;
      _lastSelectedId = selActId;
      _lastSelectedSegId = selSegId;
      _lastSelectedDay = selDay;
      _lastSelectedDays = Set.from(selDays);
      _lastSelectedMemId = selMemId;
      _lastSelectedJournalId = selJournalId2;
      _lastItems = items;
      _lastTrackColor = trackColor;
      _lastTrackWidth = trackWidth;
      _lastAlternating = alternating;
      _lastShowJournals = showJournals2;
      // Multi-select takes priority over single-day selection.
      final effectiveDays = selDays.isNotEmpty
          ? selDays
          : (selDay != null ? {selDay} : <String>{});
      // Build activityById for day-selection polyline colouring.
      final actById = <dynamic, Map<String, dynamic>>{
        for (final a in notifier.activities) a['id']: a
      };
      _cachedPolylines = geo != null
          ? _buildPolylines(geo, selActId, selSegId, effectiveDays, actById,
              items, trackColor, trackWidth, alternating,
              trackSecondaryColor: trackSecondaryColor2)
          : [];
      final hasSelection = selActId != null || selSegId != null ||
          effectiveDays.isNotEmpty || selMemId != null || selJournalId2 != null;
      _cachedSegmentMarkers = geo != null
          ? _buildSegmentMarkers(geo, selSegId, hasSelection, trackColor)
          : [];
      _cachedMemoryMarkers =
          _buildMemoryMarkers(items, selMemId, hasSelection, context);
      _cachedJournalMarkers =
          _buildJournalMarkers(items, selJournalId2, hasSelection, context);

      // Queue auto-zoom only when selection genuinely changed (not on geo updates
      // from progressive loading) so it doesn't fight _fitBoundsOnce mid-load.
      if (selectionChanged2 && widget.autoZoom && geo != null &&
          (effectiveDays.isNotEmpty || selActId != null || selSegId != null)) {
        Set<String>? dayActIds;
        Set<String>? daySegIds;
        if (effectiveDays.isNotEmpty) {
          dayActIds = {};
          daySegIds = {};
          for (final dk in effectiveDays) {
            final r = _dayItemIds(items, actById, dk);
            dayActIds.addAll(r.actIds);
            daySegIds.addAll(r.segIds);
          }
        }
        _pendingAutoZoomPts = _extractSelectedPoints(
            geo, selActId, selSegId, dayActIds, daySegIds);
      } else if (selectionChanged2) {
        _pendingAutoZoomPts = null;
      }
    }

    if (!notifier.isLoading) {
      _fitBoundsOnce(_cachedPolylines.expand((p) => p.points).toList());
    }

    // Schedule auto-zoom AFTER _fitBoundsOnce so its postFrameCallback runs
    // last and takes priority over the whole-track fit.
    final pendingPts = _pendingAutoZoomPts;
    if (pendingPts != null && pendingPts.isNotEmpty) {
      _pendingAutoZoomPts = null;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        double minLat = pendingPts.first.latitude, maxLat = pendingPts.first.latitude;
        double minLon = pendingPts.first.longitude, maxLon = pendingPts.first.longitude;
        for (final p in pendingPts) {
          if (p.latitude < minLat) minLat = p.latitude;
          if (p.latitude > maxLat) maxLat = p.latitude;
          if (p.longitude < minLon) minLon = p.longitude;
          if (p.longitude > maxLon) maxLon = p.longitude;
        }
        widget.mapController.animatedFitCamera(
          cameraFit: CameraFit.bounds(
            bounds: LatLngBounds(
                LatLng(minLat, minLon), LatLng(maxLat, maxLon)),
            padding: const EdgeInsets.fromLTRB(48, 48, 48, 48 + 160),
          ),
          curve: Curves.easeInOut,
        );
      });
    }

    return Stack(
      children: [
        FlutterMap(
          mapController: widget.mapController.mapController,
          options: MapOptions(
            initialCenter: const LatLng(48.0, 10.0),
            initialZoom: 4,
            interactionOptions: const InteractionOptions(
              flags: InteractiveFlag.all & ~InteractiveFlag.rotate,
            ),
            onTap: (_, latlng) => _onMapTap(latlng),
          ),
          children: [
            if (_vectorStyle != null)
              VectorTileLayer(
                tileProviders: _vectorStyle!.providers,
                theme: _vectorStyle!.theme,
                sprites: _vectorStyle!.sprites,
                tileOffset: TileOffset.mapbox,
                layerMode: VectorTileLayerMode.vector,
                maximumZoom: 22,
              )
            else if (_tileProvider != null)
              TileLayer(
                urlTemplate: widget.basemapUrl,
                subdomains: widget.basemapSubdomains,
                userAgentPackageName: 'com.viewtrip.client',
                tileProvider: _tileProvider!,
                maxNativeZoom: 22,
              ),
            if (_cachedPolylines.isNotEmpty)
              PolylineLayer(
                polylines: _cachedPolylines,
                simplificationTolerance: 0.5,
              ),
            if (_cachedSegmentMarkers.isNotEmpty)
              MarkerLayer(markers: _cachedSegmentMarkers),
            if (_showMemories && _cachedMemoryMarkers.isNotEmpty)
              MarkerLayer(markers: _cachedMemoryMarkers),
            if (notifier.showJournals && _cachedJournalMarkers.isNotEmpty)
              MarkerLayer(markers: _cachedJournalMarkers),
            ValueListenableBuilder<List<GeoPoint>?>(
              valueListenable: notifier.previewArcNotifier,
              builder: (_, arc, __) {
                if (arc == null) return const SizedBox.shrink();
                return PolylineLayer(
                  polylines: [
                    Polyline(
                      points: arc.map(_ll).toList(),
                      color: const Color(0xCC6366F1),
                      strokeWidth: 2.5,
                    ),
                  ],
                );
              },
            ),
            ValueListenableBuilder<GeoPoint?>(
              valueListenable: notifier.elevationCursorNotifier,
              builder: (_, cursor, __) {
                if (cursor == null) return const SizedBox.shrink();
                return MarkerLayer(
                  markers: [
                    Marker(
                      point: _ll(cursor),
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
        if (_cachedMemoryMarkers.isNotEmpty)
          Positioned(
            top: 12,
            left: 12,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  'Memories',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Colors.white,
                  ),
                ),
                Transform.scale(
                  scale: 0.7,
                  child: Switch(
                    value: _showMemories,
                    onChanged: (v) => setState(() => _showMemories = v),
                    materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

// ── _StatChip ─────────────────────────────────────────────────────────────────

// ── MobileActivityPanelOverlay ───────────────────────────────────────────────
// Slide-in activity panel for narrow (mobile) layout. Rendered as a Material
// surface with elevation so it casts a shadow over the map behind it.

class MobileActivityPanelOverlay extends StatelessWidget {
  final ProjectNotifier notifier;
  final AnimatedMapController mapController;
  final double height;

  const MobileActivityPanelOverlay({
    super.key,
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
