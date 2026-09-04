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

/// Safety valve on the combined point count of every simultaneously-drawn
/// line. Above it, [decimatePolylinePoints] caps the total at roughly this
/// many, distributed proportionally per line.
///
/// **This is no longer the thing that decides map resolution — the server is.**
/// Since issue #295 the client asks `/api/geo/project/simplified` for geometry
/// already simplified to about one screen pixel at the zoom on display, and
/// since issue #324 that request is scoped to the viewport as well. Whatever
/// comes back is, by construction, the finest detail the screen can resolve.
///
/// At 6000 this constant was binding *below* that guarantee and silently
/// undoing it. Measured on a 219-activity trip:
///
/// ```
/// geo_coords       13273   <- what the server sent, pixel-accurate at that zoom
/// rendered_points   6029   <- what this budget let through
/// ```
///
/// So the drawn track was about twice as coarse as the line the server had
/// already built and paid to transfer — and the server's own floor
/// (`min_points`, 32 per activity in src/models/simplify.py) had to be chosen
/// against *this* number rather than against what the map needs, because a
/// floor below what the renderer would draw anyway is a regression. Two
/// resolution policies were fighting, and the coarser one won.
///
/// **Why 40,000.** It is set against the server's guarantee rather than
/// against a round number or a frame budget:
///
/// * The server returns at most `max_input_points` (4,000) points per line,
///   simplified to ~1 px at the requested zoom.
/// * The largest trip this investigation has measured came back as 13,273
///   coordinates for its *entire* length at the zoom in use. 40,000 is ~3x
///   that, so the valve does not engage on pixel-accurate geometry even for a
///   trip substantially larger, or a deeper zoom, than anything measured.
/// * It still catches what it exists to catch: the full-resolution fallback
///   path (`getGeo`, taken offline, on an older server, or for a client-built
///   E2EE trip) hands the renderer 1,465,345 points on that same trip. 40,000
///   cuts that by 97%.
///
/// One number worth keeping honest: 13,273 is what a *real* trip returned at
/// the zoom it was measured at. A synthetic 219-activity trip strung across
/// Europe returns 66,418 at zoom 15 with no bounding box — above this valve.
/// The viewport box is what keeps the payload under it (7,544 for the same
/// trip and zoom, scoped to one screen), which is why these two changes belong
/// together and why raising this without #324 would have been reckless.
///
/// If a device run shows `map_lines_paint` (issue #276's frame instrumentation)
/// cannot afford what the server sends, the fix is the *server's* tolerance or
/// its per-line cap — not this number. Lowering it here would only reinstate
/// the disagreement above.
///
/// **Why it stays a single trip-wide budget.** A per-activity or
/// per-visible-length allocation was considered: 6000 split across 219
/// activities is ~27 points each whether the activity is 2 km or 200 km, on
/// screen or 500 km away. But that allocation is exactly what the server now
/// performs, with far better information — it knows each line's real geometry,
/// the zoom, and (since #324) the viewport, and it gives an off-viewport line
/// the same 32-point floor a whole-trip zoom would. A second, cruder allocator
/// on the client would be second-guessing it. And the case this valve actually
/// fires on — the full-resolution fallback — is a whole-payload problem, not a
/// per-activity one.
///
/// The mechanism it guards is unchanged: flutter_map's PolylineLayer reduces
/// point density per line adaptively with zoom (`simplificationTolerance`,
/// set at the call site) but has no concept of the AGGREGATE across every
/// line drawn at once, and its per-camera-frame culling walk re-walks every
/// point of every polyline overlapping the viewport, on every frame
/// (confirmed by reading flutter_map 8.3.1's source). Confirmed as a real
/// cause via an Android ANR trace: "Waited 5001ms for MotionEvent" with the
/// main thread pegged near 100% CPU throughout a pan on a large trip.
const kMaxTotalPolylinePoints = 40000;

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
