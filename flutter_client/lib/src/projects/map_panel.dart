library;

import 'dart:math' show pow;
import 'dart:ui' as ui show Path, PathFillType;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_map_animations/flutter_map_animations.dart';
import 'package:latlong2/latlong.dart';
import 'package:vector_map_tiles/vector_map_tiles.dart';

import '../core/design_tokens.dart' show kAccent, kShadow2, monoStyle;
import '../core/perf_timing.dart' show kPerfTiming;
import '../map/geo_point.dart';
import 'activity_panel.dart';
import 'basemaps.dart';
import 'memory_detail_modal.dart';
import 'people_screen.dart' show showGroupDetailSheet, showPersonDetailSheet;
import 'people_search.dart' show classifyEncounterPin;
import 'project_notifier.dart';
LatLng _ll(GeoPoint p) => LatLng(p.lat, p.lon);

/// Returns the coordinate at 50% of the total chord length — accurate even
/// when points are unevenly spaced (e.g. resolved rail/ferry/bus routes).
LatLng? _arcMidpoint(List coords) {
  if (coords.isEmpty) return null;
  if (coords.length == 1) {
    final c = coords[0];
    if (c is! List || c.length < 2) return null;
    return LatLng((c[1] as num).toDouble(), (c[0] as num).toDouble());
  }
  double total = 0;
  final lens = <double>[0.0];
  for (int i = 1; i < coords.length; i++) {
    final a = coords[i - 1], b = coords[i];
    if (a is! List || b is! List || a.length < 2 || b.length < 2) {
      lens.add(total);
      continue;
    }
    final dlat = (b[1] as num).toDouble() - (a[1] as num).toDouble();
    final dlon = (b[0] as num).toDouble() - (a[0] as num).toDouble();
    total += pow(dlat * dlat + dlon * dlon, 0.5);
    lens.add(total);
  }
  final half = total / 2;
  for (int i = 1; i < lens.length; i++) {
    if (lens[i] >= half) {
      final t = (lens[i] - lens[i - 1]) == 0
          ? 0.0
          : (half - lens[i - 1]) / (lens[i] - lens[i - 1]);
      final a = coords[i - 1], b = coords[i];
      if (a is! List || b is! List || a.length < 2 || b.length < 2) break;
      return LatLng(
        (a[1] as num).toDouble() + t * ((b[1] as num).toDouble() - (a[1] as num).toDouble()),
        (a[0] as num).toDouble() + t * ((b[0] as num).toDouble() - (a[0] as num).toDouble()),
      );
    }
  }
  final last = coords.last;
  if (last is! List || last.length < 2) return null;
  return LatLng((last[1] as num).toDouble(), (last[0] as num).toDouble());
}

IconData _iconForActivityType(String? type) => switch (type?.toLowerCase()) {
  'run' || 'virtualrun'                  => Icons.directions_run,
  'ride' || 'virtualride' || 'ebikeride' => Icons.directions_bike,
  'hike' || 'walk'                       => Icons.hiking,
  _                                      => Icons.map_outlined,
};

// Start (green) / end (red) markers for the selected activity (issue #19).
const Color _kStartMarkerColor = Color(0xFF22C55E); // green-500
const Color _kEndMarkerColor   = Color(0xFFEF4444); // red-500

// Focused-location marker (issue #72) — tapping an encounter's place icon
// zooms in and drops this pin, distinct from the (red) encounter pins.
const Color _kFocusMarkerColor = Color(0xFFF59E0B); // amber-500

/// A single highlighted pin at [point] — rendered by both map widgets when
/// [MapPanel.focusedLatLng] / [ManageMapPanel.focusedLatLng] is set (issue #72).
Marker focusedLocationMarker(LatLng point) => Marker(
      point: point,
      width: 30,
      height: 30,
      alignment: Alignment.center,
      child: Container(
        decoration: BoxDecoration(
          color: _kFocusMarkerColor,
          shape: BoxShape.circle,
          border: Border.all(color: Colors.white, width: 3),
        ),
        child: const Icon(Icons.place, size: 16, color: Colors.white),
      ),
    );

// "You are here" marker (issue #88) — dropped by the locate-me button, a
// plain dot (no icon glyph) so it's visually distinct from the amber
// focused-location pin above and from the locate-me button itself, which
// both use icon-in-circle styling.
const Color _kHereMarkerColor = Color(0xFF2563EB); // blue-600

/// The device-location pin dropped by the locate-me button (issue #88),
/// rendered by both map widgets when [MapPanel.hereLatLng] /
/// [ManageMapPanel.hereLatLng] is set.
Marker youAreHereMarker(LatLng point) => Marker(
      point: point,
      width: 20,
      height: 20,
      alignment: Alignment.center,
      child: Container(
        decoration: BoxDecoration(
          color: _kHereMarkerColor,
          shape: BoxShape.circle,
          border: Border.all(color: Colors.white, width: 3),
        ),
      ),
    );

/// Locate-me button (issue #88) — overlaid on the map, shared by [MapPanel]
/// and [ManageMapPanel]. Purely presentational: the async device-location
/// fetch and camera pan are owned by the parent screen (mirrors how
/// [focusedLocationMarker] taps bubble up via `onLocationTap` instead of
/// being handled inside this file), so this widget just renders the button
/// and reports taps via [onPressed].
class LocateMeButton extends StatelessWidget {
  final bool locating;
  final VoidCallback onPressed;

  const LocateMeButton({super.key, required this.locating, required this.onPressed});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Material(
      color: cs.surface.withValues(alpha: 0.94),
      shape: const CircleBorder(),
      elevation: 0,
      child: Container(
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          boxShadow: kShadow2(Theme.of(context).brightness),
        ),
        child: IconButton(
          icon: locating
              ? SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(
                      strokeWidth: 2, color: cs.onSurfaceVariant),
                )
              : Icon(Icons.my_location, color: cs.onSurfaceVariant),
          tooltip: 'Center on my location',
          onPressed: locating ? null : onPressed,
        ),
      ),
    );
  }
}

