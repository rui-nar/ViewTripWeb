/// Public-facing welcome / landing screen.
library;

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';

import '../core/design_tokens.dart';

// ── Always-dark landing palette ───────────────────────────────────────────────
const _bg       = Color(0xFF0D1B2A);
const _bgCard   = Color(0xFF1B2838);
const _bgCardAlt = Color(0xFF142031);
const _border   = Color(0xFF2D4A6A);
const _onBg     = Color(0xFFE2E8F0);
const _onCard   = Color(0xFFCBD5E1);
const _hint     = Color(0xFF64748B);
const _seed     = Color(0xFF0D6EFD);

const _kBreak  = 860.0;
const _kNavH   = 60.0;

// ─────────────────────────────────────────────────────────────────────────────

class WelcomeScreen extends StatelessWidget {
  const WelcomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      body: Stack(
        children: [
          SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: const [
                SizedBox(height: _kNavH),
                _HeroSection(),
                _FeaturesSection(),
                _AppPreviewSection(),
                _HowItWorksSection(),
                _CtaSection(),
                _Footer(),
              ],
            ),
          ),
          const Positioned(top: 0, left: 0, right: 0, child: _NavBar()),
        ],
      ),
    );
  }
}

// ── Fixed navigation bar ──────────────────────────────────────────────────────

class _NavBar extends StatelessWidget {
  const _NavBar();

  @override
  Widget build(BuildContext context) {
    return Container(
      height: _kNavH,
      decoration: BoxDecoration(
        color: _bg.withValues(alpha: 0.95),
        border: const Border(bottom: BorderSide(color: _border, width: 1)),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 28),
      child: Row(
        children: [
          Icon(Icons.map_rounded, color: _seed, size: 26),
          const SizedBox(width: 8),
          Text(
            'ViewTrip',
            style: GoogleFonts.inter(
                fontSize: 18, fontWeight: FontWeight.w700, color: _onBg),
          ),
          const Spacer(),
          TextButton(
            onPressed: () => context.go('/login'),
            style: TextButton.styleFrom(foregroundColor: _onCard),
            child: const Text('Sign In'),
          ),
          const SizedBox(width: 8),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              minimumSize: const Size(108, 36),
              padding: const EdgeInsets.symmetric(horizontal: 16),
            ),
            onPressed: () => context.go('/register'),
            child: const Text('Get Started'),
          ),
        ],
      ),
    );
  }
}

// ── Hero ──────────────────────────────────────────────────────────────────────

class _HeroSection extends StatelessWidget {
  const _HeroSection();

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xFF0A1628), _bg, Color(0xFF0D1F35)],
          stops: [0.0, 0.5, 1.0],
        ),
      ),
      child: LayoutBuilder(
        builder: (_, c) => c.maxWidth >= _kBreak
            ? _HeroWide()
            : _HeroNarrow(),
      ),
    );
  }
}

class _HeroWide extends StatelessWidget {
  const _HeroWide();
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(64, 80, 64, 80),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Expanded(child: _HeroText()),
          const SizedBox(width: 56),
          const SizedBox(width: 440, height: 300, child: _HeroIllustration()),
        ],
      ),
    );
  }
}

class _HeroNarrow extends StatelessWidget {
  const _HeroNarrow();
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 40, 24, 56),
      child: Column(
        children: [
          const SizedBox(height: 200, child: _HeroIllustration()),
          const SizedBox(height: 40),
          _HeroText(centered: true),
        ],
      ),
    );
  }
}

class _HeroText extends StatelessWidget {
  final bool centered;
  const _HeroText({this.centered = false});

