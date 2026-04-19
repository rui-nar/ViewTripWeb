library;

import 'package:flutter/material.dart';

// ── Accent (crimson red) ─────────────────────────────────────────────────────
const kAccent     = Color(0xFFDC2626);
const kAccentDark = Color(0xFFEF4444);
const kAccentSoft = Color(0x1ADC2626);

// ── Strava brand ─────────────────────────────────────────────────────────────
const kStrava = Color(0xFFFC4C02);

// ── Semantic ─────────────────────────────────────────────────────────────────
const kSuccess     = Color(0xFF16A34A);
const kSuccessDark = Color(0xFF22C55E);
const kWarning     = Color(0xFFD97706);
const kWarningDark = Color(0xFFF59E0B);

// ── Activity type colours (map polylines + icon boxes) ────────────────────────
const kColorRide  = Color(0xFF4FC3F7);
const kColorRun   = Color(0xFFEF5350);
const kColorHike  = Color(0xFF66BB6A);
const kColorOther = Color(0xFFAB47BC);
const kColorAlt   = Color(0xFFFFA726);

Color iconBoxBg(Color c) => c.withValues(alpha: 0.15);

Color iconBoxFg(Color c, {bool dark = false}) => dark
    ? c
    : HSLColor.fromColor(c)
        .withLightness(
            (HSLColor.fromColor(c).lightness * 0.65).clamp(0.0, 1.0))
        .toColor();
