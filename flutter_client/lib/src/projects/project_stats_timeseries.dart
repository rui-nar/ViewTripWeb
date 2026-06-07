part of 'project_stats_screen.dart';

// ── Enums ─────────────────────────────────────────────────────────────────────

enum _TsMetric { distance, rideTime, avgSpeed, climb }

enum _TsOp { value, cumulative, rolling7, rolling30 }

extension _TsMetricExt on _TsMetric {
  String get label => switch (this) {
        _TsMetric.distance => 'Distance',
        _TsMetric.rideTime => 'Ride time',
        _TsMetric.avgSpeed => 'Avg speed',
        _TsMetric.climb    => 'Climb',
      };

  String get unit => switch (this) {
        _TsMetric.distance => 'km',
        _TsMetric.rideTime => 'h',
        _TsMetric.avgSpeed => 'km/h',
        _TsMetric.climb    => 'm',
      };
}

extension _TsOpExt on _TsOp {
  String get label => switch (this) {
        _TsOp.value      => 'Daily value',
        _TsOp.cumulative => 'Cumulative',
        _TsOp.rolling7   => '7-day avg',
        _TsOp.rolling30  => '30-day avg',
      };
}

// ── Series descriptor ─────────────────────────────────────────────────────────

class _TsSeries {
  final _TsMetric metric;
  final _TsOp op;
  final Color color;

  const _TsSeries(this.metric, this.op, this.color);

  String get label => '${metric.label} · ${op.label}';

  @override
  bool operator ==(Object other) =>
      other is _TsSeries && other.metric == metric && other.op == op;

  @override
  int get hashCode => Object.hash(metric, op);
}

// ── Y-value helpers ───────────────────────────────────────────────────────────

double _tsRawValue(_TsMetric m, Map<String, dynamic> pt) => switch (m) {
      _TsMetric.distance => (pt['distance_m'] as num).toDouble() / 1000,
      _TsMetric.rideTime => (pt['moving_time_s'] as num).toDouble() / 3600,
      _TsMetric.avgSpeed => (pt['avg_speed_ms'] as num).toDouble() * 3.6,
      _TsMetric.climb    => (pt['elevation_m'] as num).toDouble(),
    };

List<double> _tsApplyOp(List<double> raw, List<String> dates, _TsOp op) {
  return switch (op) {
    _TsOp.value      => raw,
    _TsOp.cumulative => _tsCumulative(raw),
    _TsOp.rolling7   => _tsRolling(raw, dates, 7),
    _TsOp.rolling30  => _tsRolling(raw, dates, 30),
  };
}

List<double> _tsCumulative(List<double> values) {
  var sum = 0.0;
  return values.map((v) {
    sum += v;
    return sum;
  }).toList();
}

List<double> _tsRolling(List<double> values, List<String> dates, int windowDays) {
  final result = <double>[];
  for (var i = 0; i < values.length; i++) {
    final anchor     = DateTime.parse(dates[i]);
    final windowStart = anchor.subtract(Duration(days: windowDays - 1));
    var sum   = 0.0;
    var count = 0;
    for (var j = 0; j <= i; j++) {
      final d = DateTime.parse(dates[j]);
      if (!d.isBefore(windowStart)) {
        sum += values[j];
        count++;
      }
    }
    result.add(count > 0 ? sum / count : 0.0);
  }
  return result;
}

String _tsFormatY(double v) {
  final a = v.abs();
  if (a >= 100) return v.toStringAsFixed(0);
  if (a >= 10)  return v.toStringAsFixed(1);
  return v.toStringAsFixed(2);
}

// ── Section widget ────────────────────────────────────────────────────────────

class _RideTimeSeriesSection extends StatefulWidget {
  final List<Map<String, dynamic>> rawSeries;
  const _RideTimeSeriesSection({required this.rawSeries});

  @override
  State<_RideTimeSeriesSection> createState() => _RideTimeSeriesSectionState();
}

class _RideTimeSeriesSectionState extends State<_RideTimeSeriesSection> {
  _TsMetric _metric = _TsMetric.distance;
  _TsOp _op         = _TsOp.value;
  final _active      = <_TsSeries>[];
  var _nextColor     = 0;

  @override
  void initState() {
    super.initState();
    _push(); // Default: Distance · Daily value
  }

