/// Pure geometry for the resizable activity panel (see [AppScreen]). Kept free
/// of any `dart:html` / widget dependency so it is unit-testable headless.
library;

/// Min / max width the wide-layout activity panel can be dragged to, and the
/// width always reserved for the map so it stays usable.
const double kMinPanelWidth = 220;
const double kMaxPanelWidth = 640;
const double kMinMapWidth = 320;

/// New panel width after dragging the divider by [dx] from [current], within
/// [available] total width. Clamped to [kMinPanelWidth]..[kMaxPanelWidth] and
/// never so wide that the map drops below [kMinMapWidth].
double clampPanelWidth({
  required double current,
  required double dx,
  required double available,
}) {
  final maxW =
      (available - kMinMapWidth).clamp(kMinPanelWidth, kMaxPanelWidth).toDouble();
  return (current + dx).clamp(kMinPanelWidth, maxW).toDouble();
}