  @override
  Widget build(BuildContext context) {
    final align = centered ? TextAlign.center : TextAlign.left;
    final cross =
        centered ? CrossAxisAlignment.center : CrossAxisAlignment.start;

    return Column(
      crossAxisAlignment: cross,
      children: [
        // Eyebrow chip
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
          decoration: BoxDecoration(
            color: _seed.withValues(alpha: 0.14),
            borderRadius: BorderRadius.circular(4),
            border: Border.all(color: _seed.withValues(alpha: 0.35)),
          ),
          child: Text(
            'VISUAL TRIP PLANNING',
            style: GoogleFonts.inter(
              fontSize: 11,
              fontWeight: FontWeight.w600,
              color: _seed,
              letterSpacing: 1.6,
            ),
          ),
        ),
        const SizedBox(height: 22),

        // Headline
        Text(
          'Your adventures,\nbeautifully mapped.',
          textAlign: align,
          style: GoogleFonts.inter(
            fontSize: 44,
            fontWeight: FontWeight.w800,
            color: _onBg,
            height: 1.15,
          ),
        ),
        const SizedBox(height: 20),

        // Description
        Text(
          'ViewTrip turns your Strava activities into day-by-day trip narratives. '
          'Import rides, hikes, and runs, visualise them on interactive maps, '
          'and build a rich record of every journey.',
          textAlign: align,
          style: GoogleFonts.inter(
              fontSize: 16, color: _onCard, height: 1.65),
        ),
        const SizedBox(height: 32),

        // CTA buttons
        Wrap(
          alignment:
              centered ? WrapAlignment.center : WrapAlignment.start,
          spacing: 12,
          runSpacing: 12,
          children: [
            ElevatedButton.icon(
              style: ElevatedButton.styleFrom(
                minimumSize: const Size(176, 48),
                padding: const EdgeInsets.symmetric(horizontal: 20),
                textStyle: GoogleFonts.inter(
                    fontSize: 15, fontWeight: FontWeight.w600),
              ),
              onPressed: () => context.go('/register'),
              icon: const Icon(Icons.arrow_forward, size: 18),
              label: const Text('Get Started — free'),
            ),
            OutlinedButton(
              style: OutlinedButton.styleFrom(
                foregroundColor: _onCard,
                side: const BorderSide(color: _border),
                minimumSize: const Size(108, 48),
                padding: const EdgeInsets.symmetric(horizontal: 20),
                textStyle: GoogleFonts.inter(
                    fontSize: 15, fontWeight: FontWeight.w500),
              ),
              onPressed: () => context.go('/login'),
              child: const Text('Sign In'),
            ),
          ],
        ),
      ],
    );
  }
}

// ── Hero illustration — track-merge custom painter ────────────────────────────

class _HeroIllustration extends StatelessWidget {
  const _HeroIllustration();

  @override
  Widget build(BuildContext context) {
    return CustomPaint(painter: _TrackMergePainter());
  }
}

class _TrackMergePainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;

    // Subtle grid
    final grid = Paint()
      ..color = Colors.white.withValues(alpha: 0.045)
      ..strokeWidth = 1;
    for (double x = 0; x <= w; x += 40) {
      canvas.drawLine(Offset(x, 0), Offset(x, h), grid);
    }
    for (double y = 0; y <= h; y += 40) {
      canvas.drawLine(Offset(0, y), Offset(w, y), grid);
    }

    final mergeX = w * 0.81;
    final mergeY = h * 0.50;

    // Five colored tracks converging to the merge point
    final tracks = [
      (0.09, kColorRide),
      (0.36, kColorAlt),
      (0.50, kColorRun),
      (0.66, kColorOther),
      (0.89, kColorHike),
    ];

    for (final (yr, color) in tracks) {
      final sy = h * yr;
      final path = Path()
        ..moveTo(0, sy)
        ..cubicTo(w * 0.28, sy, w * 0.58, mergeY, mergeX, mergeY);

      canvas.drawPath(
        path,
        Paint()
          ..color = color
          ..strokeWidth = 2.5
          ..style = PaintingStyle.stroke
          ..strokeCap = StrokeCap.round
          ..strokeJoin = StrokeJoin.round,
      );

      // Start dot
      canvas.drawCircle(Offset(0, sy), 4.5, Paint()..color = color);
      canvas.drawCircle(
        Offset(0, sy),
        4.5,
        Paint()
          ..color = color.withValues(alpha: 0.45)
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.5,
      );
    }

    // Merged output — layered glow → bright core
    for (final (a, sw) in [(0.10, 10.0), (0.24, 6.0), (0.88, 3.0)]) {
      canvas.drawLine(
        Offset(mergeX, mergeY),
        Offset(w, mergeY),
        Paint()
          ..color = Colors.white.withValues(alpha: a)
          ..strokeWidth = sw
          ..strokeCap = StrokeCap.round,
      );
    }

    // Merge-node glow ring
    canvas.drawCircle(Offset(mergeX, mergeY), 14,
        Paint()..color = Colors.white.withValues(alpha: 0.15));
    canvas.drawCircle(
      Offset(mergeX, mergeY),
      14,
      Paint()
        ..color = Colors.white.withValues(alpha: 0.30)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1,
    );
    // Core dot
    canvas.drawCircle(
        Offset(mergeX, mergeY), 5, Paint()..color = Colors.white);
  }

  @override
  bool shouldRepaint(covariant CustomPainter _) => false;
}

