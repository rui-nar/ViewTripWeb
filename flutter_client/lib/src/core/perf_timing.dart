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

/// Dev diagnostic: when true, AppScreen renders a flat placeholder instead of
/// the map. Lets a scroll measurement isolate whether the raster cost is the
/// map or the activity list. False (and dropped) in every normal build.
const bool kPerfNoMap = bool.fromEnvironment('PERF_NO_MAP');

/// 60 fps frame budget in milliseconds.
const double kFrameBudgetMs = 1000.0 / 60.0; // 16.67

/// A one-line, bounded description of a thrown object, for the failure report.
/// `toString()` is used deliberately rather than type-switching: ApiException
/// already prints its status code, and this file must not import the API
/// layer to find that out.
String perfDescribeError(Object e) {
  final text = e.toString().replaceAll(RegExp(r'\s+'), ' ').trim();
  return text.length <= 120 ? text : '${text.substring(0, 117)}...';
}

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

// ── Named phase spans (issue #291) ───────────────────────────────────────────
//
// Frame percentiles above answer "was that window janky"; they cannot answer
// "which pipeline stage caused it". Every phase of the map-load plan
// (docs/PERF_MAP_LOAD.md) needs a before/after number attached to a specific
// stage, so the load path is instrumented with named spans instead.
//
// Two kinds, deliberately distinct — conflating them is what makes most
// "perf timing" harnesses lie:
//
//   * BLOCKING spans ([PerfSpans.blocking]) wrap *synchronous* work and
//     measure UI-isolate stall. These are the jank numbers, and the only ones
//     a frame-budget assertion may be made against.
//   * STAGE spans ([PerfSpans.stage]) wrap async work and measure wall clock,
//     which includes awaits and isolate hops. A 3 s `decode_geo` stage that
//     ran entirely on a worker isolate costs zero frames — useful for
//     time-to-interactive, meaningless for jank.

/// One line per recorded span: count, total, worst. Pure + testable, mirroring
/// [perfSummaryLine]'s split so the numbers read off a dev run are trustworthy.
/// [label] distinguishes the two buckets in the printed report.
String perfSpanReport(String label, Map<String, List<double>> spans) {
  if (spans.isEmpty) return '[perf] $label (none)';
  // Worst-first: the line that matters is always at the top.
  final names = spans.keys.toList()
    ..sort((a, b) => _spanMax(spans[b]!).compareTo(_spanMax(spans[a]!)));
  final buf = StringBuffer('[perf] $label');
  for (final name in names) {
    final samples = spans[name]!;
    if (samples.isEmpty) continue;
    var total = 0.0;
    for (final s in samples) {
      total += s;
    }
    buf.write('\n  $name  n=${samples.length}  '
        'total=${total.toStringAsFixed(1)}ms  '
        'worst=${_spanMax(samples).toStringAsFixed(1)}ms');
  }
  return buf.toString();
}

double _spanMax(List<double> samples) {
  var max = 0.0;
  for (final s in samples) {
    if (s > max) max = s;
  }
  return max;
}

/// Names of every blocking span that blew [kFrameBudgetMs]. Pure + testable —
/// this is the assertion the load-pipeline regression tests are written
/// against, so it must not depend on a frame pipeline or a wall clock.
List<String> perfOverBudgetSpans(Map<String, List<double>> blockingSpans,
    {double budgetMs = kFrameBudgetMs}) {
  final over = <String>[];
  for (final entry in blockingSpans.entries) {
    if (_spanMax(entry.value) > budgetMs) over.add(entry.key);
  }
  over.sort();
  return over;
}

/// Records named load-pipeline spans. See the block comment above for why
/// blocking and stage timings are kept in separate buckets.
///
/// Unlike [PerfTiming], this is not `kPerfTiming`-gated at the const level:
/// [enabled] is a mutable field so tests can turn it on. The production cost
/// is one field read and a branch per *stage* — these wrap multi-millisecond
/// fetches and decodes, never per-point loops — which is well below the noise
/// floor of the work they measure.
class PerfSpans {
  PerfSpans._();
  static final PerfSpans instance = PerfSpans._();

