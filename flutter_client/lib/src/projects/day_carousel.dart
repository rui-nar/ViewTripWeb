/// Vertical day carousel (issue #199) — view-mode only.
///
/// A transparent, pill-shaped overlay docked to the right edge of the map.
/// Scrolls through the trip's days; the centered day becomes the active map
/// selection via `notifier.selectDays()`, so `MapPanel`'s highlight/
/// auto-zoom-to-selection behaviour (also added for view mode by this same
/// change — see map_panel.dart) applies. Idle-dims and retracts toward the
/// screen edge to stay unobtrusive.
library;

import 'dart:async' show Timer;
import 'dart:ui' show lerpDouble;

import 'package:flutter/material.dart';

import '../core/design_tokens.dart' show kShadow2, monoStyle;
import 'project_notifier.dart';

/// Pure index → day-key mapping for [DayCarousel]'s `onSelectedItemChanged`,
/// extracted so the selection logic can be tested without driving a real
/// [ListWheelScrollView] scroll gesture.
@visibleForTesting
String? dayCarouselSelection(int index, List<String> days) =>
    (index >= 0 && index < days.length) ? days[index] : null;

/// Scale multiplier for a card [distanceInSlots] away from the centered
/// (highlighted) item — 1.0 at rest, growing to [DayCarousel.magnification]
/// at the center, linearly over one slot. Extracted for testing.
@visibleForTesting
double dayCarouselScale(double distanceInSlots, double magnification) {
  final t = (1 - distanceInSlots).clamp(0.0, 1.0);
  return lerpDouble(1.0, magnification, t)!;
}

class DayCarousel extends StatefulWidget {
  final ProjectNotifier notifier;

  /// Scale factor applied to the centered card's text relative to a
  /// neighboring (unselected) card — issue #199 feedback: "2x bigger".
  final double magnification;

  const DayCarousel({
    super.key,
    required this.notifier,
    this.magnification = 2.0,
  });

  @override
  State<DayCarousel> createState() => _DayCarouselState();
}

class _DayCarouselState extends State<DayCarousel> {
  static const _idleDelay = Duration(seconds: 3);
  static const _animDuration = Duration(milliseconds: 280);
  static const _selectDebounceDelay = Duration(milliseconds: 120);

  bool _revealed = true;
  Timer? _idleTimer;
  Timer? _selectDebounce;
  late FixedExtentScrollController _scrollController;

  int _activeIndex(List<String> days) {
    final active = widget.notifier.selectedDays.isNotEmpty
        ? widget.notifier.selectedDays.first
        : widget.notifier.selectedDay;
    if (active == null) return 0;
    final i = days.indexOf(active);
    return i >= 0 ? i : 0;
  }

  @override
  void initState() {
    super.initState();
    _scrollController = FixedExtentScrollController(
      initialItem: _activeIndex(widget.notifier.orderedDayKeys()),
    );
    _scheduleRetract();
  }

  @override
  void didUpdateWidget(covariant DayCarousel oldWidget) {
    super.didUpdateWidget(oldWidget);
    // Defensive: if a future caller ever swaps in a different notifier
    // without remounting this widget's State (today's callers always
    // remount — see ViewScreen's ChangeNotifierProvider), re-center the
    // wheel on the new notifier's active day instead of leaving the old
    // project's scroll position/index behind.
    if (!identical(widget.notifier, oldWidget.notifier) &&
        _scrollController.hasClients) {
      _scrollController.jumpToItem(_activeIndex(widget.notifier.orderedDayKeys()));
    }
  }

  @override
  void dispose() {
    _idleTimer?.cancel();
    _selectDebounce?.cancel();
    _scrollController.dispose();
    super.dispose();
  }

  void _reveal() {
    _idleTimer?.cancel();
    if (!_revealed) setState(() => _revealed = true);
    _scheduleRetract();
  }

  void _scheduleRetract() {
    _idleTimer?.cancel();
    _idleTimer = Timer(_idleDelay, () {
      if (mounted) setState(() => _revealed = false);
    });
  }

  // ListWheelScrollView fires onSelectedItemChanged for every index the
  // wheel crosses, including mid-fling — not just once scrolling settles.
  // Committing selectDays() (a notifyListeners(), rebuilding the map +
  // elevation chart) on each crossing would jank a fast fling, so debounce
  // to the index the wheel is actually resting on.
  void _onSelectedItemChanged(int index, List<String> days) {
    _reveal();
    _selectDebounce?.cancel();
    _selectDebounce = Timer(_selectDebounceDelay, () {
      final key = dayCarouselSelection(index, days);
      if (key != null) widget.notifier.selectDays({key});
    });
  }

