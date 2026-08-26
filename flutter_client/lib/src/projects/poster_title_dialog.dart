/// Title-configuration dialog for the poster export (issue #14 follow-up):
/// shown between `PosterConfigDialog`'s confirm and the layout preview, so
/// the user can place the trip-summary/title card, override its text and
/// resize it before generating anything. Mirrors `poster_config_dialog.dart`'s
/// conventions: an `AlertDialog` confirming with an options object via
/// `onConfirm`, with an options class carrying a `toJson()`.
library;

import 'package:flutter/material.dart';

import 'map_panel.dart' show kA0PortraitAspect;

/// Position/text/scale for the poster's title (trip-summary) card. Matches
/// `PosterRequest`'s `title_position`/`title_text`/`title_scale` fields in
/// `api/poster.py` — top-level request fields, alongside `orientation`/
/// `paper_size`, not part of `PosterConfigIn`.
class PosterTitleOptions {
  /// Normalized (0-1) position of the title card's top-left corner within
  /// the poster's drawable area. ``(0, 0)`` is the poster's default top-left
  /// corner.
  final double positionX;
  final double positionY;

  /// Overrides the card's title text; null (or blank) falls back to the
  /// project's own name server-side.
  final String? titleText;

  /// Multiplier on the base "hero_title" size. Clamped to 0.5x-2.0x here and
  /// again server-side (the API is the trust boundary, not this slider).
  final double titleScale;

  const PosterTitleOptions({
    this.positionX = 0.0,
    this.positionY = 0.0,
    this.titleText,
    this.titleScale = 1.0,
  });

  /// Matches `PosterRequest`'s top-level field names in `api/poster.py`.
  Map<String, dynamic> toJson() => {
        'title_position': {'x': positionX, 'y': positionY},
        'title_text': titleText,
        'title_scale': titleScale,
      };
}

/// Safe range for the title-size slider — a bounded relative multiplier on
/// the poster's own base title size, not a raw point size (matches
/// `api/poster.py`'s clamp).
const double kTitleScaleMin = 0.5;
const double kTitleScaleMax = 2.0;

/// Placeholder footprint of the draggable title box, as a fraction of the
/// poster outline shown in this dialog. An approximation for the drag
/// preview only — not a measurement of the real trip-summary card, which is
/// sized to its actual content server-side (card_layout.layout_card).
const double _kTitleBoxWidthFraction = 0.34;
const double _kTitleBoxHeightFraction = 0.14;

/// Fixed height budget for the poster outline area, so a portrait poster's
/// tall aspect ratio can't blow the dialog out to an unusable height — the
/// outline shrinks to fit within this, centred, same idea as the on-map
/// frame picker's own fit-to-box sizing (`frameRectFor` in map_panel.dart).
const double _kOutlineHeight = 150.0;

/// The poster outline's rect, centred and fitted (shrunk if needed) within
/// *box* at *orientation*'s aspect ratio.
Rect _outlineRectFor(Size box, String orientation) {
  final aspect =
      orientation == 'portrait' ? kA0PortraitAspect : 1 / kA0PortraitAspect;
  double w = box.width;
  double h = w / aspect;
  if (h > box.height) {
    h = box.height;
    w = h * aspect;
  }
  return Rect.fromLTWH((box.width - w) / 2, (box.height - h) / 2, w, h);
}

class PosterTitleDialog extends StatefulWidget {
  /// The poster's chosen orientation ('landscape'/'portrait'), so the outline
  /// this dialog shows matches the shape already picked in the frame picker.
  final String orientation;

  /// Default title text — the project's own name.
  final String initialTitle;

  final void Function(PosterTitleOptions) onConfirm;

  const PosterTitleDialog({
    super.key,
    required this.orientation,
    required this.initialTitle,
    required this.onConfirm,
  });

  @override
  State<PosterTitleDialog> createState() => _PosterTitleDialogState();
}

class _PosterTitleDialogState extends State<PosterTitleDialog> {
  late final TextEditingController _textController =
      TextEditingController(text: widget.initialTitle);
  double _x = 0.0;
  double _y = 0.0;
  double _scale = 1.0;

  @override
  void dispose() {
    _textController.dispose();
    super.dispose();
  }

  void _onDragUpdate(DragUpdateDetails details, Size areaSize) {
    setState(() {
      _x = (_x + details.delta.dx / areaSize.width).clamp(0.0, 1.0);
      _y = (_y + details.delta.dy / areaSize.height).clamp(0.0, 1.0);
    });
  }

  void _confirm() {
    final text = _textController.text.trim();
    final opts = PosterTitleOptions(
      positionX: _x,
      positionY: _y,
      titleText: text.isEmpty ? null : text,
      titleScale: _scale,
    );
    Navigator.of(context).pop();
    widget.onConfirm(opts);
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    return AlertDialog(
      title: const Text('Title card'),
      content: SizedBox(
        width: 360,
        // Deliberately not a SingleChildScrollView: the drag box's pan
        // gesture would have to compete with a scrollable ancestor's own
        // vertical drag recognizer for the same pointer. The outline's fixed
        // height budget (_kOutlineHeight) keeps total content short enough
        // that nothing here needs to scroll.
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Drag the title card to where it should sit on the poster.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 8),
            SizedBox(
              height: _kOutlineHeight,
              width: double.infinity,
              child: LayoutBuilder(builder: (context, constraints) {
                final outline = _outlineRectFor(
                  Size(constraints.maxWidth, constraints.maxHeight),
                  widget.orientation,
                );
                final areaSize = outline.size;
                final boxW = areaSize.width * _kTitleBoxWidthFraction;
                final boxH = areaSize.height * _kTitleBoxHeightFraction;
                final left = outline.left + _x * (areaSize.width - boxW);
                final top = outline.top + _y * (areaSize.height - boxH);
                return Stack(
                  children: [
                    Positioned.fromRect(
                      rect: outline,
                      child: DecoratedBox(
                        decoration: BoxDecoration(
                          border: Border.all(color: cs.outline),
                          color: cs.surfaceContainerHighest,
                        ),
                      ),
                    ),
                    Positioned(
                      left: left,
                      top: top,
                      width: boxW,
                      height: boxH,
                      child: GestureDetector(
                        onPanUpdate: (details) =>
                            _onDragUpdate(details, areaSize),
                        child: DecoratedBox(
                          decoration: BoxDecoration(
                            color: cs.primaryContainer,
                            border: Border.all(color: cs.primary, width: 2),
                          ),
                          child: Center(
                            child: Icon(Icons.drag_indicator,
                                color: cs.onPrimaryContainer),
                          ),
                        ),
                      ),
                    ),
                  ],
                );
              }),
            ),
            const SizedBox(height: 16),
            Text('Title text', style: Theme.of(context).textTheme.labelMedium),
            const SizedBox(height: 6),
            TextField(
              controller: _textController,
              decoration: const InputDecoration(
                isDense: true,
                border: OutlineInputBorder(),
                hintText: 'Trip title',
              ),
            ),
            const SizedBox(height: 16),
            Text('Title size: ${_scale.toStringAsFixed(2)}x',
                style: Theme.of(context).textTheme.labelMedium),
            Slider(
              value: _scale,
              min: kTitleScaleMin,
              max: kTitleScaleMax,
              divisions: 30,
              label: '${_scale.toStringAsFixed(2)}x',
              onChanged: (v) => setState(() => _scale = v),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: _confirm,
          child: const Text('Preview'),
        ),
      ],
    );
  }
}
