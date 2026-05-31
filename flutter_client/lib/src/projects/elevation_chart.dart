library;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import '../map/geo_point.dart';
import '../map/polyline_decoder.dart';

class ElevationChart extends StatefulWidget {
  final List<Map<String, dynamic>> activities;
  final dynamic selectedActivityId;

  /// Called with the map position under the chart cursor, or null when the
  /// user lifts / exits. Drives the elevation cursor marker on the map.
  final void Function(GeoPoint?)? onCursorChanged;

  /// Driven by map taps — shows a vertical line at this distance (km).
  final ValueNotifier<double?>? mapCursorNotifier;

  /// Pre-built distance-indexed track (cumulative km → LatLng).
  /// Built by ProjectNotifier from GeoJSON so Flutter never needs to decode
  /// the polyline.  Pass fullTrack when no activity is selected, or the
  /// per-activity track (0-based distances) when one is selected.
  final List<(double, GeoPoint)> track;

  /// Color of the chart line and fill. Defaults to black when null.
  final Color? color;

  /// When false, the line is hidden but the filled area below still renders.
  final bool showLine;

  const ElevationChart({
    super.key,
    required this.activities,
    required this.track,
    this.selectedActivityId,
    this.onCursorChanged,
    this.mapCursorNotifier,
    this.color,
    this.showLine = true,
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

  static Widget _elevBottomTitle(double value, TitleMeta meta) {
    // Skip the first and last tick to avoid clipping at chart edges.
    if (value == meta.min || value == meta.max) return const SizedBox.shrink();
    return Text('${value.toStringAsFixed(0)} km',
        style: const TextStyle(fontSize: 9));
  }

  double get _bottomInterval {
    if (_spots.isEmpty) return 50;
    final total = _spots.last.x;
    if (total <= 30)   return 5;
    if (total <= 100)  return 10;
    if (total <= 250)  return 25;
    if (total <= 600)  return 50;
    if (total <= 1200) return 100;
    if (total <= 3000) return 200;
    if (total <= 6000) return 500;
    return 1000;
  }

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
          gridData: FlGridData(
            show: true,
            drawHorizontalLine: true,
            horizontalInterval: 100,
            drawVerticalLine: false,
            getDrawingHorizontalLine: (value) {
              return FlLine(
                color: Colors.grey.withValues(alpha: 0.3),
                strokeWidth: 1,
                dashArray: [2, 2],
              );
            },
          ),
          borderData: FlBorderData(show: false),
          titlesData: FlTitlesData(
            leftTitles: AxisTitles(
              axisNameWidget: RotatedBox(
                quarterTurns: 0,
                child: Text(
                  'Elevation (m)',
                  style: Theme.of(context).textTheme.labelSmall,
                ),
              ),
              axisNameSize: 14,
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
                interval: _bottomInterval,
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
                color: widget.color ?? Colors.black,
                strokeWidth: 1.5,
                dashArray: [4, 4],
              ),
            ]);
          }(),
          lineTouchData: LineTouchData(
            touchCallback: _onTouch,
            handleBuiltInTouches: true,
            touchTooltipData: LineTouchTooltipData(
              getTooltipColor: (_) => Colors.transparent,
            ),
          ),
          lineBarsData: [
            LineChartBarData(
              spots: _spots,
              isCurved: true,
              color: widget.showLine
                  ? (widget.color ?? Colors.black)
                  : const Color(0x01000000), // alpha=1: invisible but touchable
              barWidth: 2,
              dotData: const FlDotData(show: false),
              belowBarData: BarAreaData(
                show: true,
                color: (widget.color ?? Colors.black).withValues(alpha: 0.2),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Drop-in replacement for [ElevationChart] shown while elevation data is
/// loading in the background.  Must match ElevationChart's preferred height
/// so the layout does not jump when the real chart replaces it.
class ElevationLoadingPlaceholder extends StatelessWidget {
  const ElevationLoadingPlaceholder({super.key});

  @override
  Widget build(BuildContext context) => const SizedBox(
    height: 160,
    child: Center(
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          SizedBox(
            width: 16,
            height: 16,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          SizedBox(width: 10),
          Text('Loading elevation data…'),
        ],
      ),
    ),
  );
}
