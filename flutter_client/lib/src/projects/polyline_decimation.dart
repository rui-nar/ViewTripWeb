/// Aggregate point-budget decimation for the map's polylines.
///
/// Lives outside `map_panel.dart` so the decode isolate can produce the
/// decimated geometry itself (issue #299) rather than the UI isolate
/// marshalling every point into records and paying `compute()` to copy them
/// across — measured on a real device at 788 ms of marshalling plus roughly
/// 1.6 s of argument copy: a 2.4 s UI stall that landed mid-pan and tripped
/// Android's ANR watchdog. The decimated result is at most
/// [kMaxTotalPolylinePoints] points in total, so returning it costs nothing.
library;

/// Total polyline points across every simultaneously-drawn line above which
/// [decimatePolylinePoints] kicks in, capping the total at roughly this many
/// (distributed proportionally per line). flutter_map's own PolylineLayer
/// already reduces point density per line adaptively with zoom
/// (simplificationTolerance, set below) — but that has no concept of the
/// AGGREGATE across every line drawn at once, and the default (no
/// selection) view always draws every activity's full track simultaneously.
/// For a large trip whose activities' tracks overlap the same region, that
/// aggregate is exactly what flutter_map's own per-camera-frame culling walk
/// (it re-walks every point of every polyline overlapping the viewport, on
/// every single frame — confirmed by reading flutter_map 8.3.1's source)
/// pays for on every pan event, scaling linearly with trip size regardless
/// of any of our own caching. Confirmed as the actual cause via an Android
/// ANR trace: "Waited 5001ms for MotionEvent" with the app's main thread
/// pegged near 100% CPU throughout a pan on a large (dozens-of-activities)
/// trip — sustained main-isolate computation, not an I/O or lock wait.
const kMaxTotalPolylinePoints = 6000;

/// Total points across [lines] — split out from [decimatePolylinePoints] so
/// a caller can cheaply decide whether decimation is needed at all.
int totalPolylinePoints(List<List<(double, double)>> lines) =>
    lines.fold(0, (sum, l) => sum + l.length);

/// Caps the combined point count of [args.lines] at [args.budget], keeping
/// every line if already under budget. Each line's share of the budget is
/// proportional to its share of the raw total, then LTTB-downsampled (see
/// [_lttbPoints]) — long/dense tracks get more of the budget than short
/// ones, and every line keeps its first/last point exactly. Pure and
/// isolate-safe (plain records only) so it can run via [compute] for a large
/// trip without blocking the UI isolate that's about to render the result.
List<List<(double, double)>> decimatePolylinePoints(
  ({List<List<(double, double)>> lines, int budget}) args,
) {
  final total = totalPolylinePoints(args.lines);
  if (total <= args.budget || args.lines.isEmpty) return args.lines;
  return [
    for (final line in args.lines)
      if (line.length <= 2)
        line
      else
        _lttbPoints(line,
            (args.budget * line.length / total).round().clamp(2, line.length)),
  ];
}

/// Largest-Triangle-Three-Buckets downsampling over generic (x, y) points —
/// mirrors elevation_chart.dart's [_lttb] (kept separate: that one is
/// specialised for FlSpot/distance-elevation series, this one for
/// lat/lon geometry) — O(n), selects [threshold] points that best preserve
/// the curve's visual shape.
List<(double, double)> _lttbPoints(List<(double, double)> data, int threshold) {
  final n = data.length;
  if (threshold >= n) return data;
  final out = <(double, double)>[data.first];
  int a = 0;
  final every = (n - 2) / (threshold - 2);
  for (int i = 0; i < threshold - 2; i++) {
    final nS = ((i + 1) * every + 1).floor();
    final nE = ((i + 2) * every + 1).floor().clamp(0, n);
    double avgX = 0, avgY = 0;
    for (int j = nS; j < nE; j++) { avgX += data[j].$1; avgY += data[j].$2; }
    final cnt = nE - nS;
    avgX /= cnt; avgY /= cnt;
    final cS = (i * every + 1).floor();
    final cE = ((i + 1) * every + 1).floor().clamp(0, n);
    final ax = data[a].$1, ay = data[a].$2;
    double maxArea = -1; int best = cS;
    for (int j = cS; j < cE; j++) {
      final area = ((ax - avgX) * (data[j].$2 - ay)
                  - (ax - data[j].$1) * (avgY - ay)).abs();
      if (area > maxArea) { maxArea = area; best = j; }
    }
    out.add(data[best]);
    a = best;
  }
  out.add(data.last);
  return out;
}

// Shared by _MapPanelState and ManageMapPanelState. Builds the geometry/style