  @override
  Widget build(BuildContext context) {
    final days = widget.notifier.orderedDayKeys();
    if (days.isEmpty) return const SizedBox.shrink();

    final cs = Theme.of(context).colorScheme;
    // Compact strip (bare number only, no "Day"/distance/climb) below this
    // width — issue #199 responsive requirement.
    final compact = MediaQuery.sizeOf(context).width < 720;
    final itemExtent = compact ? 52.0 : 110.0;
    // Pill/stadium shape (issue #199 feedback): radius = half the width, so
    // the right edge is one continuous curve; left edge stays square.
    final width = compact ? 64.0 : 120.0;
    final radius = width / 2;
    final pillRadius = BorderRadius.only(
      topRight: Radius.circular(radius),
      bottomRight: Radius.circular(radius),
    );

    return MouseRegion(
      onEnter: (_) => _reveal(),
      onExit: (_) => _scheduleRetract(),
      child: GestureDetector(
        // Only intercept taps while retracted, so a tap reveals the strip
        // instead of falling through to whatever's behind it; while revealed,
        // leave gesture handling to the ListWheelScrollView beneath.
        onTap: _revealed ? null : _reveal,
        behavior: HitTestBehavior.opaque,
        child: AnimatedSlide(
          duration: _animDuration,
          curve: Curves.easeInOut,
          offset: _revealed ? Offset.zero : const Offset(0.6, 0),
          child: AnimatedOpacity(
            duration: _animDuration,
            opacity: _revealed ? 1.0 : 0.4,
            child: Container(
              width: width,
              margin: const EdgeInsets.symmetric(vertical: 24),
              decoration: BoxDecoration(
                // Transparent overlay (issue #199 feedback), not a solid card.
                color: cs.surface.withValues(alpha: 0.55),
                borderRadius: pillRadius,
                boxShadow: kShadow2(Theme.of(context).brightness),
              ),
              // Clipping lives on this inner rect, not the Container above —
              // Container's own clipBehavior would clip its BoxDecoration's
              // boxShadow away along with the content (the shadow paints
              // outside the decoration's shape, so it'd be cut by the same
              // clip path).
              child: ClipRRect(
                borderRadius: pillRadius,
                // Fades the top/bottom 30% to transparent (issue #199
                // feedback) so the strip recedes into the map at its edges.
                child: ShaderMask(
                  blendMode: BlendMode.dstIn,
                  shaderCallback: (rect) => const LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [
                      Colors.transparent, Colors.white,
                      Colors.white, Colors.transparent,
                    ],
                    stops: [0.0, 0.3, 0.7, 1.0],
                  ).createShader(rect),
                  child: ListWheelScrollView.useDelegate(
                    controller: _scrollController,
                    itemExtent: itemExtent,
                    diameterRatio: 100,
                    perspective: 0.0005,
                    physics: const FixedExtentScrollPhysics(),
                    onSelectedItemChanged: (i) => _onSelectedItemChanged(i, days),
                    childDelegate: ListWheelChildBuilderDelegate(
                      childCount: days.length,
                      builder: (context, index) {
                        // dayTripNumbering()/dayStats() iterate the day/items
                        // lists — computed once per index here (called again
                        // only when this index re-enters the visible window),
                        // NOT inside the AnimatedBuilder below, which reruns
                        // every scroll frame. Only the cheap scale/highlighted
                        // check needs to track the live offset that often.
                        final dateKey = days[index];
                        final n = dayTripNumbering(
                            dateKey, days, widget.notifier.tripStart);
                        final stats = widget.notifier.dayStats(dateKey);
                        return AnimatedBuilder(
                          // Rebuilds this card every scroll tick so its
                          // scale/"Day N" state tracks the live offset — the
                          // hand-rolled replacement for ListWheelScrollView's
                          // built-in magnifier (issue #199: a true ~2x center
                          // card without clipping into its fixed-height slot).
                          animation: _scrollController,
                          builder: (context, _) {
                            final offset = _scrollController.hasClients
                                ? _scrollController.offset
                                : _activeIndex(days) * itemExtent;
                            final distance =
                                (index * itemExtent - offset).abs() / itemExtent;
                            final scale =
                                dayCarouselScale(distance, widget.magnification);
                            return _DayCard(
                              dayNumber: n.dayNumber,
                              distanceKm: stats.distanceKm,
                              elevationM: stats.elevationM,
                              compact: compact,
                              scale: scale,
                              highlighted: distance < 0.5,
                            );
                          },
                        );
                      },
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _DayCard extends StatelessWidget {
  final int dayNumber;
  final double distanceKm;
  final double elevationM;
  final bool compact;
  final double scale;
  final bool highlighted;

  const _DayCard({
    required this.dayNumber,
    required this.distanceKm,
    required this.elevationM,
    required this.compact,
    required this.scale,
    required this.highlighted,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    // "Day N" only for the highlighted card (space-constrained neighbors —
    // and in the compact strip — keep the bare number); issue #199 feedback.
    final label = highlighted && !compact ? 'Day $dayNumber' : '$dayNumber';
    final baseFontSize = compact ? 13.0 : 15.0;
    final showStats = highlighted && !compact;
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            label,
            style: monoStyle(
              // Same font used by the day-meta editor's hero + the map's
              // selection-stats overlay (both JetBrains Mono via monoStyle).
              fontSize: baseFontSize * scale,
              fontWeight: FontWeight.w600,
              color: cs.onSurface,
              letterSpacing: -0.5,
            ),
          ),
          if (showStats) ...[
            const SizedBox(height: 2),
            Text('${distanceKm.round()} km',
                style: monoStyle(fontSize: 10, color: cs.onSurfaceVariant)),
            Text('${elevationM.round()} m',
                style: monoStyle(fontSize: 10, color: cs.onSurfaceVariant)),
          ],
        ],
      ),
    );
  }
}