LatLng? _coordToLatLng(dynamic c) {
  if (c is! List || c.length < 2) return null;
  return LatLng((c[1] as num).toDouble(), (c[0] as num).toDouble());
}

// ── Per-feature geometry memoization ─────────────────────────────────────────
//
// The map rebuilds whenever `geo` is reassigned (notably the progressive
// low-res→full-res upgrade on load). Reconstructing markers/polylines re-ran the
// O(track-points) work — converting every coordinate to LatLng and recomputing
// each activity's arc-midpoint — for *every* feature on *every* rebuild, which
// dominated the build-thread cost and produced the load-time map jank.
//
// These memoize that work keyed by the *identity* of the raw coordinates list.
// Only changed features get a new coords list (the upgrade replaces just the
// upgraded activities), so unchanged features hit the cache — "rebuild only
// changed features" without any signature/invalidation bookkeeping: the selection
// /style-dependent bits (colour, dimming) are cheap and stay recomputed, and
// entries auto-evict when their coords list is GC'd (Expando). Returned point
// lists are shared — callers must treat them as read-only.
final Expando<List<LatLng>> _coordsLatLngCache = Expando('coordsLatLng');
final Expando<LatLng> _arcMidpointCache = Expando('arcMidpoint');

@visibleForTesting
List<LatLng> memoCoordsToLatLng(List coords) {
  final cached = _coordsLatLngCache[coords];
  if (cached != null) return cached;
  final pts = <LatLng>[];
  for (final c in coords) {
    if (c is List && c.length >= 2) {
      pts.add(LatLng((c[1] as num).toDouble(), (c[0] as num).toDouble()));
    }
  }
  _coordsLatLngCache[coords] = pts;
  return pts;
}

@visibleForTesting
LatLng? memoArcMidpoint(List coords) {
  final cached = _arcMidpointCache[coords];
  if (cached != null) return cached;
  final m = _arcMidpoint(coords);
  if (m != null) _arcMidpointCache[coords] = m;
  return m;
}

/// Activity ids that begin a new day, in trip order: the first dated activity
/// of each distinct consecutive `start_date_local` date. Used to drop a day
/// breakpoint node at the start of each day on the map so days are visually
/// separable (issue #19). Non-activity items and dateless activities are
/// ignored; mirrors the activity panel's day-grouping (only activities advance
/// the running date).
Set<String> dayStartActivityIds(
  List<Map<String, dynamic>> items,
  Map<dynamic, Map<String, dynamic>> activityById,
) {
  final starts = <String>{};
  String? lastDate;
  for (final item in items) {
    if (item['item_type'] != 'activity') continue;
    final actId = item['activity_id'];
    final date =
        (activityById[actId]?['start_date_local'] as String?)?.split('T').first;
    if (date == null) continue;
    if (date != lastDate) {
      final id = actId?.toString();
      if (id != null) starts.add(id);
      lastDate = date;
    }
  }
  return starts;
}

/// A solid coloured disc with a white ring — used for the selected activity's
/// start (green) / end (red) markers so they read on any basemap.
Marker _dotMarker(LatLng point, Color color, {double size = 16}) => Marker(
      point: point,
      width: size,
      height: size,
      alignment: Alignment.center,
      child: Container(
        decoration: BoxDecoration(
          color: color,
          shape: BoxShape.circle,
          border: Border.all(color: Colors.white, width: 2),
        ),
      ),
    );

/// A white "bead" with a thick coloured ring — the day breakpoint node. The
/// inverse fill (vs the solid sport-icon markers) makes it read as a joint that
/// breaks the line between days rather than another activity marker (#19).
Marker _dayNodeMarker(LatLng point, Color ringColor, {double size = 15}) =>
    Marker(
      point: point,
      width: size,
      height: size,
      alignment: Alignment.center,
      child: Container(
        decoration: BoxDecoration(
          color: Colors.white,
          shape: BoxShape.circle,
          border: Border.all(color: ringColor, width: 3),
        ),
      ),
    );

/// Day breakpoint node markers for [geo] (#19): one bead at the start of each
/// day-start activity (see [dayStartActivityIds]). Shared by the live map and
/// the image export so both render days the same way. [ringColor] should match
/// the colour the track line is drawn with in that context.
List<Marker> buildDayBreakpointMarkers(
  Map<String, dynamic> geo,
  Set<String> dayStartIds,
  Color ringColor,
) {
  if (dayStartIds.isEmpty) return const [];
  final features = geo['features'];
  if (features is! List) return const [];
  final markers = <Marker>[];
  for (final feature in features) {
    if (feature is! Map) continue;
    final props = feature['properties'] as Map? ?? {};
    if (props['type'] != 'activity') continue;
    final actId = props['activity_id']?.toString();
    if (actId == null || !dayStartIds.contains(actId)) continue;
    final coords = (feature['geometry'] as Map? ?? {})['coordinates'];
    if (coords is! List || coords.isEmpty) continue;
    final start = _coordToLatLng(coords.first);
    if (start != null) markers.add(_dayNodeMarker(start, ringColor));
  }
  return markers;
}

