/// Custom SVG-faithful icons for Memory and Journal markers.
///
/// Designs from the ViewTrip Design System handoff:
///   Memory  — stacked tilted Polaroids on a dark-red stake.
///   Journal — leather-style book with metallic blue gradient + red ribbon.
///
/// Each family exposes two widgets:
///   *MapMarker  — full-detail pin for flutter_map MarkerLayer.
///   *Glyph      — compact 24-pt icon for panel tiles and AppBar toggles.
library;

import 'dart:math' as math;
import 'dart:ui' as ui;
import 'package:flutter/material.dart';

// ─────────────────────────────────────────────────────────────────────────────
// MEMORY — Polaroid stack
// ─────────────────────────────────────────────────────────────────────────────

/// Polaroid-stack map pin for a memory.
/// Sized by the [Marker] width/height — no explicit size needed here.
class MemoryMapMarker extends StatelessWidget {
  final bool isSelected;
  final bool isDimmed;

  const MemoryMapMarker({
    super.key,
    this.isSelected = false,
    this.isDimmed = false,
  });

  @override
  Widget build(BuildContext context) => CustomPaint(
        painter: _MemoryMapMarkerPainter(
          isSelected: isSelected,
          isDimmed: isDimmed,
        ),
      );
}

class _MemoryMapMarkerPainter extends CustomPainter {
  final bool isSelected;
  final bool isDimmed;

  const _MemoryMapMarkerPainter({
    required this.isSelected,
    required this.isDimmed,
  });

  @override
  bool shouldRepaint(_MemoryMapMarkerPainter old) =>
      old.isSelected != isSelected || old.isDimmed != isDimmed;

  // Design viewBox: 60 × 68
  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(size.width / 60, size.height / 68);

    if (isDimmed) {
      canvas.saveLayer(
        const Rect.fromLTWH(0, 0, 60, 68),
        Paint()..color = Colors.white.withValues(alpha: 0.5),
      );
    }

    // Warm glow halo
    canvas.drawOval(
      const Rect.fromLTWH(2, 4, 56, 48),
      Paint()
        ..shader = ui.Gradient.radial(
          const Offset(30, 28), 28,
          [const Color(0x72FCD34D), const Color(0x00FCD34D)],
        ),
    );

    // Drop shadow under stake
    canvas.drawOval(
      const Rect.fromLTWH(19, 53.5, 22, 5),
      Paint()..color = Colors.black.withValues(alpha: 0.15),
    );

    // Pin stake: M30 50 L27 64 L30 67 L33 64 Z
    final stake = Path()
      ..moveTo(30, 50)
      ..lineTo(27, 64)
      ..lineTo(30, 67)
      ..lineTo(33, 64)
      ..close();
    canvas.drawPath(stake, Paint()..color = const Color(0xFF7F1D1D));
    canvas.drawPath(
      stake,
      Paint()
        ..color = const Color(0xFF5B0A0A)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 0.8,
    );

    // ── Back Polaroid — rotate(−14°) around (30, 28), offset (−22, −23)
    canvas.save();
    canvas.translate(30, 28);
    canvas.rotate(-14 * math.pi / 180);
    canvas.translate(-22, -23);
    _frame(canvas, 0, 0, 44, 46, 1.1);
    canvas.drawRect(
      const Rect.fromLTWH(4, 4, 36, 29),
      Paint()..color = const Color(0xFF94A3B8),
    );
    canvas.restore();

    // ── Middle Polaroid — rotate(+8°) around (30, 28), offset (−21, −22)
    canvas.save();
    canvas.translate(30, 28);
    canvas.rotate(8 * math.pi / 180);
    canvas.translate(-21, -22);
    _frame(canvas, 0, 0, 42, 44, 1.1);
    canvas.drawRect(
      const Rect.fromLTWH(3.5, 3.5, 35, 28),
      Paint()..color = const Color(0xFF66BB6A),
    );
    canvas.drawPath(
      Path()
        ..moveTo(3.5, 25)
        ..lineTo(13, 18)
        ..lineTo(21, 23)
        ..lineTo(29, 16)
        ..lineTo(38.5, 22)
        ..lineTo(38.5, 31.5)
        ..lineTo(3.5, 31.5)
        ..close(),
      Paint()..color = const Color(0xFF1B5E20),
    );
    canvas.restore();

