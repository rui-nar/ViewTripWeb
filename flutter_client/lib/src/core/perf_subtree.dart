/// Times the *layout and paint* of a widget subtree — issue #276.
///
/// Every other instrument in this app measures work we wrote: [PerfSpans.blocking]
/// wraps a build callback, [PerfSpans.stage] wraps a fetch or a decode. None of
/// them can see the framework's own layout and paint, and
/// `FrameTiming.buildDuration` lumps build, layout and paint into one number —
/// so a 2437 ms frame was traced to work outside every span, and the report
/// could only say `worst frame ran: (no instrumented work)`.
///
/// That blind spot is exactly the size of `flutter_map`'s per-frame cost: it
/// re-walks every point of every polyline overlapping the viewport and
/// repositions every marker, on every camera frame, and none of that is our
/// code. Wrapping the map subtree in a [PerfSubtree] makes it a named number,
/// so raising the client's point budget can be *measured* rather than guessed.
library;

import 'package:flutter/rendering.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter/widgets.dart';

import 'perf_timing.dart';

/// Reports the layout and paint time of [child] to [perfSpans] under
/// `<name>_layout` and `<name>_paint`, aggregated per frame.
///
/// Layout-transparent: [RenderPerfSubtree] is a [RenderProxyBox], so the child
/// sees the same constraints, occupies the same size and paints at the same
/// offset it would without the wrapper. Nesting is allowed and the outer name
/// simply includes the inner one's time, exactly as the framework's own
/// recursion does.
class PerfSubtree extends SingleChildRenderObjectWidget {
  const PerfSubtree({super.key, required this.name, required Widget super.child});

  /// Span prefix. Kept short — it is read off a phone screen.
  final String name;

  @override
  RenderPerfSubtree createRenderObject(BuildContext context) =>
      RenderPerfSubtree(name);

  @override
  void updateRenderObject(BuildContext context, RenderPerfSubtree renderObject) {
    renderObject.spanName = name;
  }
}

/// The render object behind [PerfSubtree]. Public so a test can drive
/// [performLayout]/[paint] directly rather than through a pumped frame.
class RenderPerfSubtree extends RenderProxyBox {
  RenderPerfSubtree(this.spanName);

  String spanName;

  /// Identity of the frame currently being produced, so [PerfSpans] can tell
  /// one frame's samples from the next. Null outside a frame (a manual
  /// `layout()` call, a test), which is itself a usable identity.
  Object get _frameId =>
      SchedulerBinding.instance.currentFrameTimeStamp;

  @override
  void performLayout() {
    // The disabled path costs one field read and a branch — no Stopwatch is
    // allocated, and this runs on every frame of every gesture.
    if (!perfSpans.enabled) {
      super.performLayout();
      return;
    }
    final sw = Stopwatch()..start();
    try {
      super.performLayout();
    } finally {
      perfSpans.recordFrameSpan(
          '${spanName}_layout', sw.elapsedMicroseconds / 1000.0, _frameId);
    }
  }

  @override
  void paint(PaintingContext context, Offset offset) {
    if (!perfSpans.enabled) {
      super.paint(context, offset);
      return;
    }
    final sw = Stopwatch()..start();
    try {
      super.paint(context, offset);
    } finally {
      perfSpans.recordFrameSpan(
          '${spanName}_paint', sw.elapsedMicroseconds / 1000.0, _frameId);
    }
  }
}