List<Marker> _buildActivityMarkersFromGeo(
  Map<String, dynamic> geo,
  dynamic selectedActivityId,
  bool hasSelection,
  Color trackColor, {
  Set<String> dayStartActivityIds = const {},
}) {
  final features = geo['features'];
  if (features is! List) return const [];
  final markers = <Marker>[];
  for (final feature in features) {
    if (feature is! Map) continue;
    final props = feature['properties'] as Map? ?? {};
    if (props['type'] != 'activity') continue;
    final coords = (feature['geometry'] as Map? ?? {})['coordinates'];
    if (coords is! List || coords.length < 2) continue;

    final point = memoArcMidpoint(coords);
    if (point == null) continue;

    final actId = props['activity_id']?.toString();
    final sportType = props['sport_type'] as String?;
    final isSelected = selectedActivityId != null &&
        actId == selectedActivityId.toString();

    final bgColor = isSelected
        ? trackColor
        : hasSelection
            ? trackColor.withAlpha(0x60)
            : trackColor;

    markers.add(Marker(
      point: point,
      width: 22,
      height: 22,
      alignment: Alignment.center,
      child: Container(
        decoration: BoxDecoration(color: bgColor, shape: BoxShape.circle),
        child: Icon(_iconForActivityType(sportType), color: Colors.white, size: 13),
      ),
    ));

    // Start (green) / end (red) markers for the selected activity (#19).
    if (isSelected) {
      final start = _coordToLatLng(coords.first);
      final end = _coordToLatLng(coords.last);
      if (start != null) markers.add(_dotMarker(start, _kStartMarkerColor, size: 18));
      if (end != null) markers.add(_dotMarker(end, _kEndMarkerColor, size: 18));
    }
  }
  // Day breakpoints sit beneath the sport icons / selected endpoints (so prepend).
  return [
    ...buildDayBreakpointMarkers(geo, dayStartActivityIds, trackColor),
    ...markers,
  ];
}

/// Owner-only encounter pins (issue #40). Tapping opens the person/group
/// sheet. Shared by [ManageMapPanelState] and the (owner-only, gated)
/// view-mode [_MapPanelState] (issue #71) so the pin-classification logic
/// isn't duplicated between the two maps.
List<Marker> buildEncounterMarkers(
  List<Map<String, dynamic>> items,
  BuildContext context,
  ProjectNotifier notifier, {
  /// Invoked when the opened sheet's encounter-location icon is tapped
  /// (issue #72). The pin's own sheet is closed first, then this fires so the
  /// caller can re-focus/zoom the map to that point.
  void Function(double lat, double lon)? onLocationTap,
}) {
  // Lookups for pin classification: a grouped person's encounter shows the
  // group ("People") icon (the individual is masked); an ungrouped person
  // shows a person icon (issue #50).
  final peopleById = {
    for (final p in notifier.people)
      if (p['id'] is int) p['id'] as int: p,
  };
  final groupsById = {
    for (final g in notifier.groups)
      if (g['id'] is int) g['id'] as int: g,
  };

  final markers = <Marker>[];
  for (final item in items) {
    if (item['item_type'] != 'encounter') continue;
    final e = item['encounter'] as Map<String, dynamic>?;
    if (e == null) continue;
    final lat = (e['lat'] as num?)?.toDouble();
    final lon = (e['lon'] as num?)?.toDouble();
    if (lat == null || lon == null) continue;

    final pin = classifyEncounterPin(
        (e['person_id'] as num?)?.toInt(), (e['group_id'] as num?)?.toInt(),
        peopleById, groupsById);
    final isGroup = pin?.kind == 'group';
    final sheetLocationTap = onLocationTap == null
        ? null
        : (double lat2, double lon2) {
            Navigator.of(context).pop();
            onLocationTap(lat2, lon2);
          };
    markers.add(Marker(
      point: LatLng(lat, lon),
      width: 22,
      height: 22,
      child: GestureDetector(
        onTap: pin == null
            ? null
            : () {
                if (isGroup) {
                  showGroupDetailSheet(context, notifier, pin.entity,
                      onLocationTap: sheetLocationTap);
                } else {
                  showPersonDetailSheet(context, notifier, pin.entity,
                      onLocationTap: sheetLocationTap);
                }
              },
        child: Container(
          decoration: BoxDecoration(
            color: kAccent,
            shape: BoxShape.circle,
            border: Border.all(color: Colors.white, width: 2),
          ),
          child: Center(
            child: Icon(isGroup ? Icons.groups : Icons.person,
                size: 12, color: Colors.white),
          ),
        ),
      ),
    ));
  }
  return markers;
}

// ── Selection stats overlay (issue #74) ──────────────────────────────────────
//
// Shows the distance/climb/day-number of the current activity or day(s)
// selection on top of the map. Shared by MapPanel (view mode) and
// ManageMapPanel (manage mode) — both read the same ProjectNotifier selection
// state (selectedActivityId / selectedDays, mutually exclusive by construction).

/// Distance/climb + a day label for the current map selection, or null when
/// nothing is selected (the overlay is hidden in that case).
@visibleForTesting
class SelectionStatsData {
  final double distanceKm;
  final double elevationM;
  /// "Day N" for a single activity/day, "Days N–M" for a contiguous multi-day
  /// selection, or "N days selected" for a non-contiguous one.
  final String dayLabel;

  const SelectionStatsData({
    required this.distanceKm,
    required this.elevationM,
    required this.dayLabel,
  });
}