// ── Features section ──────────────────────────────────────────────────────────

class _FeaturesSection extends StatelessWidget {
  const _FeaturesSection();

  static const _features = [
    (
      Icons.route,
      kColorRide,
      'Interactive maps',
      'Every activity visualised on a live map with elevation profiles, '
          'speed data, and per-activity statistics.',
    ),
    (
      Icons.sync_rounded,
      kStrava,
      'Strava import',
      'Connect your Strava account and pull in rides, runs, and hikes '
          'filtered by date range and activity type.',
    ),
    (
      Icons.calendar_month_outlined,
      kColorHike,
      'Day-by-day stories',
      'Group activities into days, add connecting segments for trains or flights, '
          'and attach memories and notes.',
    ),
    (
      Icons.share_rounded,
      kColorOther,
      'Share & export',
      'Publish a live share link for anyone to explore, or export '
          'a high-resolution image of your trip map.',
    ),
  ];

  @override
  Widget build(BuildContext context) {
    return Container(
      color: _bgCard,
      padding: const EdgeInsets.symmetric(horizontal: 40, vertical: 72),
      child: Column(
        children: [
          Text(
            'Everything you need to document your journey',
            textAlign: TextAlign.center,
            style: GoogleFonts.inter(
                fontSize: 28, fontWeight: FontWeight.w700, color: _onBg, height: 1.25),
          ),
          const SizedBox(height: 10),
          Text(
            'From Strava import to map export — all in one place.',
            textAlign: TextAlign.center,
            style: GoogleFonts.inter(fontSize: 15, color: _hint),
          ),
          const SizedBox(height: 48),
          LayoutBuilder(
            builder: (_, c) {
              final wide = c.maxWidth >= _kBreak;
              if (wide) {
                return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (int i = 0; i < _features.length; i++) ...[
                      if (i > 0) const SizedBox(width: 20),
                      Expanded(child: _FeatureCard(_features[i])),
                    ],
                  ],
                );
              }
              return Column(
                children: [
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(child: _FeatureCard(_features[0])),
                      const SizedBox(width: 16),
                      Expanded(child: _FeatureCard(_features[1])),
                    ],
                  ),
                  const SizedBox(height: 16),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(child: _FeatureCard(_features[2])),
                      const SizedBox(width: 16),
                      Expanded(child: _FeatureCard(_features[3])),
                    ],
                  ),
                ],
              );
            },
          ),
        ],
      ),
    );
  }
}

class _FeatureCard extends StatelessWidget {
  final (IconData, Color, String, String) feature;
  const _FeatureCard(this.feature);