  /// Recording is on in every build, not just `--dart-define=PERF_TIMING`
  /// ones. Each span wraps a multi-millisecond fetch, decode or build, so a
  /// Stopwatch and a map insert sit far below the noise floor of what they
  /// measure — and [lastReport] is surfaced in-app (Settings -> Performance)
  /// precisely so a real device can be diagnosed without a debugger attached,
  /// which a dart-define-gated debugPrint cannot do.
  bool enabled = true;

  final Map<String, List<double>> _blocking = {};
  final Map<String, List<double>> _stage = {};
  final Map<String, String> _notes = {};
  final Map<String, List<String>> _failures = {};

  // ── Frames during map gestures ─────────────────────────────────────────
  // Every span above measures *loading*. The ANR on issue #276 happens while
  // panning, and nothing measured that window — three rounds of fixes were
  // aimed at load-time work on the strength of load-time numbers. These
  // capture the gesture itself: a pan that drops frames shows up here even
  // when every load span is comfortably under budget.
  bool _framesHooked = false;
  bool _inGesture = false;
  int _gestures = 0;
  final List<double> _gestureBuild = [];
  final List<double> _gestureRaster = [];

  /// Bounded so a long session cannot grow this without limit; the worst
  /// frame is what matters, and trimming the oldest keeps it.
  static const _kMaxGestureFrames = 4000;

  /// Called when the map camera starts moving — see
  /// `ProjectNotifier.setMapCameraActive`, which drives both.
  void beginGesture() {
    if (!enabled) return;
    _hookFrames();
    if (_inGesture) return;
    _inGesture = true;
    _gestures++;
  }

  void endGesture() => _inGesture = false;

  void _hookFrames() {
    if (_framesHooked) return;
    try {
      WidgetsBinding.instance.addTimingsCallback(_onGestureFrames);
      _framesHooked = true;
    } catch (_) {
      // No binding (a plain unit test) — frame capture simply stays off.
    }
  }

  void _onGestureFrames(List<FrameTiming> timings) {
    if (!_inGesture) return;
    for (final t in timings) {
      _gestureBuild.add(t.buildDuration.inMicroseconds / 1000.0);
      _gestureRaster.add(t.rasterDuration.inMicroseconds / 1000.0);
    }
    if (_gestureBuild.length > _kMaxGestureFrames) {
      _gestureBuild.removeRange(0, _gestureBuild.length - _kMaxGestureFrames);
      _gestureRaster.removeRange(0, _gestureRaster.length - _kMaxGestureFrames);
    }
  }

  /// Frames captured while the map camera was moving.
  ({int gestures, List<double> build, List<double> raster}) get gestureFrames =>
      (
        gestures: _gestures,
        build: List.unmodifiable(_gestureBuild),
        raster: List.unmodifiable(_gestureRaster),
      );

  /// UI-isolate stall of a synchronous [body], recorded under [name].
  T blocking<T>(String name, T Function() body) {
    if (!enabled) return body();
    final sw = Stopwatch()..start();
    try {
      return body();
    } finally {
      (_blocking[name] ??= []).add(sw.elapsedMicroseconds / 1000.0);
    }
  }

  /// Wall-clock duration of an async [body], recorded under [name]. Includes
  /// awaits and isolate hops, so this is NOT a jank measurement.
  /// Wall-clock duration of an async [body], recorded under [name]. Includes
  /// awaits and isolate hops, so this is NOT a jank measurement.
  ///
  /// A failure is recorded too, and separately. The duration alone is
  /// actively misleading without it: a span timed in a `finally` is written
  /// whether the body returned or threw, so a failing fetch and a slow
  /// successful one are indistinguishable. On issue #276 that is exactly what
  /// happened — `fetch_geo` showed 5.1 s twice with no decode after it, and
  /// the report gave no way to tell a slow server from a failing one.
  Future<T> stage<T>(String name, Future<T> Function() body) async {
    if (!enabled) return body();
    final sw = Stopwatch()..start();
    try {
      return await body();
    } on Object catch (e) {
      (_failures[name] ??= []).add(perfDescribeError(e));
      rethrow;
    } finally {
      (_stage[name] ??= []).add(sw.elapsedMicroseconds / 1000.0);
    }
  }

