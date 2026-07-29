/// The TraxJourney brand mark — design concept 6c, "Feeding in".
///
/// A chrome-to-crimson ribbon with three plain nodes on it, fed by source
/// bubbles balanced either side of the track: a Strava activity trace and an
/// encounter above, a photo below. The ribbon ends on the glowing crimson
/// "you are here".
///
/// Authored in a 160×160 design space and scaled to whatever box it is given,
/// so the same geometry serves the splash (168–228 px) and the app icon.
///
/// This is one of three copies of the same geometry — change all three
/// together:
///   * this painter                 — in-app rendering
///   * assets/mark.svg              — the design-system export
///   * scripts/generate_icons.py    — favicon, PWA and launcher rasters
///
/// The palette assumes a dark field; the mark has no light-background variant.
library;

import 'dart:ui' as ui;

import 'package:flutter/material.dart';

/// Edge of the square design space the paths are authored in.
const double kBrandMarkCanvas = 160.0;

// ── Palette ──────────────────────────────────────────────────────────────────
/// Ribbon gradient: slate → cobalt → crimson, running start-of-trip to now.
const _ribbonStart = Color(0xFF3A526E);
const _ribbonMid = Color(0xFF3B82F6);
const _ribbonEnd = Color(0xFFEF4444);

/// Muted stem every source bubble feeds in along.
const _feeder = Color(0xFF64748B);

/// Per-source accents — activity, photo, people.
const _activity = Color(0xFF60A5FA);
const _photo = Color(0xFF818CF8);
const _people = Color(0xFFC084FC);

/// Punched-out centre of every ring, matching the icon's darkest field.
const _hollow = Color(0xFF0B1420);

/// The crimson present-moment node at the end of the ribbon.
const _destination = Color(0xFFEF4444);

/// Renders the brand mark, scaled to fill a [size]×[size] box.
class BrandMark extends StatelessWidget {
  const BrandMark({super.key, required this.size});

  final double size;

  @override
  Widget build(BuildContext context) => SizedBox.square(
        dimension: size,
        child: const CustomPaint(painter: BrandMarkPainter()),
      );
}

/// Paints [BrandMark] into the shortest side of the canvas it is given.
class BrandMarkPainter extends CustomPainter {
  const BrandMarkPainter();

  @override
  void paint(Canvas canvas, Size size) {
    canvas.save();
    canvas.scale(size.shortestSide / kBrandMarkCanvas);

    _paintRibbon(canvas);
    _paintFeeders(canvas);
    _paintSources(canvas);
    _paintNodes(canvas);
    _paintDestination(canvas);

    canvas.restore();
  }

  // The ribbon itself — one continuous curve from the trip's start to now.
  void _paintRibbon(Canvas canvas) {
    final ribbon = Path()
      ..moveTo(14, 140)
      ..cubicTo(26, 126, 32, 118, 38, 112)
      ..cubicTo(50, 102, 64, 112, 74, 104)
      ..cubicTo(86, 94, 94, 80, 102, 72)
      ..cubicTo(112, 62, 126, 56, 136, 48);

    canvas.drawPath(
      ribbon,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 5.5
        ..strokeCap = StrokeCap.round
        // The SVG gradient is in object-bounding-box units, which for this
        // path resolves to exactly its own start and end points.
        ..shader = ui.Gradient.linear(
          const Offset(14, 140),
          const Offset(136, 48),
          const [_ribbonStart, _ribbonMid, _ribbonEnd],
          const [0.0, 0.4, 1.0],
        ),
    );
  }

