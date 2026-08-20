/// Vertical day carousel (issue #199) — view-mode only.
///
/// Scrolls through the trip's days on the right edge of the map; the
/// centered day becomes the active map selection (same `selectedDays`
/// mechanism the manage-mode activity panel and map selection-stats overlay
/// already use), so existing highlight/auto-zoom behaviour applies for free.
/// Idle-dims and retracts toward the screen edge to stay unobtrusive.
library;

import 'dart:async' show Timer;

import 'package:flutter/material.dart';

import '../core/design_tokens.dart' show kShadow2, monoStyle;
import 'project_notifier.dart';

/// Pure index → day-key mapping for [DayCarousel]'s `onSelectedItemChanged`,
/// extracted so the selection logic can be tested without driving a real
/// [ListWheelScrollView] scroll gesture.
@visibleForTesting
String? dayCarouselSelection(int index, List<String> days) =>
    (index >= 0 && index < days.length) ? days[index] : null;

class DayCarousel extends StatefulWidget {
  final ProjectNotifier notifier;

  const DayCarousel({super.key, required this.notifier});

  @override
  State<DayCarousel> createState() => _DayCarouselState();
}

class _DayCarouselState extends State<DayCarousel> {
  static const _idleDelay = Duration(seconds: 3);
  static const _animDuration = Duration(milliseconds: 280);

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
  static const _selectDebounceDelay = Duration(milliseconds: 120);

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
    // Compact strip (day number only, no distance/climb) below this width —
    // issue #199 responsive requirement.
    final compact = MediaQuery.sizeOf(context).width < 720;
    final itemExtent = compact ? 44.0 : 64.0;
    final width = compact ? 52.0 : 92.0;

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
              margin: const EdgeInsets.symmetric(vertical: 12),
              decoration: BoxDecoration(
                color: cs.surface.withValues(alpha: 0.94),
                borderRadius: const BorderRadius.only(
                  topRight: Radius.circular(12),
                  bottomRight: Radius.circular(12),
                ),
                boxShadow: kShadow2(Theme.of(context).brightness),
              ),
              // Clipping lives on this inner rect, not the Container above —
              // Container's own clipBehavior would clip its BoxDecoration's
              // boxShadow away along with the content (the shadow paints
              // outside the decoration's shape, so it'd be cut by the same
              // clip path).
              child: ClipRRect(
                borderRadius: const BorderRadius.only(
                  topRight: Radius.circular(12),
                  bottomRight: Radius.circular(12),
                ),
                child: ListWheelScrollView.useDelegate(
                  controller: _scrollController,
                  itemExtent: itemExtent,
                  diameterRatio: 10,
                  useMagnifier: true,
                  magnification: 1.18,
                  physics: const FixedExtentScrollPhysics(),
                  onSelectedItemChanged: (i) => _onSelectedItemChanged(i, days),
                  childDelegate: ListWheelChildBuilderDelegate(
                    childCount: days.length,
                    builder: (context, index) => _DayCard(
                      notifier: widget.notifier,
                      dateKey: days[index],
                      orderedDays: days,
                      compact: compact,
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
  final ProjectNotifier notifier;
  final String dateKey;
  final List<String> orderedDays;
  final bool compact;

  const _DayCard({
    required this.notifier,
    required this.dateKey,
    required this.orderedDays,
    required this.compact,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final n = dayTripNumbering(dateKey, orderedDays, notifier.tripStart);
    final stats = notifier.dayStats(dateKey);
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            '${n.dayNumber}',
            style: monoStyle(
              fontSize: compact ? 14 : 17,
              fontWeight: FontWeight.w700,
              color: cs.onSurface,
            ),
          ),
          if (!compact) ...[
            const SizedBox(height: 2),
            Text('${stats.distanceKm.round()} km',
                style: monoStyle(fontSize: 9.5, color: cs.onSurfaceVariant)),
            Text('${stats.elevationM.round()} m',
                style: monoStyle(fontSize: 9.5, color: cs.onSurfaceVariant)),
          ],
        ],
      ),
    );
  }
}
