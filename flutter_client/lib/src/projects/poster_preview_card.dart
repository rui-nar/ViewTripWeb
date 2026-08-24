/// Live mock-up of the poster's cards, shown inside [PosterConfigDialog] so
/// the user can see what each toggle actually adds before generating an A0
/// print they then have to wait for.
///
/// This is a *visual approximation*, not a second renderer: it draws the same
/// elements in the same order as `src/poster/card_layout.py` (day badge, hero
/// photo, title, date, description, stats, counters, tag distances, photo
/// grid) with fixed sample content, but none of the real card-layout
/// algorithm — no measuring, no shrink-to-content, no overflow handling.
///
/// The colours are deliberately hard-coded rather than taken from the ambient
/// Material theme: the preview must show the *poster's* selected theme, which
/// is independent of whether the app itself is in light or dark mode. They
/// mirror `PosterTheme` in `src/poster/theme.py` — keep the two in sync.
library;

import 'package:flutter/material.dart';

/// The app's brand orange (`ACCENT` in `theme.py`), shared by both themes.
const Color _kAccent = Color(0xFFFC4C02);

/// Shown when every per-memory toggle is off: the backend emits no card at
/// all in that case, the memory is listed as plain text instead.
const String kNoCardMessage =
    '(no card — this memory will appear in a list instead)';

/// The subset of [PosterTheme] the preview needs.
class _Palette {
  final Color cardBg;
  final Color primaryText;
  final Color mutedText;
  final Color shadow;

  /// Stands in for the basemap the cards are drawn over, so a white card is
  /// still legible on a white dialog.
  final Color backdrop;

  const _Palette({
    required this.cardBg,
    required this.primaryText,
    required this.mutedText,
    required this.shadow,
    required this.backdrop,
  });

  static const _light = _Palette(
    cardBg: Color(0xFFFFFFFF),
    primaryText: Color(0xFF334155), // slate-700
    mutedText: Color(0xFF94A3B8), // slate-400
    shadow: Color(0x2E0F2236), // #0F2236 @ 18%
    backdrop: Color(0xFFE2E8F0), // slate-200
  );

  static const _dark = _Palette(
    cardBg: Color(0xFF1B2838),
    primaryText: Color(0xFFCBD5E1), // slate-300
    mutedText: Color(0xFF64748B), // slate-500
    shadow: Color(0x99000000), // black @ 60%
    backdrop: Color(0xFF0F1A24),
  );

  /// Unknown/missing names fall back to dark, like `theme.py`'s `get_theme`.
  static _Palette of(String name) => name == 'light' ? _light : _dark;
}

class PosterPreview extends StatelessWidget {
  final String theme;
  final bool distance;
  final bool elevation;
  final bool heroPhoto;
  final bool allPhotos;
  final bool memoryText;
  final bool counters;
  final bool tagPie;
  final bool encounters;
  final bool tripSummary;

  const PosterPreview({
    super.key,
    required this.theme,
    required this.distance,
    required this.elevation,
    required this.heroPhoto,
    required this.allPhotos,
    required this.memoryText,
    required this.counters,
    required this.tagPie,
    required this.encounters,
    required this.tripSummary,
  });

  /// A memory card exists as soon as *anything* would go on it. `tripSummary`
  /// is deliberately excluded: it is a standalone card, not memory content.
  bool get _hasMemoryContent =>
      distance ||
      elevation ||
      heroPhoto ||
      allPhotos ||
      memoryText ||
      counters ||
      tagPie ||
      encounters;