    // ── Front Polaroid — rotate(−4°) around (30, 29), offset (−21, −23)
    canvas.save();
    canvas.translate(30, 29);
    canvas.rotate(-4 * math.pi / 180);
    canvas.translate(-21, -23);
    _frame(canvas, 0, 0, 42, 46, 1.2);

    // Sunset gradient photo
    canvas.drawRect(
      const Rect.fromLTWH(3.5, 3.5, 35, 28),
      Paint()
        ..shader = ui.Gradient.linear(
          const Offset(3.5, 3.5),
          const Offset(3.5, 31.5),
          [
            const Color(0xFFFCD34D),
            const Color(0xFFF97316),
            const Color(0xFF9F1239),
          ],
          [0.0, 0.45, 1.0],
        ),
    );
    // Sun
    canvas.drawCircle(
      const Offset(21, 15),
      3.8,
      Paint()..color = const Color(0xFFFEF3C7),
    );
    // Mountain silhouette
    canvas.drawPath(
      Path()
        ..moveTo(3.5, 26)
        ..lineTo(10, 20)
        ..lineTo(18, 23)
        ..lineTo(25, 18)
        ..lineTo(32, 22)
        ..lineTo(38.5, 19)
        ..lineTo(38.5, 31.5)
        ..lineTo(3.5, 31.5)
        ..close(),
      Paint()..color = const Color(0xFF7C2D12),
    );

    // Handwritten caption (three squiggle segments)
    // M7 38 Q9 36 11 38 T15 38  (T reflects ctrl through end)
    final capPaint = Paint()
      ..color = const Color(0xFF1E293B)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.1
      ..strokeCap = StrokeCap.round;
    canvas.drawPath(
      Path()
        ..moveTo(7, 38)
        ..quadraticBezierTo(9, 36, 11, 38)
        ..quadraticBezierTo(13, 40, 15, 38),
      capPaint,
    );
    // M17 38 Q19 37 21 38 T25 37.5
    canvas.drawPath(
      Path()
        ..moveTo(17, 38)
        ..quadraticBezierTo(19, 37, 21, 38)
        ..quadraticBezierTo(23, 39, 25, 37.5),
      capPaint,
    );
    // M27 38 L34 38
    canvas.drawPath(
      Path()
        ..moveTo(27, 38)
        ..lineTo(34, 38),
      Paint()
        ..color = const Color(0xFF1E293B)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.0
        ..strokeCap = StrokeCap.round,
    );

    // Yellow masking tape on top edge
    canvas.drawRect(
      const Rect.fromLTWH(15, -3, 12, 6),
      Paint()..color = const Color(0xFFFDE68A),
    );
    canvas.drawRect(
      const Rect.fromLTWH(15, -3, 12, 6),
      Paint()
        ..color = const Color(0x6692400E)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 0.4,
    );
    canvas.restore();

    // Sparkle accent at (52, 10) — not in the rotated group
    canvas.save();
    canvas.translate(52, 10);
    canvas.drawPath(
      Path()
        ..moveTo(0, -4)
        ..lineTo(1, -1)
        ..lineTo(4, 0)
        ..lineTo(1, 1)
        ..lineTo(0, 4)
        ..lineTo(-1, 1)
        ..lineTo(-4, 0)
        ..lineTo(-1, -1)
        ..close(),
      Paint()..color = const Color(0xFFFCD34D),
    );
    canvas.restore();

    if (isDimmed) canvas.restore();

