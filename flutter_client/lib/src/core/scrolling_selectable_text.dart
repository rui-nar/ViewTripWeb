/// A single-line [Text] that, when both selected and too long to fit, plays
/// a short marquee (scroll out, pause, scroll back, pause) so the full label
/// becomes readable, then holds still — it never loops indefinitely. On web
/// it also offers the full text as a hover [Tooltip] when truncated.
library;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';

/// Renders [text] as ellipsized, single-line text. While [isSelected] and the
/// text overflows its available width, it scrolls out and back once (a short
/// "marquee") before settling back at the start — never repeating on its own.
class ScrollingSelectableText extends StatefulWidget {
  const ScrollingSelectableText({
    super.key,
    required this.text,
    required this.isSelected,
    this.style,
    this.textAlign = TextAlign.start,
    bool? showTooltipOnWeb,
    this.pixelsPerSecond = 40,
    this.pauseDuration = const Duration(milliseconds: 700),
  }) : showTooltipOnWeb = showTooltipOnWeb ?? kIsWeb;

  final String text;
  final bool isSelected;
  final TextStyle? style;
  final TextAlign textAlign;

  /// Whether a hover [Tooltip] with the full text is offered when truncated.
  /// Defaults to [kIsWeb]; overridable so widget tests can force either
  /// branch without depending on the real (compile-time) platform.
  final bool showTooltipOnWeb;

  /// Marquee scroll speed.
  final double pixelsPerSecond;

  /// How long the text pauses at each end of a pass.
  final Duration pauseDuration;

  @override
  State<ScrollingSelectableText> createState() =>
      _ScrollingSelectableTextState();
}

class _ScrollingSelectableTextState extends State<ScrollingSelectableText>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  Animation<double>? _offset;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(vsync: this);
  }

  @override
  void didUpdateWidget(ScrollingSelectableText oldWidget) {
    super.didUpdateWidget(oldWidget);
    final justDeselected = oldWidget.isSelected && !widget.isSelected;
    final textChanged = oldWidget.text != widget.text;
    if (justDeselected || textChanged) {
      _controller.stop();
      _controller.value = 0;
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _maybeStartSequence(double distance) {
    if (!widget.isSelected || _controller.value != 0 || _controller.isAnimating) {
      return;
    }
    final isRtl = Directionality.of(context) == TextDirection.rtl;
    final pauseMs = widget.pauseDuration.inMilliseconds;
    final scrollMs =
        (distance / widget.pixelsPerSecond * 1000).clamp(1200, 6000).round();
    _controller.duration =
        Duration(milliseconds: pauseMs * 3 + scrollMs * 2);
    final signedDistance = isRtl ? distance : -distance;
    _offset = TweenSequence<double>([
      TweenSequenceItem(weight: pauseMs.toDouble(), tween: ConstantTween(0.0)),
      TweenSequenceItem(
        weight: scrollMs.toDouble(),
        tween: Tween(begin: 0.0, end: signedDistance)
            .chain(CurveTween(curve: Curves.easeInOut)),
      ),
      TweenSequenceItem(
        weight: pauseMs.toDouble(),
        tween: ConstantTween(signedDistance),
      ),
      TweenSequenceItem(
        weight: scrollMs.toDouble(),
        tween: Tween(begin: signedDistance, end: 0.0)
            .chain(CurveTween(curve: Curves.easeInOut)),
      ),
      TweenSequenceItem(weight: pauseMs.toDouble(), tween: ConstantTween(0.0)),
    ]).animate(_controller);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _controller.forward(from: 0);
    });
  }

  @override
  Widget build(BuildContext context) {
    final effectiveStyle =
        DefaultTextStyle.of(context).style.merge(widget.style);
    return LayoutBuilder(
      builder: (context, constraints) {
        final painter = TextPainter(
          text: TextSpan(text: widget.text, style: effectiveStyle),
          maxLines: 1,
          textDirection: Directionality.of(context),
          textScaler: MediaQuery.textScalerOf(context),
        )..layout();
        final overflowing = painter.width > constraints.maxWidth + 0.5;
        final distance = painter.width - constraints.maxWidth;

        Widget content;
        if (overflowing && widget.isSelected) {
          _maybeStartSequence(distance);
          content = ClipRect(
            key: const ValueKey('scrolling-text-marquee-active'),
            child: SizedBox(
              width: constraints.maxWidth,
              height: painter.height,
              child: AnimatedBuilder(
                animation: _controller,
                builder: (context, child) => Transform.translate(
                  offset: Offset(_offset?.value ?? 0, 0),
                  child: child,
                ),
                child: Text(
                  widget.text,
                  style: effectiveStyle,
                  textAlign: widget.textAlign,
                  maxLines: 1,
                  softWrap: false,
                  overflow: TextOverflow.visible,
                ),
              ),
            ),
          );
        } else {
          content = Text(
            widget.text,
            style: widget.style,
            textAlign: widget.textAlign,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          );
        }

        if (widget.showTooltipOnWeb && overflowing) {
          content = Tooltip(message: widget.text, child: content);
        }

        return Semantics(
          label: widget.text,
          child: ExcludeSemantics(child: content),
        );
      },
    );
  }
}
