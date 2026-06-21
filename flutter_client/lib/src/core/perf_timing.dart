library;

import 'dart:async';

import 'package:flutter/scheduler.dart' show FrameTiming;
import 'package:flutter/widgets.dart';

/// Dev-only frame-timing recorder. Compiled in only when built with
/// `--dart-define=PERF_TIMING=true`; in every normal/production build the const
/// is false, [PerfTiming.start] is a no-op, and the tree-shaker drops the rest.
///
/// Why this over DevTools/the performance overlay: it prints exact UI-thread
/// (build) and raster-thread (GPU) frame durations as percentiles every couple
/// of seconds, so a scroll burst is trivially isolated from idle — no GUI
/// scrubbing. The 60 fps budget is 16.7 ms; a frame is "janky" when either
/// thread blows it. build-bound jank ⇒ per-row build/layout cost; raster-bound
/// jank ⇒ paint/compositing/renderer cost. See the activity-panel diagnosis.
const bool kPerfTiming = bool.fromEnvironment('PERF_TIMING');

/// 60 fps frame budget in milliseconds.
const double kFrameBudgetMs = 1000.0 / 60.0; // 16.67

/// Nearest-rank percentile of an already-ascending-sorted list, in ms.
/// Returns 0 for an empty list. Pure + testable.
double perfPercentile(List<double> sortedAsc, int pct) {
  if (sortedAsc.isEmpty) return 0;
  final idx = ((pct / 100.0) * (sortedAsc.length - 1)).round();
  return sortedAsc[idx.clamp(0, sortedAsc.length - 1)];
}

/// One-line summary of a window of frame timings. Pure + testable so the
/// reporting format is covered without needing a real frame pipeline.
String perfSummaryLine(List<double> buildMs, List<double> rasterMs) {
  final n = buildMs.length;
  if (n == 0) return '[perf] (no frames)';
  var janky = 0;
  for (var i = 0; i < n; i++) {
    if (buildMs[i] > kFrameBudgetMs ||
        (i < rasterMs.length && rasterMs[i] > kFrameBudgetMs)) {
      janky++;
    }
  }
  final b = [...buildMs]..sort();
  final r = [...rasterMs]..sort();
  String f(double ms) => ms.toStringAsFixed(1);
  return '[perf] frames=$n  '
      'build p50=${f(perfPercentile(b, 50))} p90=${f(perfPercentile(b, 90))} '
      'p99=${f(perfPercentile(b, 99))} max=${f(b.last)}ms  |  '
      'raster p50=${f(perfPercentile(r, 50))} p90=${f(perfPercentile(r, 90))} '
      'p99=${f(perfPercentile(r, 99))} max=${f(r.last)}ms  |  '
      'janky(>${kFrameBudgetMs.toStringAsFixed(1)}ms)=$janky/$n';
}

class PerfTiming {
  PerfTiming._();
  static final PerfTiming instance = PerfTiming._();

  final List<double> _build = [];
  final List<double> _raster = [];
  Timer? _timer;
  bool _started = false;

  /// Begin recording. No-op unless built with PERF_TIMING=true.
  void start() {
    if (_started || !kPerfTiming) return;
    _started = true;
    WidgetsBinding.instance.addTimingsCallback(_onTimings);
    _timer = Timer.periodic(const Duration(seconds: 2), (_) => _report());
    debugPrint('[perf] frame-timing recorder ON '
        '(budget ${kFrameBudgetMs.toStringAsFixed(1)}ms/frame). '
        'Scroll the activity panel — a summary prints every 2s; '
        'idle windows are skipped.');
  }

  void _onTimings(List<FrameTiming> timings) {
    for (final t in timings) {
      _build.add(t.buildDuration.inMicroseconds / 1000.0);
      _raster.add(t.rasterDuration.inMicroseconds / 1000.0);
    }
  }

  void _report() {
    if (_build.isEmpty) return; // skip idle windows
    debugPrint(perfSummaryLine(_build, _raster));
    _build.clear();
    _raster.clear();
  }

  /// Stop recording (rarely needed — it's meant to run for the whole session).
  void stop() {
    _timer?.cancel();
    _timer = null;
    if (_started) {
      WidgetsBinding.instance.removeTimingsCallback(_onTimings);
      _started = false;
    }
  }
}