  @override
  Widget build(BuildContext context) {
    final (icon, color, title, body) = feature;
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: _bg,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 48,
            height: 48,
            decoration: BoxDecoration(
              color: iconBoxBg(color),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(icon, size: 22, color: color),
          ),
          const SizedBox(height: 16),
          Text(
            title,
            style: GoogleFonts.inter(
                fontSize: 16, fontWeight: FontWeight.w600, color: _onBg),
          ),
          const SizedBox(height: 8),
          Text(
            body,
            style: GoogleFonts.inter(fontSize: 14, color: _onCard, height: 1.6),
          ),
        ],
      ),
    );
  }
}

// ── App preview section ───────────────────────────────────────────────────────

class _AppPreviewSection extends StatelessWidget {
  const _AppPreviewSection();

  @override
  Widget build(BuildContext context) {
    return Container(
      color: _bg,
      padding: const EdgeInsets.symmetric(horizontal: 40, vertical: 72),
      child: Column(
        children: [
          Text(
            'See your trip come to life',
            textAlign: TextAlign.center,
            style: GoogleFonts.inter(
                fontSize: 28, fontWeight: FontWeight.w700, color: _onBg),
          ),
          const SizedBox(height: 10),
          Text(
            'Day-by-day activities, mapped and measured.',
            textAlign: TextAlign.center,
            style: GoogleFonts.inter(fontSize: 15, color: _hint),
          ),
          const SizedBox(height: 40),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 880),
            child: AspectRatio(
              aspectRatio: 16 / 9,
              child: Container(
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: _border, width: 1.5),
                  boxShadow: [
                    BoxShadow(
                      color: _seed.withValues(alpha: 0.08),
                      blurRadius: 40,
                      spreadRadius: 4,
                    ),
                  ],
                ),
                clipBehavior: Clip.antiAlias,
                child: CustomPaint(painter: _AppMockPainter()),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _AppMockPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;

    // ── Full background ──
    canvas.drawRect(Rect.fromLTWH(0, 0, w, h), Paint()..color = _bg);

    // ── Layout: 30% left panel | 70% map panel ──
    final panelW = w * 0.30;
    final mapX   = panelW;
    final mapW   = w - panelW;
    final navH   = h * 0.07;

    // ── App-bar ──
    canvas.drawRect(
      Rect.fromLTWH(0, 0, w, navH),
      Paint()..color = _bgCard,
    );
    canvas.drawLine(
      Offset(0, navH), Offset(w, navH),
      Paint()..color = _border..strokeWidth = 1,
    );
    // Brand icon
    _drawRRect(canvas, Rect.fromLTWH(12, navH * 0.28, navH * 0.44, navH * 0.44),
        3, _seed.withValues(alpha: 0.25));
    // "ViewTrip" label bar
    _drawRRect(canvas, Rect.fromLTWH(navH * 0.75, navH * 0.38, 54, 8), 2,
        _onBg.withValues(alpha: 0.55));

    // ── Left panel background ──
    canvas.drawRect(
      Rect.fromLTWH(0, navH, panelW, h - navH),
      Paint()..color = _bgCard,
    );
    canvas.drawLine(
      Offset(panelW, navH), Offset(panelW, h),
      Paint()..color = _border..strokeWidth = 1,
    );

    // Panel sub-header
    final subH = h * 0.08;
    canvas.drawRect(
      Rect.fromLTWH(0, navH, panelW, subH),
      Paint()..color = _bgCardAlt,
    );
    canvas.drawLine(
      Offset(0, navH + subH), Offset(panelW, navH + subH),
      Paint()..color = _border..strokeWidth = 1,
    );
    // "Sort" chips in sub-header
    for (int i = 0; i < 3; i++) {
      _drawRRect(
        canvas,
        Rect.fromLTWH(10.0 + i * 44, navH + subH * 0.3, 36, subH * 0.42),
        3,
        i == 1 ? _seed.withValues(alpha: 0.35) : _border,
      );
    }

    // Activity rows
    final listTop = navH + subH;
    final rowCount = 7;
    final rowH = (h - listTop) / rowCount;
    final actColors = [
      kColorRide,
      kColorRun,
      kColorAlt,
      kColorHike,
      kColorOther,
      kColorRide,
      kColorRun,
    ];
    final barWidths = [0.68, 0.55, 0.72, 0.60, 0.65, 0.58, 0.70];

    for (int i = 0; i < rowCount; i++) {
      final y = listTop + i * rowH;
      final color = actColors[i];

      // Selected row highlight
      if (i == 2) {
        canvas.drawRect(
          Rect.fromLTWH(0, y, panelW, rowH),
          Paint()..color = _seed.withValues(alpha: 0.14),
        );
        // Selection indicator strip
        canvas.drawRect(
          Rect.fromLTWH(0, y, 3, rowH),
          Paint()..color = _seed,
        );
      }

      // Row divider
      canvas.drawLine(
        Offset(0, y + rowH), Offset(panelW, y + rowH),
        Paint()..color = _border.withValues(alpha: 0.5)..strokeWidth = 0.5,
      );

      // Icon box
      final boxY = y + rowH / 2 - 11;
      _drawRRect(canvas, Rect.fromLTWH(10, boxY, 22, 22), 5,
          color.withValues(alpha: 0.2));
      canvas.drawCircle(Offset(21, boxY + 11), 4, Paint()..color = color);

      // Name bar
      final nameW = (panelW - 42) * barWidths[i];
      _drawRRect(canvas,
          Rect.fromLTWH(38, y + rowH / 2 - 7, nameW, 7), 2,
          _onBg.withValues(alpha: i == 2 ? 0.75 : 0.50));
      // Sub-label bar
      _drawRRect(canvas,
          Rect.fromLTWH(38, y + rowH / 2 + 4, nameW * 0.55, 5), 2,
          _hint.withValues(alpha: 0.55));
    }

    // ── Map panel ──
    canvas.drawRect(
      Rect.fromLTWH(mapX, navH, mapW, h - navH),
      Paint()..color = const Color(0xFF0F2438),
    );

    // Map grid
    final mg = Paint()
      ..color = Colors.white.withValues(alpha: 0.04)
      ..strokeWidth = 1;
    for (double x = mapX; x < w; x += 28) {
      canvas.drawLine(Offset(x, navH), Offset(x, h), mg);
    }
    for (double y = navH; y < h; y += 28) {
      canvas.drawLine(Offset(mapX, y), Offset(w, y), mg);
    }

    // Main route — a winding cubic path in sky blue
    final r = Paint()
      ..color = kColorRide
      ..strokeWidth = 2.5
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;

    final mx0 = mapX + mapW * 0.06;
    final route = Path()
      ..moveTo(mx0, h * 0.55)
      ..cubicTo(
        mapX + mapW * 0.22, h * 0.28,
        mapX + mapW * 0.38, h * 0.62,
        mapX + mapW * 0.55, h * 0.42,
      )
      ..cubicTo(
        mapX + mapW * 0.67, h * 0.28,
        mapX + mapW * 0.80, h * 0.58,
        mapX + mapW * 0.93, h * 0.45,
      );
    canvas.drawPath(route, r);

    // Day waypoints along the route
    final waypoints = [
      (mx0,                    h * 0.55, kColorHike,  '1'),
      (mapX + mapW * 0.55, h * 0.42, kColorRide,  '2'),
      (mapX + mapW * 0.93, h * 0.45, kColorRun,   '3'),
    ];

    for (final (wx, wy, wc, label) in waypoints) {
      // Outer glow
      canvas.drawCircle(Offset(wx, wy), 10,
          Paint()..color = wc.withValues(alpha: 0.20));
      // Filled dot
      canvas.drawCircle(Offset(wx, wy), 7, Paint()..color = wc);
      // White ring
      canvas.drawCircle(
        Offset(wx, wy),
        7,
        Paint()
          ..color = Colors.white.withValues(alpha: 0.6)
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.5,
      );
      // Day number
      final tp = TextPainter(
        text: TextSpan(
          text: label,
          style: const TextStyle(
            color: Colors.white,
            fontSize: 7,
            fontWeight: FontWeight.w700,
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, Offset(wx - tp.width / 2, wy - tp.height / 2));
    }

    // Elevation chart strip at the bottom of the map
    final chartH = h * 0.14;
    final chartY = h - chartH;
    canvas.drawRect(
      Rect.fromLTWH(mapX, chartY, mapW, chartH),
      Paint()..color = _bgCard.withValues(alpha: 0.88),
    );
    canvas.drawLine(
      Offset(mapX, chartY), Offset(w, chartY),
      Paint()..color = _border..strokeWidth = 1,
    );

    // Elevation curve
    final elevPts = [0.5, 0.35, 0.55, 0.25, 0.40, 0.30, 0.50, 0.20, 0.38, 0.45];
    final segW = mapW / (elevPts.length - 1);
    final elevPath = Path();
    for (int i = 0; i < elevPts.length; i++) {
      final ex = mapX + i * segW;
      final ey = chartY + chartH * 0.85 - chartH * 0.65 * elevPts[i];
      if (i == 0) {
        elevPath.moveTo(ex, ey);
      } else {
        final prevX = mapX + (i - 1) * segW;
        final prevY = chartY + chartH * 0.85 - chartH * 0.65 * elevPts[i - 1];
        elevPath.cubicTo(
          prevX + segW * 0.4, prevY,
          ex - segW * 0.4, ey,
          ex, ey,
        );
      }
    }

    // Fill under elevation curve
    final fillPath = Path.from(elevPath)
      ..lineTo(w, h)
      ..lineTo(mapX, h)
      ..close();
    canvas.drawPath(
      fillPath,
      Paint()..color = kColorRide.withValues(alpha: 0.12),
    );
    canvas.drawPath(
      elevPath,
      Paint()
        ..color = kColorRide
        ..strokeWidth = 1.5
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round,
    );
  }

  static void _drawRRect(
      Canvas canvas, Rect rect, double r, Color color) {
    canvas.drawRRect(
      RRect.fromRectAndRadius(rect, Radius.circular(r)),
      Paint()..color = color,
    );
  }

  @override
  bool shouldRepaint(covariant CustomPainter _) => false;
}

// ── How it works ──────────────────────────────────────────────────────────────

class _HowItWorksSection extends StatelessWidget {
  const _HowItWorksSection();

  static const _steps = [
    (
      '01',
      Icons.add_circle_outline,
      'Create a project',
      'Name your trip and open a new project. One project covers a full journey — '
          'a week-long cycling tour, a hiking trip, a road trip across a continent.',
    ),
    (
      '02',
      Icons.download_rounded,
      'Import your activities',
      'Link your Strava account to pull activities automatically, filtered by date '
          'and type. Add connecting segments — trains, buses, or flights — between stops.',
    ),
    (
      '03',
      Icons.explore_outlined,
      'Explore and share',
      'View your full route on the map, review elevation and stats per activity, '
          'then share a live link or export a high-resolution image.',
    ),
  ];

  @override
  Widget build(BuildContext context) {
    return Container(
      color: _bgCard,
      padding: const EdgeInsets.symmetric(horizontal: 40, vertical: 72),
      child: Column(
        children: [
          Text(
            'Up and running in minutes',
            textAlign: TextAlign.center,
            style: GoogleFonts.inter(
                fontSize: 28, fontWeight: FontWeight.w700, color: _onBg),
          ),
          const SizedBox(height: 10),
          Text(
            'Three steps from Strava to your trip map.',
            textAlign: TextAlign.center,
            style: GoogleFonts.inter(fontSize: 15, color: _hint),
          ),
          const SizedBox(height: 52),
          LayoutBuilder(
            builder: (_, c) {
              final wide = c.maxWidth >= _kBreak;
              if (wide) {
                return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (int i = 0; i < _steps.length; i++) ...[
                      if (i > 0) ...[
                        const SizedBox(width: 8),
                        Padding(
                          padding: const EdgeInsets.only(top: 26),
                          child: Icon(Icons.chevron_right,
                              color: _border, size: 28),
                        ),
                        const SizedBox(width: 8),
                      ],
                      Expanded(child: _StepCard(_steps[i])),
                    ],
                  ],
                );
              }
              return Column(
                children: [
                  for (int i = 0; i < _steps.length; i++) ...[
                    if (i > 0) ...[
                      const SizedBox(height: 8),
                      Icon(Icons.keyboard_arrow_down, color: _border, size: 28),
                      const SizedBox(height: 8),
                    ],
                    _StepCard(_steps[i]),
                  ],
                ],
              );
            },
          ),
        ],
      ),
    );
  }
}

class _StepCard extends StatelessWidget {
  final (String, IconData, String, String) step;
  const _StepCard(this.step);

  @override
  Widget build(BuildContext context) {
    final (num, icon, title, body) = step;
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: _bgCardAlt,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            num,
            style: GoogleFonts.inter(
              fontSize: 36,
              fontWeight: FontWeight.w800,
              color: _seed.withValues(alpha: 0.22),
              height: 1,
            ),
          ),
          const SizedBox(height: 14),
          Icon(icon, color: _seed, size: 28),
          const SizedBox(height: 14),
          Text(
            title,
            style: GoogleFonts.inter(
                fontSize: 16, fontWeight: FontWeight.w600, color: _onBg),
          ),
          const SizedBox(height: 8),
          Text(
            body,
            style: GoogleFonts.inter(
                fontSize: 14, color: _onCard, height: 1.6),
          ),
        ],
      ),
    );
  }
}