  /// Snapshot of recorded UI-isolate stalls, keyed by span name.
  Map<String, List<double>> get blockingSpans =>
      {for (final e in _blocking.entries) e.key: List.unmodifiable(e.value)};

  /// Snapshot of recorded wall-clock stage durations, keyed by span name.
  Map<String, List<double>> get stageSpans =>
      {for (final e in _stage.entries) e.key: List.unmodifiable(e.value)};

  /// Records a non-timing fact about this load — a payload size, a cache
  /// verdict. A duration alone cannot distinguish a big payload on a slow
  /// link from a slow server, and those have entirely different fixes.
  void note(String name, String value) {
    if (!enabled) return;
    _notes[name] = value;
  }

  Map<String, String> get notes => Map.unmodifiable(_notes);

  /// Failures per stage, newest last.
  Map<String, List<String>> get failures =>
      {for (final e in _failures.entries) e.key: List.unmodifiable(e.value)};

  void reset() {
    _blocking.clear();
    _stage.clear();
    _notes.clear();
    _failures.clear();
    _gestureBuild.clear();
    _gestureRaster.clear();
    _gestures = 0;
  }

  /// The most recently completed load's report, or null if none has finished
  /// in this session. A [ValueNotifier] so a Settings screen left open across
  /// a load updates itself.
  final ValueNotifier<String?> lastReport = ValueNotifier<String?>(null);

  /// Snapshots both buckets into [lastReport] (and prints them on a
  /// PERF_TIMING build). Called once per load, after the background phases
  /// finish; a no-op when nothing was recorded.
  void report() {
    if (_blocking.isEmpty && _stage.isEmpty) return;
    final text = perfFullReport(_blocking, _stage, _notes,
        failures: _failures,
        gestures: _gestures,
        gestureBuild: _gestureBuild,
        gestureRaster: _gestureRaster);
    lastReport.value = text;
    if (kPerfTiming) debugPrint(text);
  }
}

/// The full report for one load: UI-isolate stalls, wall-clock stages, and an
/// explicit over-budget verdict. Pure + testable — this is what a user reads
/// off Settings -> Performance and pastes into an issue, so its shape is
/// pinned rather than incidental.
String perfLoadReport(Map<String, List<double>> blocking,
        Map<String, List<double>> stage,
        [Map<String, String> notes = const {}]) =>
    perfFullReport(blocking, stage, notes);

/// [perfLoadReport] plus the map-gesture frame summary. A separate entry
/// point so the three-argument form, and its tests, keep working.
String perfFullReport(
  Map<String, List<double>> blocking,
  Map<String, List<double>> stage,
  Map<String, String> notes, {
  Map<String, List<String>> failures = const {},
  int gestures = 0,
  List<double> gestureBuild = const [],
  List<double> gestureRaster = const [],
}) {
  final buf = StringBuffer()
    ..writeln(perfSpanReport('blocking (UI isolate)', blocking))
    ..writeln(perfSpanReport('stages (wall clock)', stage));
  if (gestures > 0) {
    buf
      ..writeln('[perf] map gestures: $gestures')
      ..writeln('  ${perfSummaryLine(gestureBuild, gestureRaster)}');
  }
  if (failures.isNotEmpty) {
    buf.writeln('[perf] FAILURES');
    final names = failures.keys.toList()..sort();
    for (final n in names) {
      final errs = failures[n]!;
      buf.writeln('  $n  x${errs.length}  ${errs.last}');
    }
  }
  if (notes.isNotEmpty) {
    buf.writeln('[perf] payloads');
    final names = notes.keys.toList()..sort();
    for (final n in names) {
      buf.writeln('  $n  ${notes[n]}');
    }
  }
  final over = perfOverBudgetSpans(blocking);
  buf.write(over.isEmpty
      ? '[perf] no UI-isolate span over '
          '${kFrameBudgetMs.toStringAsFixed(1)}ms'
      : '[perf] OVER BUDGET (>${kFrameBudgetMs.toStringAsFixed(1)}ms on the '
          'UI isolate): ${over.join(', ')}');
  return buf.toString();
}

/// Shorthand for the instrumentation call sites.
PerfSpans get perfSpans => PerfSpans.instance;