/// Computes the overlay content for the notifier's current selection. Mirrors
/// [ProjectNotifier.dayStats]'s field names/units/rounding conventions for the
/// single-activity case (distance in metres → km, elevation already in metres).
@visibleForTesting
SelectionStatsData? computeSelectionStats(ProjectNotifier notifier) {
  final selActId = notifier.selectedActivityId;
  final selDays = notifier.selectedDays;
  if (selActId == null && selDays.isEmpty) return null;

  final orderedDays = notifier.orderedDayKeys();

  if (selDays.isEmpty) {
    // Single activity selected.
    Map<String, dynamic>? activity;
    for (final a in notifier.activities) {
      if (a['id']?.toString() == selActId.toString()) {
        activity = a;
        break;
      }
    }
    if (activity == null) return null;
    final distanceKm = (activity['distance'] as num? ?? 0).toDouble() / 1000.0;
    final elevationM = (activity['total_elevation_gain'] as num? ?? 0).toDouble();
    final dateKey = (activity['start_date_local'] as String?)?.split('T').first;
    final dayLabel = dateKey == null
        ? ''
        : 'Day ${dayTripNumbering(dateKey, orderedDays, notifier.tripStart).dayNumber}';
    return SelectionStatsData(
        distanceKm: distanceKm, elevationM: elevationM, dayLabel: dayLabel);
  }

  if (selDays.length == 1) {
    final dateKey = selDays.first;
    final stats = notifier.dayStats(dateKey);
    final n = dayTripNumbering(dateKey, orderedDays, notifier.tripStart);
    return SelectionStatsData(
        distanceKm: stats.distanceKm,
        elevationM: stats.elevationM,
        dayLabel: 'Day ${n.dayNumber}');
  }

  // Multiple days selected: sum distance/climb across every selected date.
  double distanceKm = 0, elevationM = 0;
  for (final d in selDays) {
    final s = notifier.dayStats(d);
    distanceKm += s.distanceKm;
    elevationM += s.elevationM;
  }
  final sortedDays = selDays.toList()..sort();
  final indices = sortedDays.map((d) => orderedDays.indexOf(d)).toList()..sort();
  final contiguous = !indices.contains(-1) &&
      indices.last - indices.first + 1 == indices.length;
  final String dayLabel;
  if (contiguous) {
    final first = dayTripNumbering(sortedDays.first, orderedDays, notifier.tripStart).dayNumber;
    final last = dayTripNumbering(sortedDays.last, orderedDays, notifier.tripStart).dayNumber;
    dayLabel = 'Days $first–$last';
  } else {
    dayLabel = '${selDays.length} days selected';
  }
  return SelectionStatsData(distanceKm: distanceKm, elevationM: elevationM, dayLabel: dayLabel);
}

/// Small mono-numeral "LABEL / value+unit" cell, matching the day-meta
/// editor's stat styling (see `_EDStat` in day_meta_editor.dart).
class _StatCell extends StatelessWidget {
  final String label;
  final String value;
  final String unit;

  const _StatCell({required this.label, required this.value, required this.unit});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(label,
            style: monoStyle(
              fontSize: 9.5, fontWeight: FontWeight.w600,
              color: cs.onSurfaceVariant, letterSpacing: 1.2,
            )),
        Row(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.baseline,
          textBaseline: TextBaseline.alphabetic,
          children: [
            Text(value,
                style: monoStyle(
                  fontSize: 15, fontWeight: FontWeight.w600, color: cs.onSurface,
                )),
            const SizedBox(width: 1),
            Text(unit, style: monoStyle(fontSize: 9.5, color: cs.onSurfaceVariant)),
          ],
        ),
      ],
    );
  }
}

/// Positioned badge (top-right corner) showing distance/climb/day for the
/// current activity or day(s) selection. Hidden entirely when nothing is
/// selected — see [computeSelectionStats].
class SelectionStatsOverlay extends StatelessWidget {
  final ProjectNotifier notifier;

  const SelectionStatsOverlay({super.key, required this.notifier});

  @override
  Widget build(BuildContext context) {
    final stats = computeSelectionStats(notifier);
    if (stats == null) return const SizedBox.shrink();
    final cs = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 10, 14, 10),
      decoration: BoxDecoration(
        color: cs.surface.withValues(alpha: 0.94),
        borderRadius: BorderRadius.circular(12),
        boxShadow: kShadow2(Theme.of(context).brightness),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (stats.dayLabel.isNotEmpty) ...[
            Icon(Icons.today, size: 14, color: cs.onSurfaceVariant),
            const SizedBox(width: 6),
            Text(stats.dayLabel,
                style: monoStyle(
                  fontSize: 12.5, fontWeight: FontWeight.w600, color: cs.onSurface,
                )),
            const SizedBox(width: 12),
            Container(width: 1, height: 22, color: cs.outlineVariant),
            const SizedBox(width: 12),
          ],
          _StatCell(
              label: 'DIST', value: stats.distanceKm.round().toString(), unit: 'km'),
          const SizedBox(width: 14),
          _StatCell(
              label: 'CLIMB', value: stats.elevationM.round().toString(), unit: 'm'),
        ],
      ),
    );
  }
}

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

  /// When true, changing the selection zooms the map to the selected
  /// activity/segment instead of leaving the viewport as-is (view-mode
  /// "auto-zoom to selection", issue #34).
  final bool autoZoom;

  /// Initial camera position (carried over from the other mode when
  /// switching view/edit, so the viewport doesn't reset to fit-all-bounds).
  /// When set, the initial full-track auto-fit is skipped.
  final double? initialLat;
  final double? initialLng;
  final double? initialZoom;

  /// Owner-only encounter pins + toggle (issue #71). Defaults to `false` so
  /// the public/shared map (which reuses this same widget) never renders
  /// encounters — they are strictly owner-only PII (see docs/ENCOUNTERS.md).
  /// Only the owner-authenticated view-mode screen should ever pass `true`.
  final bool showEncounters;

  /// A single point to highlight with [focusedLocationMarker] (issue #72),
  /// set by the parent screen when the user taps an encounter's place icon.
  final LatLng? focusedLatLng;

  /// Invoked when an encounter pin's sheet's place icon is tapped (issue #72)
  /// — the parent screen re-focuses/zooms the map to that point.
  final void Function(double lat, double lon)? onLocationTap;

  /// Invoked on any other map tap/selection, so the parent can clear
  /// [focusedLatLng] (issue #72) — no timer, cleared on the next interaction.
  final VoidCallback? onClearFocusedLocation;

  /// Owner-only locate-me button (issue #88). Defaults to `false` so the
  /// public/shared map (which reuses this same widget) never prompts
  /// anonymous visitors for their location — mirrors [showEncounters].
  /// Only the owner-authenticated view-mode screen should ever pass `true`.
  final bool showLocateMe;

  /// The device-location pin to render via [youAreHereMarker] (issue #88),
  /// set by the parent screen after a successful locate-me fetch.
  final LatLng? hereLatLng;

  /// True while the parent screen is fetching the device's location, so the
  /// locate-me button can show a busy state.
  final bool locatingHere;

  /// Invoked when the locate-me button is tapped — the parent screen owns
  /// the actual device-location fetch and camera pan, mirroring how
  /// [onLocationTap] is owned by the parent rather than this widget.
  final VoidCallback? onLocateMe;

  const MapPanel({
    super.key,
    required this.notifier,
    required this.mapController,
    required this.basemapUrl,
    this.basemapSubdomains = const [],
    this.labelsUrl,
    this.basemapStyleUri,
    this.trackTileUrlTemplate,
    this.autoZoom = false,
    this.initialLat,
    this.initialLng,
    this.initialZoom,
    this.showEncounters = false,
    this.focusedLatLng,
    this.onLocationTap,
    this.onClearFocusedLocation,
    this.showLocateMe = false,
    this.hereLatLng,
    this.locatingHere = false,
    this.onLocateMe,
  });

  @override
  State<MapPanel> createState() => _MapPanelState();
}