  void _push() {
    if (_active.length >= 8) return;
    final candidate = _TsSeries(
      _metric, _op, _counterPalette[_nextColor % _counterPalette.length],
    );
    if (_active.contains(candidate)) return;
    setState(() {
      _active.add(candidate);
      _nextColor++;
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme  = Theme.of(context);
    final canAdd = _active.length < 8;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // ── Selector row ──────────────────────────────────────────────────
        Row(
          children: [
            Expanded(
              child: InputDecorator(
                decoration: const InputDecoration(
                  labelText: 'Metric',
                  border: OutlineInputBorder(),
                  isDense: true,
                  contentPadding:
                      EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                ),
                child: DropdownButton<_TsMetric>(
                  value: _metric,
                  isExpanded: true,
                  isDense: true,
                  underline: const SizedBox.shrink(),
                  items: _TsMetric.values
                      .map((m) =>
                          DropdownMenuItem(value: m, child: Text(m.label)))
                      .toList(),
                  onChanged: (v) => setState(() => _metric = v!),
                ),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: InputDecorator(
                decoration: const InputDecoration(
                  labelText: 'Operation',
                  border: OutlineInputBorder(),
                  isDense: true,
                  contentPadding:
                      EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                ),
                child: DropdownButton<_TsOp>(
                  value: _op,
                  isExpanded: true,
                  isDense: true,
                  underline: const SizedBox.shrink(),
                  items: _TsOp.values
                      .map((o) =>
                          DropdownMenuItem(value: o, child: Text(o.label)))
                      .toList(),
                  onChanged: (v) => setState(() => _op = v!),
                ),
              ),
            ),
            const SizedBox(width: 8),
            IconButton.filled(
              tooltip: canAdd ? 'Add series' : 'Maximum 8 series',
              icon: const Icon(Icons.add),
              onPressed: canAdd ? _push : null,
            ),
          ],
        ),

        // ── Active series chips ───────────────────────────────────────────
        if (_active.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 10),
            child: Wrap(
              spacing: 6,
              runSpacing: 4,
              children: List.generate(_active.length, (i) {
                final s = _active[i];
                return Chip(
                  avatar: CircleAvatar(backgroundColor: s.color, radius: 8),
                  label: Text(s.label,
                      style: theme.textTheme.bodySmall),
                  onDeleted: () => setState(() => _active.removeAt(i)),
                  visualDensity: VisualDensity.compact,
                  materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                );
              }),
            ),
          ),

        // ── Chart ─────────────────────────────────────────────────────────
        if (_active.isNotEmpty)
          _RideTimeSeriesChart(
            rawSeries: widget.rawSeries,
            activeSeries: _active,
          ),
      ],
    );
  }
}

// ── Chart widget ──────────────────────────────────────────────────────────────

class _RideTimeSeriesChart extends StatelessWidget {
  final List<Map<String, dynamic>> rawSeries;
  final List<_TsSeries> activeSeries;

  const _RideTimeSeriesChart({
    required this.rawSeries,
    required this.activeSeries,
  });

  @override
  Widget build(BuildContext context) {
    if (rawSeries.isEmpty) return const SizedBox.shrink();

    final theme  = Theme.of(context);
    final dates  = rawSeries.map((pt) => pt['date'] as String).toList();
    final origin = DateTime.parse(dates.first);

    double dayOff(String ds) =>
        DateTime.parse(ds).difference(origin).inDays.toDouble();

    final bars     = <LineChartBarData>[];
    var globalMin  = double.infinity;
    var globalMax  = double.negativeInfinity;

    for (final s in activeSeries) {
      final raw         = rawSeries.map((pt) => _tsRawValue(s.metric, pt)).toList();
      final transformed = _tsApplyOp(raw, dates, s.op);

      final spots = <FlSpot>[];
      for (var i = 0; i < rawSeries.length; i++) {
        final y = transformed[i];
        if (y < globalMin) globalMin = y;
        if (y > globalMax) globalMax = y;
        spots.add(FlSpot(dayOff(dates[i]), y));
      }

      bars.add(LineChartBarData(
        spots: spots,
        isCurved: false,
        color: s.color,
        barWidth: 2,
        dotData: FlDotData(
          show: rawSeries.length <= 60,
          getDotPainter: (_, __, ___, ____) => FlDotCirclePainter(
            radius: 3,
            color: s.color,
            strokeWidth: 0,
          ),
        ),
      ));
    }

    if (bars.isEmpty) return const SizedBox.shrink();

    final range = (globalMax - globalMin).abs();
    final yPad  = range < 0.01 ? 1.0 : range * 0.1;
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
        height: 220,
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
                  reservedSize: 48,
                  getTitlesWidget: (v, _) => Text(
                    _tsFormatY(v),
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
            lineTouchData: LineTouchData(
              touchTooltipData: LineTouchTooltipData(
                getTooltipItems: (spots) => spots.map((spot) {
                  final s = activeSeries[spot.barIndex];
                  return LineTooltipItem(
                    '${_tsFormatY(spot.y)} ${s.metric.unit}',
                    TextStyle(
                      color: s.color,
                      fontWeight: FontWeight.w600,
                      fontSize: 12,
                    ),
                  );
                }).toList(),
              ),
            ),
            lineBarsData: bars,
          ),
        ),
      ),
    );
  }
}