  @override
  Widget build(BuildContext context) {
    final p = _Palette.of(theme);
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('Preview', style: Theme.of(context).textTheme.labelMedium),
        const SizedBox(height: 6),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: p.backdrop,
            borderRadius: BorderRadius.circular(8),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (_hasMemoryContent)
                _card(p, _memoryCardChildren(p))
              else
                _noCard(p),
              if (tripSummary) ...[
                const SizedBox(height: 12),
                _card(p, _tripSummaryChildren(p)),
              ],
            ],
          ),
        ),
      ],
    );
  }

  /// The card shell: rounded, soft downward shadow, both themes.
  Widget _card(_Palette p, List<Widget> children) => Container(
        padding: const EdgeInsets.fromLTRB(10, 10, 10, 4),
        decoration: BoxDecoration(
          color: p.cardBg,
          borderRadius: BorderRadius.circular(12),
          boxShadow: [
            BoxShadow(
              color: p.shadow,
              blurRadius: 12,
              offset: const Offset(0, 3),
            ),
          ],
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: children,
        ),
      );

  Widget _noCard(_Palette p) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 14),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: p.mutedText, width: 1),
        ),
        child: Text(
          kNoCardMessage,
          textAlign: TextAlign.center,
          style: TextStyle(color: p.mutedText, fontSize: 11),
        ),
      );

  /// Same order as `layout_card()` in `src/poster/card_layout.py`, with the
  /// day badge prepended. The title is *not* gated by [memoryText]: every
  /// card that exists is titled; `memory_text` only gates date + description.
  List<Widget> _memoryCardChildren(_Palette p) => [
        _dayBadge(),
        if (heroPhoto) _photoBox(p, 64),
        _title(p, 'Sunset at the beach'),
        if (memoryText) _dateLine('12 Jun 2024'),
        if (memoryText)
          _body(p, 'Golden light over the dunes, the last swim of the trip '
              'before the long drive north.'),
        if (distance) _statRow(p, 'Distance', '12.3 km'),
        if (elevation) _statRow(p, 'Ascent', '340 m'),
        if (encounters) _statRow(p, 'People met', '7'),
        if (counters) _statRow(p, 'Photos', '12'),
        if (counters) _statRow(p, 'Memories', '4'),
        if (tagPie) _statRow(p, 'Hiking', '42 km'),
        if (tagPie) _statRow(p, 'Cycling', '18 km'),
        if (allPhotos) _photoStrip(p),
      ];

  List<Widget> _tripSummaryChildren(_Palette p) => [
        _label(p, 'Trip summary'),
        _title(p, 'Iceland ring road'),
        _dateLine('1 Jun 2024 – 14 Jun 2024'),
        _statRow(p, 'Total distance', '412 km'),
        _statRow(p, 'Total climb', '6,240 m'),
      ];

  static Widget _pad(Widget child) =>
      Padding(padding: const EdgeInsets.only(bottom: 6), child: child);

  /// Unconditional on every card that exists — not tied to any toggle.
  Widget _dayBadge() => _pad(Align(
        alignment: Alignment.centerLeft,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
          decoration: BoxDecoration(
            color: _kAccent.withValues(alpha: 0.15),
            borderRadius: BorderRadius.circular(4),
          ),
          child: const Text(
            'DAY 3',
            style: TextStyle(
              color: _kAccent,
              fontSize: 9,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.8,
            ),
          ),
        ),
      ));

  Widget _label(_Palette p, String text) => _pad(Text(
        text.toUpperCase(),
        style: TextStyle(
          color: p.mutedText,
          fontSize: 9,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.8,
        ),
      ));

  Widget _title(_Palette p, String text) => _pad(Text(
        text,
        style: TextStyle(
          color: p.primaryText,
          fontSize: 14,
          fontWeight: FontWeight.w600,
        ),
      ));

  Widget _dateLine(String text) => _pad(Text(
        text,
        style: const TextStyle(color: _kAccent, fontSize: 10),
      ));

  Widget _body(_Palette p, String text) => _pad(Text(
        text,
        style: TextStyle(color: p.primaryText, fontSize: 10, height: 1.3),
      ));

  Widget _statRow(_Palette p, String label, String value) => _pad(Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: TextStyle(color: p.mutedText, fontSize: 10)),
          Text(
            value,
            style: TextStyle(
              color: p.primaryText,
              fontSize: 11,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ));

  Widget _photoBox(_Palette p, double height) => _pad(Container(
        height: height,
        decoration: BoxDecoration(
          color: p.mutedText.withValues(alpha: 0.30),
          borderRadius: BorderRadius.circular(6),
        ),
        child: Icon(Icons.photo_outlined, size: 20, color: p.mutedText),
      ));

  Widget _photoStrip(_Palette p) => _pad(Row(
        children: [
          for (var i = 0; i < 3; i++) ...[
            if (i > 0) const SizedBox(width: 6),
            Expanded(
              child: Container(
                height: 30,
                decoration: BoxDecoration(
                  color: p.mutedText.withValues(alpha: 0.30),
                  borderRadius: BorderRadius.circular(4),
                ),
              ),
            ),
          ],
        ],
      ));
}