class _MapPanelState extends State<MapPanel> {
  // Seeded true when an initial camera position was carried over from the
  // other mode (view/edit toggle) — skips the fit-all-bounds animation.
  late bool _fittedBounds = widget.initialLat != null;
  // Points to auto-zoom to after the next full-track fit (issue #34). Set when
  // the selection changes and autoZoom is on; consumed once in build().
  List<LatLng>? _pendingAutoZoomPts;
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
  List<Marker> _cachedActivityMarkers = [];
  List<Marker> _cachedSegmentMarkers = [];
  List<Marker> _cachedMemoryMarkers = [];
  List<Marker> _cachedJournalMarkers = [];
  List<Marker> _cachedEncounterMarkers = [];
  bool _showMemories = true;
  bool _showEncounters = true;
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
      pts.addAll(memoCoordsToLatLng(coords));
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

      final points = memoCoordsToLatLng(coords);
      // A LineString needs ≥2 points; a single-point polyline can throw deep in
      // flutter_map's paint path, so skip it (and empty ones) defensively.
      if (points.length < 2) continue;

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

      final point = memoArcMidpoint(coords);
      if (point == null) continue;

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
          ? const Color(0xFF333333)
          : hasSelection
              ? const Color(0xA0000000)
              : Colors.black;
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
            showMemoryDetail(context, widget.notifier, mem, readOnly: true,
                shareContentKey: widget.notifier.shareContentKey);
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
          // View mode lays the chart out as a sibling below the map (a Column),
          // so the map viewport already excludes it — no chart-clearance inset
          // here, unlike ManageMapPanel where the chart overlays the map.
          padding: const EdgeInsets.all(32),
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
    widget.onClearFocusedLocation?.call();
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
      final dayStartIds = dayStartActivityIds(
          items, {for (final a in notifier.activities) a['id']: a});
      _cachedActivityMarkers = geo != null
          ? _buildActivityMarkersFromGeo(geo, selActId, hasSelection, trackColor,
              dayStartActivityIds: dayStartIds)
          : [];
      _cachedSegmentMarkers = geo != null
          ? _buildSegmentMarkers(geo, selSegId, hasSelection, trackColor)
          : [];
      _cachedMemoryMarkers =
          _buildMemoryMarkers(items, selMemId, hasSelection, context);
      _cachedJournalMarkers =
          _buildJournalMarkers(items, selJournalId, hasSelection, context);
      _cachedEncounterMarkers = widget.showEncounters
          ? buildEncounterMarkers(items, context, notifier,
              onLocationTap: widget.onLocationTap)
          : const [];
      // Auto-zoom to selection (issue #34). Previously this always did
      // `_fittedBounds = false` on any selection change, which re-fit the map to
      // the WHOLE trip every time — so view mode "reset to full trip zoom"
      // instead of zooming to the picked item. Now: only when auto-zoom is on
      // and something is selected do we queue a zoom to that item; with
      // auto-zoom off, selection leaves the viewport untouched.
      if (selectionChanged && widget.autoZoom && geo != null &&
          (selActId != null || selSegId != null)) {
        _pendingAutoZoomPts = ManageMapPanelState.extractSelectedPoints(
            geo, selActId, selSegId, null, null);
      } else if (selectionChanged) {
        _pendingAutoZoomPts = null;
      }
    }
    final polylines = _cachedPolylines;
    final allPoints = _cachedAllPoints;

    if (allPoints.isNotEmpty && !notifier.isLoading) {
      _fitBoundsOnce(allPoints);
    }

    // Auto-zoom to the selected item (issue #34), scheduled after the
    // full-track fit so it wins over it.
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
            padding: const EdgeInsets.all(48),
          ),
          curve: Curves.easeInOut,
        );
      });
    }

    // FlutterMap stays mounted throughout loading so the MapController stays
    // attached and tiles don't get torn down on every load.  A spinner is
    // overlaid on top while data is in flight.
    return Stack(
      children: [
        FlutterMap(
          mapController: widget.mapController.mapController,
          options: MapOptions(
            initialCenter: widget.initialLat != null
                ? LatLng(widget.initialLat!, widget.initialLng!)
                : const LatLng(0, 0),
            initialZoom: widget.initialZoom ?? 2,
            maxZoom: kMaxMapZoom,
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
                layerMode: kVectorTileMode,
                maximumZoom: kMaxMapZoom,
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
            if (_cachedActivityMarkers.isNotEmpty)
              MarkerLayer(markers: _cachedActivityMarkers),
            if (_cachedSegmentMarkers.isNotEmpty)
              MarkerLayer(markers: _cachedSegmentMarkers),
            if (_showMemories && _cachedMemoryMarkers.isNotEmpty)
              MarkerLayer(markers: _cachedMemoryMarkers),
            if (notifier.showJournals && _cachedJournalMarkers.isNotEmpty)
              MarkerLayer(markers: _cachedJournalMarkers),
            if (widget.showEncounters && _showEncounters &&
                _cachedEncounterMarkers.isNotEmpty)
              MarkerLayer(markers: _cachedEncounterMarkers),
            if (widget.focusedLatLng != null)
              MarkerLayer(markers: [focusedLocationMarker(widget.focusedLatLng!)]),
            if (widget.hereLatLng != null)
              MarkerLayer(markers: [youAreHereMarker(widget.hereLatLng!)]),
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
                          color: Colors.black,
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
        if (_cachedMemoryMarkers.isNotEmpty ||
            (widget.showEncounters && _cachedEncounterMarkers.isNotEmpty))
          Positioned(
            top: 12,
            left: 12,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (_cachedMemoryMarkers.isNotEmpty) ...[
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
                if (widget.showEncounters && _cachedEncounterMarkers.isNotEmpty) ...[
                  if (_cachedMemoryMarkers.isNotEmpty) const SizedBox(width: 12),
                  Text(
                    'Encounters',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Colors.white,
                    ),
                  ),
                  Transform.scale(
                    scale: 0.7,
                    child: Switch(
                      value: _showEncounters,
                      onChanged: (v) => setState(() => _showEncounters = v),
                      materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    ),
                  ),
                ],
              ],
            ),
          ),
        Positioned(
          top: 12,
          right: 12,
          child: SelectionStatsOverlay(notifier: notifier),
        ),
        if (widget.showLocateMe && widget.onLocateMe != null)
          Positioned(
            bottom: 16,
            right: 12,
            child: LocateMeButton(
              locating: widget.locatingHere,
              onPressed: widget.onLocateMe!,
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

  /// Initial camera position (carried over from the other mode when
  /// switching view/edit). The caller is expected to seed [fittedNotifier]
  /// to `true` when these are set, so the fit-all-bounds animation is skipped.
  final double? initialLat;
  final double? initialLng;
  final double? initialZoom;

  /// A single point to highlight with [focusedLocationMarker] (issue #72),
  /// set by the parent screen when the user taps an encounter's place icon.
  final LatLng? focusedLatLng;

  /// Invoked when an encounter pin's sheet's place icon is tapped (issue #72)
  /// — the parent screen re-focuses/zooms the map to that point.
  final void Function(double lat, double lon)? onLocationTap;

  /// Invoked on any other map tap/selection, so the parent can clear
  /// [focusedLatLng] (issue #72) — no timer, cleared on the next interaction.
  final VoidCallback? onClearFocusedLocation;

  /// The device-location pin to render via [youAreHereMarker] (issue #88),
  /// set by the parent screen after a successful locate-me fetch.
  final LatLng? hereLatLng;

  /// True while the parent screen is fetching the device's location, so the
  /// locate-me button can show a busy state.
  final bool locatingHere;

  /// Invoked when the locate-me button is tapped — the parent screen owns
  /// the actual device-location fetch and camera pan. Edit mode is always
  /// owner-only, so unlike [MapPanel.showLocateMe] there's no separate gate:
  /// the button renders whenever this is non-null.
  final VoidCallback? onLocateMe;

  const ManageMapPanel({
    super.key,
    required this.notifier,
    required this.mapController,
    required this.basemapUrl,
    required this.fittedNotifier,
    this.autoZoom = false,
    this.basemapSubdomains = const [],
    this.basemapStyleUri,
    this.initialLat,
    this.initialLng,
    this.initialZoom,
    this.focusedLatLng,
    this.onLocationTap,
    this.onClearFocusedLocation,
    this.hereLatLng,
    this.locatingHere = false,
    this.onLocateMe,
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
  List<Marker> _cachedActivityMarkers = [];
  List<Marker> _cachedSegmentMarkers = [];
  List<Marker> _cachedMemoryMarkers = [];
  List<Marker> _cachedJournalMarkers = [];
  List<Marker> _cachedEncounterMarkers = [];
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

      final point = memoArcMidpoint(coords);
      if (point == null) continue;

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
    Set<String> effectiveDays,
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
      final memDate = mem['date'] as String?;
      final isDayHighlighted = effectiveDays.isEmpty ||
          (memDate != null && effectiveDays.contains(memDate));
      final size = isSelected ? 34.0 : 28.0;
      final bgColor = isSelected
          ? const Color(0xFF333333)
          : (hasSelection && !isDayHighlighted)
              ? const Color(0xA0000000)
              : Colors.black;

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
    widget.onClearFocusedLocation?.call();
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

  /// Points of the currently-selected activity/segment (or all activities/
  /// segments of the selected day(s)), used to compute the auto-zoom target.
  /// Public + static so the view-mode [MapPanel] and tests can reuse it.
  static List<LatLng> extractSelectedPoints(
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
      points.addAll(memoCoordsToLatLng(coords));
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
      final points = memoCoordsToLatLng(coords);
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
    // Dev-only build timer (PERF_TIMING) — pins whether map rebuilds are the
    // source of the build-thread storms, and what triggers them.
    final perfSw = kPerfTiming ? (Stopwatch()..start()) : null;
    var perfRebuiltLayers = false;
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
    final perfGeoChg = !identical(geo, _lastGeo);
    final perfItemsChg = !identical(items, _lastItems);
    final perfJournalsChg = showJournals2 != _lastShowJournals;
    if (perfGeoChg || selectionChanged2 ||
        perfItemsChg || styleChanged2 ||
        perfJournalsChg) {
      perfRebuiltLayers = true;
      if (selectionChanged2 && widget.autoZoom) widget.fittedNotifier.value = false;
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
      _cachedActivityMarkers = geo != null
          ? _buildActivityMarkersFromGeo(geo, selActId, hasSelection, trackColor,
              dayStartActivityIds: dayStartActivityIds(items, actById))
          : [];
      _cachedSegmentMarkers = geo != null
          ? _buildSegmentMarkers(geo, selSegId, hasSelection, trackColor)
          : [];
      _cachedMemoryMarkers =
          _buildMemoryMarkers(items, selMemId, hasSelection, effectiveDays, context);
      _cachedJournalMarkers =
          _buildJournalMarkers(items, selJournalId2, hasSelection, context);
      _cachedEncounterMarkers = buildEncounterMarkers(items, context,
          widget.notifier, onLocationTap: widget.onLocationTap);

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
        _pendingAutoZoomPts = extractSelectedPoints(
            geo, selActId, selSegId, dayActIds, daySegIds);
      } else if (selectionChanged2) {
        _pendingAutoZoomPts = null;
      }
    }

    // Guard on fittedNotifier before flattening every polyline's points: once
    // the map has been fitted, _fitBoundsOnce early-returns, so building this
    // (potentially huge) point list on every build was pure waste/GC churn.
    if (!notifier.isLoading && !widget.fittedNotifier.value) {
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

    final perfBuilt = Stack(
      children: [
        FlutterMap(
          mapController: widget.mapController.mapController,
          options: MapOptions(
            initialCenter: widget.initialLat != null
                ? LatLng(widget.initialLat!, widget.initialLng!)
                : const LatLng(48.0, 10.0),
            initialZoom: widget.initialZoom ?? 4,
            maxZoom: kMaxMapZoom,
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
                layerMode: kVectorTileMode,
                maximumZoom: kMaxMapZoom,
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
            if (_cachedActivityMarkers.isNotEmpty)
              MarkerLayer(markers: _cachedActivityMarkers),
            if (_cachedSegmentMarkers.isNotEmpty)
              MarkerLayer(markers: _cachedSegmentMarkers),
            if (_showMemories && _cachedMemoryMarkers.isNotEmpty)
              MarkerLayer(markers: _cachedMemoryMarkers),
            if (notifier.showJournals && _cachedJournalMarkers.isNotEmpty)
              MarkerLayer(markers: _cachedJournalMarkers),
            if (_cachedEncounterMarkers.isNotEmpty)
              MarkerLayer(markers: _cachedEncounterMarkers),
            if (widget.focusedLatLng != null)
              MarkerLayer(markers: [focusedLocationMarker(widget.focusedLatLng!)]),
            if (widget.hereLatLng != null)
              MarkerLayer(markers: [youAreHereMarker(widget.hereLatLng!)]),
            // Owner-only, view-only Polarsteps trip overlay for a person (#40).
            if (notifier.polarstepsOverlaySteps.isNotEmpty) ...[
              PolylineLayer(
                polylines: [
                  Polyline(
                    points: [
                      for (final s in notifier.polarstepsOverlaySteps)
                        LatLng((s['lat'] as num).toDouble(),
                            (s['lon'] as num).toDouble()),
                    ],
                    color: const Color(0xFF7C3AED),
                    strokeWidth: 3,
                  ),
                ],
              ),
              MarkerLayer(
                markers: [
                  for (final s in notifier.polarstepsOverlaySteps)
                    Marker(
                      point: LatLng((s['lat'] as num).toDouble(),
                          (s['lon'] as num).toDouble()),
                      width: 12,
                      height: 12,
                      child: const DecoratedBox(
                        decoration: BoxDecoration(
                          color: Color(0xFF7C3AED),
                          shape: BoxShape.circle,
                        ),
                      ),
                    ),
                ],
              ),
            ],
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
                          color: Colors.black,
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
        if (notifier.polarstepsOverlaySteps.isNotEmpty)
          Positioned(
            top: 12,
            left: 12,
            right: 12,
            child: Align(
              alignment: Alignment.topCenter,
              child: Material(
                color: const Color(0xFF7C3AED),
                borderRadius: BorderRadius.circular(20),
                child: Padding(
                  padding: const EdgeInsets.only(left: 14, right: 4),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.travel_explore,
                          size: 16, color: Colors.white),
                      const SizedBox(width: 8),
                      Flexible(
                        child: Text(
                          notifier.polarstepsOverlayLabel ?? 'Polarsteps trip',
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(color: Colors.white),
                        ),
                      ),
                      IconButton(
                        icon: const Icon(Icons.close,
                            size: 16, color: Colors.white),
                        visualDensity: VisualDensity.compact,
                        tooltip: 'Clear overlay',
                        onPressed: notifier.clearPolarstepsOverlay,
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        Positioned(
          top: 12,
          right: 12,
          child: SelectionStatsOverlay(notifier: notifier),
        ),
        if (widget.onLocateMe != null)
          Positioned(
            bottom: 16,
            right: 12,
            child: LocateMeButton(
              locating: widget.locatingHere,
              onPressed: widget.onLocateMe!,
            ),
          ),
      ],
    );
    if (perfSw != null) {
      perfSw.stop();
      final ms = perfSw.elapsedMilliseconds;
      if (ms >= 16) {
        final markers = _cachedActivityMarkers.length +
            _cachedSegmentMarkers.length +
            _cachedMemoryMarkers.length +
            _cachedJournalMarkers.length;
        debugPrint('[perf] ManageMapPanel.build ${ms}ms '
            'rebuilt=$perfRebuiltLayers geoChg=$perfGeoChg selChg=$selectionChanged2 '
            'itemsChg=$perfItemsChg styleChg=$styleChanged2 jrnChg=$perfJournalsChg '
            'markers=$markers polys=${_cachedPolylines.length}');
      }
    }
    return perfBuilt;
  }
}

// ── _StatChip ─────────────────────────────────────────────────────────────────

// ── Poster frame picker (issue #14, unit F) ──────────────────────────────────
//
// A fixed-aspect-ratio frame overlaid on the map to preview what an A0 poster
// export will capture. The user pans/zooms the real map underneath the frame
// using normal map gestures — the frame itself is wrapped in [IgnorePointer]
// and never intercepts touches or drags. Confirming ("Next") reads the map's
// current viewport bounds (`camera.visibleBounds`) as the capture region (see
// [posterBoundsFromLatLngBounds]) — the map viewport is generally a different
// aspect ratio than the drawn frame, so this is a v1 approximation rather than
// a pixel-exact crop of the frame rectangle.

/// A0 paper aspect ratio (width / height) in portrait orientation (841×1189 mm).
const double kA0PortraitAspect = 841 / 1189;

/// The frame rectangle centered in [size] with the given orientation's A0
/// aspect ratio, inset by [padding] on all sides (shrunk to fit if needed).
@visibleForTesting
Rect frameRectFor(Size size, String orientation, {double padding = 32}) {
  final aspect =
      orientation == 'portrait' ? kA0PortraitAspect : 1 / kA0PortraitAspect;
  final maxW = (size.width - padding * 2).clamp(0.0, size.width);
  final maxH = (size.height - padding * 2).clamp(0.0, size.height);
  double w = maxW;
  double h = w / aspect;
  if (h > maxH) {
    h = maxH;
    w = h * aspect;
  }
  final left = (size.width - w) / 2;
  final top = (size.height - h) / 2;
  return Rect.fromLTWH(left, top, w, h);
}

/// Converts the map's current viewport bounds to the `{north, south, east,
/// west}` shape the poster API's `bounds` request field expects. Used by
/// `app_screen.dart` when the frame picker's "Next" is confirmed.
Map<String, double> posterBoundsFromLatLngBounds(LatLngBounds bounds) => {
      'north': bounds.north,
      'south': bounds.south,
      'east': bounds.east,
      'west': bounds.west,
    };

class _FrameMaskPainter extends CustomPainter {
  final Rect frameRect;
  final Color maskColor;
  final Color borderColor;

  const _FrameMaskPainter({
    required this.frameRect,
    required this.maskColor,
    required this.borderColor,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final path = ui.Path()
      ..addRect(Rect.fromLTWH(0, 0, size.width, size.height))
      ..addRect(frameRect)
      ..fillType = ui.PathFillType.evenOdd;
    canvas.drawPath(path, Paint()..color = maskColor);
    canvas.drawRect(
      frameRect,
      Paint()
        ..color = borderColor
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );
  }

  @override
  bool shouldRepaint(covariant _FrameMaskPainter oldDelegate) =>
      oldDelegate.frameRect != frameRect ||
      oldDelegate.maskColor != maskColor ||
      oldDelegate.borderColor != borderColor;
}

/// Dimmed-mask + fixed-aspect-ratio frame overlay for picking the poster
/// capture region (issue #14). Placed as a `Stack` sibling on top of a live
/// [ManageMapPanel] by the parent screen (`app_screen.dart`) when the poster
/// flow is active — see that file for the on/off toggle wiring.
class FramePickerOverlay extends StatefulWidget {
  final AnimatedMapController mapController;

  /// Invoked with the map's current viewport bounds and the chosen
  /// orientation ('landscape'/'portrait') when the user taps "Next".
  final void Function(LatLngBounds bounds, String orientation) onNext;
  final VoidCallback onCancel;

  const FramePickerOverlay({
    super.key,
    required this.mapController,
    required this.onNext,
    required this.onCancel,
  });

  @override
  State<FramePickerOverlay> createState() => _FramePickerOverlayState();
}

class _FramePickerOverlayState extends State<FramePickerOverlay> {
  String _orientation = 'landscape';

  void _toggleOrientation() => setState(() =>
      _orientation = _orientation == 'landscape' ? 'portrait' : 'landscape');

  void _confirm() {
    final bounds = widget.mapController.mapController.camera.visibleBounds;
    widget.onNext(bounds, _orientation);
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return LayoutBuilder(builder: (context, constraints) {
      final size = Size(constraints.maxWidth, constraints.maxHeight);
      final frameRect = frameRectFor(size, _orientation);
      return Stack(
        children: [
          Positioned.fill(
            child: IgnorePointer(
              child: CustomPaint(
                painter: _FrameMaskPainter(
                  frameRect: frameRect,
                  maskColor: const Color(0x99000000),
                  borderColor: Colors.white,
                ),
              ),
            ),
          ),
          Positioned(
            bottom: 24,
            left: 0,
            right: 0,
            child: Center(
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                decoration: BoxDecoration(
                  color: cs.surface.withValues(alpha: 0.95),
                  borderRadius: BorderRadius.circular(12),
                  boxShadow: kShadow2(Theme.of(context).brightness),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    IconButton(
                      tooltip: _orientation == 'landscape'
                          ? 'Switch to portrait'
                          : 'Switch to landscape',
                      icon: Icon(_orientation == 'landscape'
                          ? Icons.crop_landscape
                          : Icons.crop_portrait),
                      onPressed: _toggleOrientation,
                    ),
                    const SizedBox(width: 4),
                    TextButton(
                      onPressed: widget.onCancel,
                      child: const Text('Cancel'),
                    ),
                    const SizedBox(width: 4),
                    FilledButton(
                      onPressed: _confirm,
                      child: const Text('Next'),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      );
    });
  }
}

// ── MobileActivityPanelOverlay ───────────────────────────────────────────────
// Slide-in activity panel for narrow (mobile) layout. Rendered as a Material
// surface with elevation so it casts a shadow over the map behind it.

class MobileActivityPanelOverlay extends StatelessWidget {
  final ProjectNotifier notifier;
  final AnimatedMapController mapController;
  final double height;

  /// Drives the panel's list scrolling. Without it the panel can't centre a
  /// selection (issue #21) — `_scrollToSegment` no-ops on a null controller.
  final ScrollController? scrollController;

  /// Whether the overlay is currently open (slid on-screen). Forwarded to
  /// [ActivityPanel.panelVisible] so it reveals the current selection on open.
  final bool isVisible;

  /// Forwarded to [ActivityPanel.onLocationTap] (issue #72).
  final void Function(double lat, double lon)? onLocationTap;

  const MobileActivityPanelOverlay({
    super.key,
    required this.notifier,
    required this.mapController,
    required this.height,
    this.scrollController,
    this.isVisible = true,
    this.onLocationTap,
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
          scrollController: scrollController,
          panelVisible: isVisible,
          onLocationTap: onLocationTap,
        ),
      ),
    );
  }
}
