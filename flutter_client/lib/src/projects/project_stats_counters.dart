part of 'project_stats_screen.dart';

// ── Counter helpers ───────────────────────────────────────────────────────────

String _fmtCounter(double v) {
  if (v == v.truncateToDouble()) return v.toInt().toString();
  return v.toStringAsFixed(1);
}

// ── Counter section ───────────────────────────────────────────────────────────

class _CounterSection extends StatefulWidget {
  final List<Map<String, dynamic>> counterStats;
  const _CounterSection({required this.counterStats});
  @override
  State<_CounterSection> createState() => _CounterSectionState();
}

class _CounterSectionState extends State<_CounterSection> {
  int _selectedIdx = 0;

  @override
  void didUpdateWidget(_CounterSection old) {
    super.didUpdateWidget(old);
    if (_selectedIdx >= widget.counterStats.length) _selectedIdx = 0;
  }

  @override
  Widget build(BuildContext context) {
    final sel    = widget.counterStats[_selectedIdx];
    final name   = sel['name'] as String;
    final total  = (sel['total'] as num?)?.toDouble() ?? 0.0;
    final start  = (sel['start'] as num?)?.toDouble() ?? 0.0;
    final series = (sel['series'] as List?)
            ?.cast<Map<String, dynamic>>() ??
        const <Map<String, dynamic>>[];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (widget.counterStats.length > 1)
          DropdownButton<int>(
            value: _selectedIdx,
            underline: const SizedBox.shrink(),
            items: widget.counterStats.indexed
                .map((p) => DropdownMenuItem(
                      value: p.$1,
                      child: Text(p.$2['name'] as String),
                    ))
                .toList(),
            onChanged: (i) => setState(() => _selectedIdx = i!),
          ),
        _StatCard(
            icon: Icons.pin_outlined,
            label: name,
            value: _fmtCounter(total)),
        if (series.isNotEmpty)
          _CounterChart(series: series, startValue: start),
      ],
    );
  }
}

// ── Counter chart (step-function line chart) ──────────────────────────────────

class _CounterChart extends StatelessWidget {
  final List<Map<String, dynamic>> series;
  final double startValue;
  const _CounterChart({required this.series, required this.startValue});

  @override
  Widget build(BuildContext context) {
    if (series.isEmpty) return const SizedBox.shrink();

    final theme = Theme.of(context);

    // Parse dates and compute integer day offsets from the first date.
    final firstDate = DateTime.parse(series.first['date'] as String);

    double dayOffset(String d) =>
        DateTime.parse(d).difference(firstDate).inDays.toDouble();

    // Build step-function spots: for each jump, emit a horizontal point
    // at the previous value before the vertical jump.
    final spots = <FlSpot>[];
    double prevValue = startValue;
    for (final pt in series) {
      final x = dayOffset(pt['date'] as String);
      final y = (pt['value'] as num).toDouble();
      if (spots.isNotEmpty) {
        spots.add(FlSpot(x, prevValue)); // horizontal step
      }
      spots.add(FlSpot(x, y));
      prevValue = y;
    }

    // Which x-values are real data points (not the duplicated step points).
    final dataXSet = series.map((p) => dayOffset(p['date'] as String)).toSet();

    final color = theme.colorScheme.primary;

    // X-axis label formatter.
    String xLabel(double x) {
      final d = firstDate.add(Duration(days: x.toInt()));
      const months = [
        'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
      ];
      return '${months[d.month - 1]} ${d.day}';
    }

    final minY = spots.map((s) => s.y).reduce((a, b) => a < b ? a : b);
    final maxY = spots.map((s) => s.y).reduce((a, b) => a > b ? a : b);
    final yPad = (maxY - minY).abs() < 1 ? 1.0 : (maxY - minY) * 0.1;

    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: SizedBox(
        height: 200,
        child: LineChart(
          LineChartData(
            minY: minY - yPad,
            maxY: maxY + yPad,
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
                  interval: spots.last.x < 7 ? 1 : (spots.last.x / 4).ceilToDouble(),
                  getTitlesWidget: (v, _) => Text(
                    xLabel(v),
                    style: theme.textTheme.bodySmall
                        ?.copyWith(fontSize: 10),
                  ),
                ),
              ),
              topTitles: const AxisTitles(
                  sideTitles: SideTitles(showTitles: false)),
              rightTitles: const AxisTitles(
                  sideTitles: SideTitles(showTitles: false)),
            ),
            lineBarsData: [
              LineChartBarData(
                spots: spots,
                isCurved: false,
                color: color,
                barWidth: 2,
                dotData: FlDotData(
                  show: true,
                  checkToShowDot: (spot, _) => dataXSet.contains(spot.x),
                  getDotPainter: (_, __, ___, ____) => FlDotCirclePainter(
                    radius: 4,
                    color: color,
                    strokeWidth: 0,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