// ── CTA section ───────────────────────────────────────────────────────────────

class _CtaSection extends StatelessWidget {
  const _CtaSection();

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xFF0A2265), Color(0xFF0D1B2A)],
        ),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 40, vertical: 80),
      child: Column(
        children: [
          Text(
            'Ready to map your next adventure?',
            textAlign: TextAlign.center,
            style: GoogleFonts.inter(
              fontSize: 32,
              fontWeight: FontWeight.w800,
              color: _onBg,
              height: 1.2,
            ),
          ),
          const SizedBox(height: 14),
          Text(
            'Join ViewTrip and start documenting your journeys today. Free to use.',
            textAlign: TextAlign.center,
            style: GoogleFonts.inter(
                fontSize: 16, color: _onCard, height: 1.55),
          ),
          const SizedBox(height: 36),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              minimumSize: const Size(220, 52),
              textStyle: GoogleFonts.inter(
                  fontSize: 16, fontWeight: FontWeight.w600),
            ),
            onPressed: () => context.go('/register'),
            child: const Text('Create your free account'),
          ),
          const SizedBox(height: 16),
          TextButton(
            style: TextButton.styleFrom(foregroundColor: _hint),
            onPressed: () => context.go('/login'),
            child: const Text('Already have an account? Sign in →'),
          ),
        ],
      ),
    );
  }
}

// ── Footer ────────────────────────────────────────────────────────────────────

class _Footer extends StatelessWidget {
  const _Footer();

  @override
  Widget build(BuildContext context) {
    return Container(
      color: const Color(0xFF080F18),
      padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 22),
      child: LayoutBuilder(
        builder: (_, c) {
          final brand = Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.map_rounded, color: _seed, size: 16),
              const SizedBox(width: 6),
              Text(
                'ViewTrip',
                style: GoogleFonts.inter(
                    fontSize: 13, fontWeight: FontWeight.w600, color: _onCard),
              ),
            ],
          );
          final copy = Text(
            '© ${DateTime.now().year} ViewTrip',
            style: GoogleFonts.inter(fontSize: 12, color: _hint),
          );

          if (c.maxWidth >= 500) {
            return Row(
              children: [brand, const Spacer(), copy],
            );
          }
          return Column(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [brand, const SizedBox(height: 8), copy],
          );
        },
      ),
    );
  }
}