    // Selection ring
    if (isSelected) {
      canvas.drawOval(
        const Rect.fromLTWH(2, 4, 56, 48),
        Paint()
          ..color = Colors.white.withValues(alpha: 0.9)
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2.5,
      );
    }
  }

  /// White cream frame with brown stroke around a Polaroid border.
  static void _frame(
      Canvas c, double x, double y, double w, double h, double sw) {
    final r = Rect.fromLTWH(x, y, w, h);
    c.drawRect(r, Paint()..color = const Color(0xFFFDFBF2));
    c.drawRect(
      r,
      Paint()
        ..color = const Color(0xFF8B7C5A)
        ..style = PaintingStyle.stroke
        ..strokeWidth = sw,
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// JOURNAL — Leather book with ribbon bookmark
// ─────────────────────────────────────────────────────────────────────────────

/// Metallic-blue book map pin for a journal entry.
class JournalMapMarker extends StatelessWidget {
  final bool isSelected;
  final bool isDimmed;

  const JournalMapMarker({
    super.key,
    this.isSelected = false,
    this.isDimmed = false,
  });

  @override
  Widget build(BuildContext context) => CustomPaint(
        painter: _JournalMapMarkerPainter(
          isSelected: isSelected,
          isDimmed: isDimmed,
        ),
      );
}

class _JournalMapMarkerPainter extends CustomPainter {
  final bool isSelected;
  final bool isDimmed;

  const _JournalMapMarkerPainter({
    required this.isSelected,
    required this.isDimmed,
  });

  @override
  bool shouldRepaint(_JournalMapMarkerPainter old) =>
      old.isSelected != isSelected || old.isDimmed != isDimmed;

  // Design viewBox: 54 × 60
  // Book outline: M7 8 Q7 5 10 5 L44 5 Q47 5 47 8 L47 44 L27 56 L7 44 Z
  static Path _bookOutline() => Path()
    ..moveTo(7, 8)
    ..quadraticBezierTo(7, 5, 10, 5)
    ..lineTo(44, 5)
    ..quadraticBezierTo(47, 5, 47, 8)
    ..lineTo(47, 44)
    ..lineTo(27, 56)
    ..lineTo(7, 44)
    ..close();

  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(size.width / 54, size.height / 60);

    if (isDimmed) {
      canvas.saveLayer(
        const Rect.fromLTWH(0, 0, 54, 60),
        Paint()..color = Colors.white.withValues(alpha: 0.5),
      );
    }

    // Blue glow halo
    canvas.drawOval(
      const Rect.fromLTWH(3, 8, 48, 44),
      Paint()
        ..shader = ui.Gradient.radial(
          const Offset(27, 30),
          27,
          [const Color(0x7293C5FD), const Color(0x0093C5FD)],
        ),
    );

    final outline = _bookOutline();

    // Metallic blue body
    canvas.drawPath(
      outline,
      Paint()
        ..shader = ui.Gradient.linear(
          const Offset(27, 5),
          const Offset(27, 56),
          [
            const Color(0xFF60A5FA),
            const Color(0xFF1E40AF),
            const Color(0xFF0F172A),
          ],
          [0.0, 0.55, 1.0],
        ),
    );
    canvas.drawPath(
      outline,
      Paint()
        ..color = const Color(0xFF0A2E6B)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.5
        ..strokeJoin = StrokeJoin.round,
    );

    // Metallic shine overlay
    canvas.drawPath(
      outline,
      Paint()
        ..shader = ui.Gradient.linear(
          const Offset(27, 5),
          const Offset(27, 30),
          [
            Colors.white.withValues(alpha: 0.45),
            Colors.white.withValues(alpha: 0.0),
          ],
        ),
    );

    // Stitch border (inner rect)
    canvas.drawRect(
      const Rect.fromLTWH(11, 10, 32, 30),
      Paint()
        ..color = Colors.white.withValues(alpha: 0.35)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.0,
    );

    // Open page: M14 16 L40 16 L40 34 L27 38 L14 34 Z
    final page = Path()
      ..moveTo(14, 16)
      ..lineTo(40, 16)
      ..lineTo(40, 34)
      ..lineTo(27, 38)
      ..lineTo(14, 34)
      ..close();
    canvas.drawPath(page, Paint()..color = const Color(0xFFFDFBF2));
    canvas.drawPath(
      page,
      Paint()
        ..color = const Color(0xFF0A2E6B)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 0.8,
    );

    // Handwritten swoosh lines in blue
    // M17 22 Q22 20 27 22 T37 22
    // M17 27 Q22 25 26 27 T34 27
    // M17 32 Q21 30 24 32
    final writePaint = Paint()
      ..color = const Color(0xFF1E40AF)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.2
      ..strokeCap = StrokeCap.round;
    canvas.drawPath(
      Path()
        ..moveTo(17, 22)
        ..quadraticBezierTo(22, 20, 27, 22)
        ..quadraticBezierTo(32, 24, 37, 22),
      writePaint,
    );
    canvas.drawPath(
      Path()
        ..moveTo(17, 27)
        ..quadraticBezierTo(22, 25, 26, 27)
        ..quadraticBezierTo(30, 29, 34, 27),
      writePaint,
    );
    canvas.drawPath(
      Path()
        ..moveTo(17, 32)
        ..quadraticBezierTo(21, 30, 24, 32),
      writePaint,
    );

    // Small red heart on the page
    // M31 31 C29 30,28.5 28.5,29.5 27.8 C30.2 27.3,30.8 27.6,31 28.2
    //         C31.2 27.6,31.8 27.3,32.5 27.8 C33.5 28.5,33 30,31 31 Z
    canvas.drawPath(
      Path()
        ..moveTo(31, 31)
        ..cubicTo(29, 30, 28.5, 28.5, 29.5, 27.8)
        ..cubicTo(30.2, 27.3, 30.8, 27.6, 31, 28.2)
        ..cubicTo(31.2, 27.6, 31.8, 27.3, 32.5, 27.8)
        ..cubicTo(33.5, 28.5, 33, 30, 31, 31)
        ..close(),
      Paint()..color = const Color(0xFFEF4444),
    );

    // Ribbon bookmark: M22 38 L22 54 L26 50 L30 54 L30 38 Z
    final ribbon = Path()
      ..moveTo(22, 38)
      ..lineTo(22, 54)
      ..lineTo(26, 50)
      ..lineTo(30, 54)
      ..lineTo(30, 38)
      ..close();
    canvas.drawPath(
      ribbon,
      Paint()
        ..shader = ui.Gradient.linear(
          const Offset(26, 38),
          const Offset(26, 54),
          [const Color(0xFFFB7185), const Color(0xFF9F1239)],
        ),
    );
    canvas.drawPath(
      ribbon,
      Paint()
        ..color = const Color(0xFF7F1D1D)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 0.8
        ..strokeJoin = StrokeJoin.round,
    );
    // Ribbon satin highlight
    canvas.drawPath(
      Path()
        ..moveTo(22, 38)
        ..lineTo(22, 50)
        ..lineTo(24, 50)
        ..lineTo(24, 38)
        ..close(),
      Paint()..color = Colors.white.withValues(alpha: 0.25),
    );

    if (isDimmed) canvas.restore();

    // Selection ring traces the book outline
    if (isSelected) {
      canvas.drawPath(
        _bookOutline(),
        Paint()
          ..color = Colors.white.withValues(alpha: 0.9)
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2.5
          ..strokeJoin = StrokeJoin.round,
      );
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// MEMORY GLYPH — compact Polaroid icon (24×24 viewBox, rotated −8°)
// ─────────────────────────────────────────────────────────────────────────────

/// Small Polaroid glyph for panel tiles and AppBar toggles.
///
/// [filled] true  → solid body (memories "on" / selected state)
/// [filled] false → stroke only + sparkle (memories "off" / unselected)
/// [color] defaults to crimson when filled, muted slate when outlined.
class MemoryGlyph extends StatelessWidget {
  final double size;
  final bool filled;
  final Color? color;

  const MemoryGlyph({super.key, this.size = 24, this.filled = true, this.color});

  @override
  Widget build(BuildContext context) {
    final c = color ??
        (filled
            ? const Color(0xFFDC2626)
            : Theme.of(context).colorScheme.onSurface.withValues(alpha: 0.55));
    return SizedBox(
      width: size,
      height: size,
      child: CustomPaint(painter: _MemoryGlyphPainter(filled: filled, color: c)),
    );
  }
}

class _MemoryGlyphPainter extends CustomPainter {
  final bool filled;
  final Color color;

  const _MemoryGlyphPainter({required this.filled, required this.color});

  @override
  bool shouldRepaint(_MemoryGlyphPainter old) =>
      old.filled != filled || old.color != color;

  // Design viewBox: 24 × 24; Polaroid group rotated −8° around (12, 12)
  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(size.width / 24, size.height / 24);

    // Rotate the Polaroid group
    canvas.save();
    canvas.translate(12, 12);
    canvas.rotate(-8 * math.pi / 180);
    canvas.translate(-12, -12);

    if (filled) {
      // Solid Polaroid body
      canvas.drawRect(
        const Rect.fromLTWH(3, 3, 18, 19),
        Paint()..color = color,
      );
      // Cream photo area
      canvas.drawRect(
        const Rect.fromLTWH(4.6, 4.6, 14.8, 11.5),
        Paint()..color = const Color(0xFFFDFBF2),
      );
      // Sun dot
      canvas.drawCircle(
        const Offset(10, 9),
        1.8,
        Paint()..color = const Color(0xFFFCD34D),
      );
      // Mountain horizon (semi-transparent white)
      canvas.drawPath(
        Path()
          ..moveTo(4.6, 14)
          ..lineTo(8, 11)
          ..lineTo(11, 13)
          ..lineTo(15, 10)
          ..lineTo(19.4, 12.5)
          ..lineTo(19.4, 16.1)
          ..lineTo(4.6, 16.1)
          ..close(),
        Paint()..color = Colors.white.withValues(alpha: 0.4),
      );
      // Caption lines
      final capPaint = Paint()
        ..color = const Color(0xFFFDFBF2)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.0
        ..strokeCap = StrokeCap.round;
      canvas.drawLine(const Offset(6, 19), const Offset(18, 19), capPaint);
      canvas.drawLine(const Offset(6, 21), const Offset(14, 21), capPaint);
    } else {
      // Outlined Polaroid
      final stroke = Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.miter;

      stroke.strokeWidth = 1.7;
      canvas.drawRect(const Rect.fromLTWH(3, 3, 18, 19), stroke);

      stroke.strokeWidth = 1.3;
      canvas.drawRect(const Rect.fromLTWH(5, 5, 14, 11), stroke);

      // Sun dot (filled)
      canvas.drawCircle(const Offset(10, 9), 1.3, Paint()..color = color);

      // Mountain horizon line
      stroke
        ..strokeWidth = 1.3
        ..strokeJoin = StrokeJoin.round;
      canvas.drawPath(
        Path()
          ..moveTo(5, 14)
          ..lineTo(8, 11)
          ..lineTo(11, 13)
          ..lineTo(15, 10)
          ..lineTo(19, 12.5),
        stroke,
      );

      // Caption lines
      stroke.strokeWidth = 1.4;
      canvas.drawLine(const Offset(6, 19), const Offset(17, 19), stroke);
      canvas.drawLine(const Offset(6, 21), const Offset(13, 21), stroke);
    }

    canvas.restore(); // end rotated group

    // Sparkle at absolute (20.5, 5) — outside the rotated group
    canvas.save();
    canvas.translate(20.5, 5);
    canvas.drawPath(
      Path()
        ..moveTo(0, -2)
        ..lineTo(0.6, -0.6)
        ..lineTo(2, 0)
        ..lineTo(0.6, 0.6)
        ..lineTo(0, 2)
        ..lineTo(-0.6, 0.6)
        ..lineTo(-2, 0)
        ..lineTo(-0.6, -0.6)
        ..close(),
      Paint()
        ..color = filled ? const Color(0xFFFCD34D) : color,
    );
    canvas.restore();
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// JOURNAL GLYPH — compact book icon (24×24 viewBox)
// ─────────────────────────────────────────────────────────────────────────────

/// Small book glyph for panel tiles and AppBar toggles.
///
/// [filled] true  → closed book (solid body with page, ruled lines, red ribbon)
/// [filled] false → open book from above (diamond outline with handwriting)
/// [color] defaults to primary blue when filled, muted slate when outlined.
class JournalGlyph extends StatelessWidget {
  final double size;
  final bool filled;
  final Color? color;

  const JournalGlyph({super.key, this.size = 24, this.filled = true, this.color});

  @override
  Widget build(BuildContext context) {
    final c = color ??
        (filled
            ? Theme.of(context).colorScheme.primary
            : Theme.of(context).colorScheme.onSurface.withValues(alpha: 0.55));
    return SizedBox(
      width: size,
      height: size,
      child: CustomPaint(painter: _JournalGlyphPainter(filled: filled, color: c)),
    );
  }
}

class _JournalGlyphPainter extends CustomPainter {
  final bool filled;
  final Color color;

  const _JournalGlyphPainter({required this.filled, required this.color});

  @override
  bool shouldRepaint(_JournalGlyphPainter old) =>
      old.filled != filled || old.color != color;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(size.width / 24, size.height / 24);

    if (filled) {
      // ── Closed book (front view) ──────────────────────────────────────────
      // Cover: M4 4 Q4 3 5 3 L19 3 Q20 3 20 4 V19 Q20 20 19 20 H12
      //         Q11 20 11 19 H5 Q4 20 4 19 Z
      final cover = Path()
        ..moveTo(4, 4)
        ..quadraticBezierTo(4, 3, 5, 3)
        ..lineTo(19, 3)
        ..quadraticBezierTo(20, 3, 20, 4)
        ..lineTo(20, 19)
        ..quadraticBezierTo(20, 20, 19, 20)
        ..lineTo(12, 20)
        ..quadraticBezierTo(11, 20, 11, 19)
        ..lineTo(5, 19)
        ..quadraticBezierTo(4, 20, 4, 19)
        ..close();
      canvas.drawPath(cover, Paint()..color = color);

      // Page interior (cream)
      canvas.drawRect(
        const Rect.fromLTWH(6, 5, 12, 12),
        Paint()..color = const Color(0xFFFDFBF2),
      );

      // Ruled lines
      final rule = Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.2
        ..strokeCap = StrokeCap.round;
      canvas.drawLine(const Offset(8, 8), const Offset(16, 8), rule);
      canvas.drawLine(const Offset(8, 11), const Offset(14, 11), rule);
      canvas.drawLine(const Offset(8, 14), const Offset(12, 14), rule);

      // Red ribbon bookmark hanging from the spine
      // M11 21 L11 13 L12 14 L13 13 L13 21 L12 19 Z
      canvas.drawPath(
        Path()
          ..moveTo(11, 21)
          ..lineTo(11, 13)
          ..lineTo(12, 14)
          ..lineTo(13, 13)
          ..lineTo(13, 21)
          ..lineTo(12, 19)
          ..close(),
        Paint()..color = const Color(0xFFEF4444),
      );
    } else {
      // ── Open book (top-down view) ─────────────────────────────────────────
      // Diamond outline: M3 6 L12 8 L21 6 L21 18 L12 20 L3 18 Z
      final stroke = Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeJoin = StrokeJoin.round;

      stroke.strokeWidth = 1.7;
      canvas.drawPath(
        Path()
          ..moveTo(3, 6)
          ..lineTo(12, 8)
          ..lineTo(21, 6)
          ..lineTo(21, 18)
          ..lineTo(12, 20)
          ..lineTo(3, 18)
          ..close(),
        stroke,
      );

      // Spine
      stroke.strokeWidth = 1.5;
      canvas.drawLine(const Offset(12, 8), const Offset(12, 20), stroke);

      // Handwriting squiggles
      // Left page: M5.5 11 Q7 10.5 8.5 11 T11 11
      // Left page: M5.5 14 Q7 13.5 8.5 14 T10 14
      // Right page: M13 11 Q14.5 10.5 16 11 T18.5 11
      // Right page: M13 14 Q14.5 13.5 16 14
      stroke
        ..strokeWidth = 1.2
        ..strokeCap = StrokeCap.round;
      canvas.drawPath(
        Path()
          ..moveTo(5.5, 11)
          ..quadraticBezierTo(7, 10.5, 8.5, 11)
          ..quadraticBezierTo(10, 11.5, 11, 11),
        stroke,
      );
      canvas.drawPath(
        Path()
          ..moveTo(5.5, 14)
          ..quadraticBezierTo(7, 13.5, 8.5, 14)
          ..quadraticBezierTo(10, 14.5, 10, 14),
        stroke,
      );
      canvas.drawPath(
        Path()
          ..moveTo(13, 11)
          ..quadraticBezierTo(14.5, 10.5, 16, 11)
          ..quadraticBezierTo(17.5, 11.5, 18.5, 11),
        stroke,
      );
      canvas.drawPath(
        Path()
          ..moveTo(13, 14)
          ..quadraticBezierTo(14.5, 13.5, 16, 14),
        stroke,
      );

      // Small red heart near top-right page
      // M17 8.5 C16 8,15.7 7,16.5 6.6 C17 6.4,17.3 6.6,17.5 6.9
      //           C17.7 6.6,18 6.4,18.5 6.6 C19.3 7,19 8,17 8.5 Z
      canvas.drawPath(
        Path()
          ..moveTo(17, 8.5)
          ..cubicTo(16, 8, 15.7, 7, 16.5, 6.6)
          ..cubicTo(17, 6.4, 17.3, 6.6, 17.5, 6.9)
          ..cubicTo(17.7, 6.6, 18, 6.4, 18.5, 6.6)
          ..cubicTo(19.3, 7, 19, 8, 17, 8.5)
          ..close(),
        Paint()..color = const Color(0xFFEF4444),
      );
    }
  }
}
