part of 'project_stats_screen.dart';

// ── Counter helpers ───────────────────────────────────────────────────────────

String _fmtCounter(double v) {
  if (v == v.truncateToDouble()) return v.toInt().toString();
  return v.toStringAsFixed(1);
}

const _counterPalette = [
  Color(0xFF3B82F6),
  Color(0xFFEF4444),
  Color(0xFF22C55E),
  Color(0xFFF59E0B),
  Color(0xFFA855F7),
  Color(0xFF14B8A6),
  Color(0xFFEC4899),
  Color(0xFFFC4C02),
];

// ── Counter section ───────────────────────────────────────────────────────────

class _CounterSection extends StatefulWidget {
  final List<Map<String, dynamic>> counterStats;
  const _CounterSection({required this.counterStats});
  @override
  State<_CounterSection> createState() => _CounterSectionState();
}

class _CounterSectionState extends State<_CounterSection> {
  late Set<int> _enabled;

  @override
  void initState() {
    super.initState();
    _enabled = Set.of(List.generate(widget.counterStats.length, (i) => i));
  }

  @override
  void didUpdateWidget(_CounterSection old) {
    super.didUpdateWidget(old);
    _enabled = _enabled.where((i) => i < widget.counterStats.length).toSet();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final stats = widget.counterStats;

    final enabledWithSeries = _enabled.where((i) {
      final s = (stats[i]['series'] as List?)?.cast<Map<String, dynamic>>() ?? [];
      return s.isNotEmpty;
    }).toSet();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // ── Tiles ────────────────────────────────────────────────────────
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: List.generate(stats.length, (i) {
            final c       = stats[i];
            final enabled = _enabled.contains(i);
            final color   = _counterPalette[i % _counterPalette.length];
            final total   = (c['total'] as num?)?.toDouble() ?? 0.0;

            return GestureDetector(
              onTap: () => setState(() {
                if (enabled) {
                  _enabled.remove(i);
                } else {
                  _enabled.add(i);
                }
              }),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 150),
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                decoration: BoxDecoration(
                  color: enabled
                      ? color.withValues(alpha: 0.12)
                      : Colors.transparent,
                  border: Border.all(
                    color: enabled ? color : theme.colorScheme.outlineVariant,
                    width: enabled ? 1.5 : 1,
                  ),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      _fmtCounter(total),
                      style: theme.textTheme.titleMedium?.copyWith(
                        color: enabled
                            ? color
                            : theme.colorScheme.onSurfaceVariant,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    Text(
                      c['name'] as String,
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: enabled
                            ? color.withValues(alpha: 0.8)
                            : theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
            );
          }),
        ),
        // ── Chart ────────────────────────────────────────────────────────
        if (enabledWithSeries.isNotEmpty)
          _CounterChart(
            counterStats: stats,
            enabledIndices: enabledWithSeries,
          ),
      ],
    );
  }
}

// ── Multi-counter line chart ──────────────────────────────────────────────────

class _CounterChart extends StatelessWidget {
  final List<Map<String, dynamic>> counterStats;
  final Set<int> enabledIndices;

  const _CounterChart({
    required this.counterStats,
    required this.enabledIndices,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    // Earliest date across all enabled series (shared X origin).
    DateTime? earliest;
    for (final i in enabledIndices) {
      final series =
          (counterStats[i]['series'] as List?)?.cast<Map<String, dynamic>>() ??
              [];
      if (series.isEmpty) continue;
      final d = DateTime.parse(series.first['date'] as String);
      if (earliest == null || d.isBefore(earliest)) earliest = d;
    }
    if (earliest == null) return const SizedBox.shrink();

    final origin = earliest;
    double dayOff(String ds) =>
        DateTime.parse(ds).difference(origin).inDays.toDouble();

    // One LineChartBarData per enabled counter.
    final bars       = <LineChartBarData>[];
    var globalMin    = double.infinity;
    var globalMax    = double.negativeInfinity;

    for (final i in enabledIndices) {
      final series =
          (counterStats[i]['series'] as List?)?.cast<Map<String, dynamic>>() ??
              [];
      if (series.isEmpty) continue;

      final color = _counterPalette[i % _counterPalette.length];
      final spots = series.map((pt) {
        final y = (pt['value'] as num).toDouble();
        if (y < globalMin) globalMin = y;
        if (y > globalMax) globalMax = y;
        return FlSpot(dayOff(pt['date'] as String), y);
      }).toList();

      bars.add(LineChartBarData(
        spots: spots,
        isCurved: false,
        color: color,
        barWidth: 2,
        dotData: FlDotData(
          show: true,
          getDotPainter: (_, __, ___, ____) => FlDotCirclePainter(
            radius: 3.5,
            color: color,
            strokeWidth: 0,
          ),
        ),
      ));
    }

    if (bars.isEmpty) return const SizedBox.shrink();

    final yPad  = (globalMax - globalMin).abs() < 1
        ? 1.0
        : (globalMax - globalMin) * 0.1;
    final maxX  = bars
        .expand((b) => b.spots)
        .map((s) => s.x)
        .reduce((a, b) => a > b ? a : b);

    String xLabel(double x) {
      final d = origin.add(Duration(days: x.toInt()));
      const months = [
        'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
      ];
      return '${months[d.month - 1]} ${d.day}';
    }

    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: SizedBox(
        height: 200,
        child: LineChart(
          LineChartData(
            minY: globalMin - yPad,
            maxY: globalMax + yPad,
            gridData: FlGridData(
              show: true,
              drawVerticalLine: false,
              getDrawingHorizontalLine: (_) => FlLine(
                color: theme.colorScheme.outlineVariant.withAlpha(80),
                strokeWidth: 1,
              ),
            ),
            borderData: FlBorderData(show: false),
            titlesData: FlTitlesData(
              leftTitles: AxisTitles(
                sideTitles: SideTitles(
                  showTitles: true,
                  reservedSize: 40,
                  getTitlesWidget: (v, _) => Text(
                    _fmtCounter(v),
                    style: theme.textTheme.bodySmall,
                  ),
                ),
              ),
              bottomTitles: AxisTitles(
                sideTitles: SideTitles(
                  showTitles: true,
                  reservedSize: 24,
                  interval: maxX < 7 ? 1 : (maxX / 4).ceilToDouble(),
                  getTitlesWidget: (v, _) => Text(
                    xLabel(v),
                    style: theme.textTheme.bodySmall?.copyWith(fontSize: 10),
                  ),
                ),
              ),
              topTitles: const AxisTitles(
                  sideTitles: SideTitles(showTitles: false)),
              rightTitles: const AxisTitles(
                  sideTitles: SideTitles(showTitles: false)),
            ),
            lineBarsData: bars,
          ),
        ),
      ),
    );
  }
}