  // Curved arrows carrying each source into its node on the ribbon.
  void _paintFeeders(Canvas canvas) {
    final stem = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.4
      ..strokeCap = StrokeCap.round
      ..color = _feeder;

    // Activity bubble → first node.
    canvas.drawPath(
      Path()
        ..moveTo(23, 94.5)
        ..quadraticBezierTo(25, 102, 34, 107.2),
      stem,
    );
    _fillTriangle(canvas, const [
      Offset(34, 107.2),
      Offset(27.3, 107.05),
      Offset(30.1, 101.75),
    ], _activity);

    // Photo bubble → second node.
    canvas.drawPath(
      Path()
        ..moveTo(99, 120.5)
        ..quadraticBezierTo(89, 116.5, 80.4, 108),
      stem,
    );
    _fillTriangle(canvas, const [
      Offset(80.4, 108),
      Offset(86.7, 110.3),
      Offset(82.3, 114.4),
    ], _photo);

    // People bubble → third node.
    canvas.drawPath(
      Path()
        ..moveTo(79, 53.5)
        ..quadraticBezierTo(85.5, 57.5, 95.4, 66.7),
      stem,
    );
    _fillTriangle(canvas, const [
      Offset(95.4, 66.7),
      Offset(89, 64.8),
      Offset(93, 60.4),
    ], _people);
  }

  // The three source bubbles, each holding what it carries.
  void _paintSources(Canvas canvas) {
    // Strava activity — a miniature elevation trace.
    _ring(canvas, const Offset(18, 88), 10, _activity, 2.6);
    canvas.drawPath(
      Path()
        ..moveTo(13.5, 90.5)
        ..lineTo(16.5, 86)
        ..lineTo(19.5, 89)
        ..lineTo(23, 83.5),
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round
        ..color = _activity,
    );

    // Photo — frame plus the peak inside it.
    _ring(canvas, const Offset(106, 124), 10, _photo, 2.6);
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        const Rect.fromLTWH(100.5, 119.5, 11, 9),
        const Radius.circular(1.8),
      ),
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2
        ..color = _photo,
    );
    _fillTriangle(canvas, const [
      Offset(102.5, 127.5),
      Offset(105.5, 123),
      Offset(108.5, 127.5),
    ], _photo);

    // Encounter — two people, one behind the other.
    _ring(canvas, const Offset(72, 48), 11, _people, 2.6);
    final person = Paint()..color = _people;
    canvas.drawCircle(const Offset(76.2, 42.5), 1.9, person);
    _shoulders(canvas, const Offset(73.5, 47.5), 2.7, person);
    canvas.drawCircle(const Offset(69, 46.5), 2.7, person);
    _shoulders(canvas, const Offset(65.3, 53.5), 3.7, person);
  }

  // Plain nodes riding the ribbon — the moments themselves.
  void _paintNodes(Canvas canvas) {
    _ring(canvas, const Offset(38, 112), 7, _activity, 3);
    _ring(canvas, const Offset(74, 104), 8, _photo, 3);
    _ring(canvas, const Offset(102, 72), 9, _people, 3.2);
  }

  // "You are here" — solid crimson under its own glow.
  void _paintDestination(Canvas canvas) {
    const centre = Offset(136, 48);
    // Matches the SVG's feGaussianBlur stdDeviation, which is already a sigma.
    canvas.drawCircle(
      centre,
      13,
      Paint()
        ..color = _destination
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 4.5),
    );
    canvas.drawCircle(centre, 13, Paint()..color = _destination);
  }

  /// A hollow circle: the field punched out, then an accent outline.
  void _ring(
    Canvas canvas,
    Offset centre,
    double radius,
    Color colour,
    double strokeWidth,
  ) {
    canvas.drawCircle(centre, radius, Paint()..color = _hollow);
    canvas.drawCircle(
      centre,
      radius,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = strokeWidth
        ..color = colour,
    );
  }

  void _fillTriangle(Canvas canvas, List<Offset> points, Color colour) {
    canvas.drawPath(
      Path()
        ..moveTo(points[0].dx, points[0].dy)
        ..lineTo(points[1].dx, points[1].dy)
        ..lineTo(points[2].dx, points[2].dy)
        ..close(),
      Paint()..color = colour,
    );
  }

  /// Upper half-disc of radius [radius] sitting on [left] — a person's
  /// shoulders. Drawn clockwise so it bulges away from the baseline.
  void _shoulders(Canvas canvas, Offset left, double radius, Paint paint) {
    canvas.drawPath(
      Path()
        ..moveTo(left.dx, left.dy)
        ..arcToPoint(
          Offset(left.dx + radius * 2, left.dy),
          radius: Radius.circular(radius),
        )
        ..close(),
      paint,
    );
  }

  @override
  bool shouldRepaint(BrandMarkPainter oldDelegate) => false;
}
