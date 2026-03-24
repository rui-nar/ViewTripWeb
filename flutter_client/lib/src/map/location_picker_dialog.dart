/// Full-screen dialog that lets the user tap a point on the map.
///
/// Returns a [LatLonResult] record on confirm, or null on cancel.
// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use
library;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_map_cancellable_tile_provider/flutter_map_cancellable_tile_provider.dart';
import 'package:latlong2/latlong.dart';

typedef LatLonResult = ({double lat, double lon});

class LocationPickerDialog extends StatefulWidget {
  /// Label shown in the title bar, e.g. "Pick start location".
  final String title;

  /// Pre-selected position (centers the map and places a marker).
  final double? initialLat;
  final double? initialLon;

  /// Project GeoJSON — rendered as context polylines so the user can see
  /// the existing route while picking a new point.
  final Map<String, dynamic>? geo;

  const LocationPickerDialog({
    super.key,
    required this.title,
    this.initialLat,
    this.initialLon,
    this.geo,
  });

  @override
  State<LocationPickerDialog> createState() => _LocationPickerDialogState();
}

class _LocationPickerDialogState extends State<LocationPickerDialog> {
  LatLng? _picked;

  @override
  void initState() {
    super.initState();
    if (widget.initialLat != null && widget.initialLon != null) {
      _picked = LatLng(widget.initialLat!, widget.initialLon!);
    }
  }

  // ── Map initialisation ──────────────────────────────────────────────────────

  LatLng get _center {
    if (_picked != null) return _picked!;
    // Default: zoom out to world view
    return const LatLng(20, 0);
  }

  double get _zoom => _picked != null ? 10.0 : 2.0;

  // ── Polylines from project GeoJSON ─────────────────────────────────────────

  List<Polyline> _buildPolylines() {
    final geo = widget.geo;
    if (geo == null) return [];
    final features = geo['features'];
    if (features is! List) return [];

    final lines = <Polyline>[];
    for (final f in features) {
      if (f is! Map) continue;
      final coords = f['geometry']?['coordinates'];
      if (coords is! List) continue;
      final pts = <LatLng>[];
      for (final c in coords) {
        if (c is List && c.length >= 2) {
          pts.add(LatLng((c[1] as num).toDouble(), (c[0] as num).toDouble()));
        }
      }
      if (pts.isEmpty) continue;
      final isSegment = f['properties']?['type'] == 'segment';
      lines.add(Polyline(
        points: pts,
        color: isSegment
            ? const Color(0x88888888)
            : const Color(0x80F97316),
        strokeWidth: isSegment ? 1.5 : 2.5,
      ));
    }
    return lines;
  }

  // ── UI ──────────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final polylines = _buildPolylines();

    return Dialog(
      insetPadding: const EdgeInsets.all(16),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 700, maxHeight: 540),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // ── Header ─────────────────────────────────────────────────────
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 16, 8, 4),
              child: Row(
                children: [
                  const Icon(Icons.location_on, size: 20),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(widget.title,
                        style: theme.textTheme.titleMedium),
                  ),
                  IconButton(
                    icon: const Icon(Icons.close),
                    onPressed: () => Navigator.of(context).pop(null),
                  ),
                ],
              ),
            ),

            // ── Instruction ─────────────────────────────────────────────────
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: Text(
                'Tap anywhere on the map to place a pin.',
                style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurface.withValues(alpha: 0.6)),
              ),
            ),
            const SizedBox(height: 8),

            // ── Map ──────────────────────────────────────────────────────────
            Expanded(
              child: ClipRect(
                child: FlutterMap(
                  options: MapOptions(
                    initialCenter: _center,
                    initialZoom: _zoom,
                    onTap: (_, latlng) {
                      setState(() => _picked = latlng);
                    },
                  ),
                  children: [
                    TileLayer(
                      urlTemplate:
                          'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                      userAgentPackageName: 'com.viewtrip.client',
                      tileProvider: CancellableNetworkTileProvider(),
                    ),
                    if (polylines.isNotEmpty)
                      PolylineLayer(polylines: polylines),
                    if (_picked != null)
                      MarkerLayer(
                        markers: [
                          Marker(
                            point: _picked!,
                            width: 36,
                            height: 36,
                            alignment: Alignment.topCenter,
                            child: const Icon(
                              Icons.location_pin,
                              color: Colors.red,
                              size: 36,
                            ),
                          ),
                        ],
                      ),
                  ],
                ),
              ),
            ),

            // ── Footer ───────────────────────────────────────────────────────
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
              child: Row(
                children: [
                  // Coordinate readout
                  Expanded(
                    child: _picked == null
                        ? Text('No point selected',
                            style: theme.textTheme.bodySmall)
                        : Text(
                            '${_picked!.latitude.toStringAsFixed(6)}, '
                            '${_picked!.longitude.toStringAsFixed(6)}',
                            style: theme.textTheme.bodySmall?.copyWith(
                                fontFamily: 'monospace'),
                          ),
                  ),
                  TextButton(
                    onPressed: () => Navigator.of(context).pop(null),
                    child: const Text('Cancel'),
                  ),
                  const SizedBox(width: 8),
                  ElevatedButton.icon(
                    icon: const Icon(Icons.check, size: 16),
                    label: const Text('Confirm'),
                    onPressed: _picked == null
                        ? null
                        : () => Navigator.of(context).pop<LatLonResult>((
                              lat: _picked!.latitude,
                              lon: _picked!.longitude,
                            )),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
