/// Project statistics screen — shows pre-computed trip stats for a project.
library;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

import 'project_service.dart';

// ── Helpers ───────────────────────────────────────────────────────────────────

String _fmtDistance(double metres) {
  final km = metres / 1000;
  return '${km.toStringAsFixed(1)} km';
}

String _fmtDuration(int seconds) {
  if (seconds <= 0) return '0m';
  final d = seconds ~/ 86400;
  final h = (seconds % 86400) ~/ 3600;
  final m = (seconds % 3600) ~/ 60;
  final parts = <String>[];
  if (d > 0) parts.add('${d}d');
  if (h > 0) parts.add('${h}h');
  if (m > 0 || parts.isEmpty) parts.add('${m}m');
  return parts.join(' ');
}

String _fmtElevation(double metres) => '${metres.toStringAsFixed(0)} m';

String _fmtDate(String? isoDate) {
  if (isoDate == null || isoDate.isEmpty) return '—';
  try {
    final dt = DateTime.parse(isoDate);
    const months = [
      'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
    ];
    return '${months[dt.month - 1]} ${dt.day}';
  } catch (_) {
    return isoDate;
  }
}

/// Capitalise first letter of a type string (e.g. "ride" → "Ride").
String _capitalize(String s) =>
    s.isEmpty ? s : s[0].toUpperCase() + s.substring(1);

// ── Sleeping group colours ─────────────────────────────────────────────────────

const _groupColors = {
  'Outdoors': Color(0xFF22C55E),
  'Indoors':  Color(0xFF3B82F6),
  'Other':    Color(0xFFA855F7),
  'No data':  Color(0xFF9E9E9E),
};

Color _outerModeColor(String group, int idxInGroup) {
  final base = _groupColors[group] ?? const Color(0xFF9E9E9E);
  final hsl = HSLColor.fromColor(base);
  return hsl.withLightness((hsl.lightness + 0.12 * idxInGroup).clamp(0.0, 0.88)).toColor();
}

// ── Mode colours ──────────────────────────────────────────────────────────────

const _modeColors = {
  'ride':   Color(0xFFFF6B35),
  'flight': Color(0xFF607D8B),
  'train':  Color(0xFF4CAF50),
  'boat':   Color(0xFF00BCD4),
  'bus':    Color(0xFF9C27B0),
};

const _modeLabels = {
  'ride':   'Ride',
  'flight': 'Flight',
  'train':  'Train',
  'boat':   'Boat',
  'bus':    'Bus',
};

// ── Widgets ───────────────────────────────────────────────────────────────────

class _StatCard extends StatelessWidget {
  final String label;
  final String value;
  final IconData icon;

  const _StatCard({required this.label, required this.value, required this.icon});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 28, color: theme.colorScheme.primary),
            const SizedBox(height: 6),
            Text(value,
                style: theme.textTheme.titleLarge
                    ?.copyWith(fontWeight: FontWeight.bold)),
            const SizedBox(height: 2),
            Text(label,
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
          ],
        ),
      ),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  final String title;
  const _SectionHeader(this.title);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 24, bottom: 8),
      child: Text(title,
          style: Theme.of(context)
              .textTheme
              .titleMedium
              ?.copyWith(fontWeight: FontWeight.w600)),
    );
  }
}

/// A simple two-column label / value row used in count tables.
class _CountRow extends StatelessWidget {
  final String label;
  final String value;

  const _CountRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Expanded(child: Text(label)),
          Text(value,
              style: Theme.of(context)
                  .textTheme
                  .bodyMedium
                  ?.copyWith(fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }
}

// ── Screen ────────────────────────────────────────────────────────────────────

class ProjectStatsScreen extends StatefulWidget {
  final String projectName;
  final List<String> availableTags;
  final Map<String, String> sleepingOptionGroups;

  const ProjectStatsScreen({
    super.key,
    required this.projectName,
    this.availableTags = const [],
    this.sleepingOptionGroups = const {},
  });

  @override
  State<ProjectStatsScreen> createState() => _ProjectStatsScreenState();
}

class _ProjectStatsScreenState extends State<ProjectStatsScreen> {
  late Future<Map<String, dynamic>> _statsFuture;
  Set<String> _selectedTags = {};
  List<String> _tagOptions = [];

  @override
  void initState() {
    super.initState();
    _tagOptions = List.of(widget.availableTags);
    _load();
  }

  void _load() {
    final future = ProjectService()
        .getStats(widget.projectName, tags: _selectedTags.toList());
    future.then((data) {
      if (!mounted) return;
      final opts = data['tag_options'];
      if (opts is List) {
        setState(() => _tagOptions = opts.cast<String>());
      }
    });
    _statsFuture = future;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('${widget.projectName} — Statistics')),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // ── Tag filter ───────────────────────────────────────────────────
          if (_tagOptions.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
              child: Wrap(
                spacing: 6,
                runSpacing: 4,
                children: [
                  FilterChip(
                    label: const Text('All'),
                    selected: _selectedTags.isEmpty,
                    onSelected: (_) => setState(() {
                      _selectedTags = {};
                      _load();
                    }),
                  ),
                  for (final tag in _tagOptions)
                    FilterChip(
                      label: Text(tag),
                      selected: _selectedTags.contains(tag),
                      onSelected: (on) => setState(() {
                        if (on) {
                          _selectedTags = {..._selectedTags, tag};
                        } else {
                          _selectedTags = {..._selectedTags}..remove(tag);
                        }
                        _load();
                      }),
                    ),
                ],
              ),
            ),
          // ── Stats content ─────────────────────────────────────────────
          Expanded(
            child: FutureBuilder<Map<String, dynamic>>(
              future: _statsFuture,
              builder: (context, snap) {
                if (snap.connectionState != ConnectionState.done) {
                  return const Center(child: CircularProgressIndicator());
                }
                if (snap.hasError) {
                  return Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text('Failed to load stats: ${snap.error}',
                            textAlign: TextAlign.center),
                        const SizedBox(height: 12),
                        ElevatedButton(
                          onPressed: () => setState(_load),
                          child: const Text('Retry'),
                        ),
                      ],
                    ),
                  );
                }

                final s = snap.data!;
                return _StatsBody(
                  stats: s,
                  projectName: widget.projectName,
                  sleepingOptionGroups: widget.sleepingOptionGroups,
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

// ── Body (extracted so FutureBuilder stays slim) ──────────────────────────────

class _StatsBody extends StatelessWidget {
  final Map<String, dynamic> stats;
  final String projectName;
  final Map<String, String> sleepingOptionGroups;

  const _StatsBody({
    required this.stats,
    required this.projectName,
    this.sleepingOptionGroups = const {},
  });

  @override
  Widget build(BuildContext context) {
    final totalDistM = (stats['total_distance_m'] as num?)?.toDouble() ?? 0.0;
    final totalMovS = (stats['total_moving_s'] as num?)?.toInt() ?? 0;
    final totalElevM = (stats['total_elevation_m'] as num?)?.toDouble() ?? 0.0;

    final activityCounts =
        (stats['activity_counts'] as Map<String, dynamic>?) ?? {};
    final segmentCounts =
        (stats['segment_counts'] as Map<String, dynamic>?) ?? {};

    final rideDays = (stats['ride_days'] as num?)?.toInt() ?? 0;
    final rideAvgDistPerDay =
        (stats['ride_avg_dist_per_day_m'] as num?)?.toDouble() ?? 0.0;
    final rideTotalElev =
        (stats['ride_total_elev_m'] as num?)?.toDouble() ?? 0.0;
    final bestRideDist = (stats['best_ride_dist_m'] as num?)?.toDouble() ?? 0.0;
    final bestRideDistDay = stats['best_ride_dist_day'] as String?;
    final bestRideElev = (stats['best_ride_elev_m'] as num?)?.toDouble() ?? 0.0;
    final bestRideElevDay = stats['best_ride_elev_day'] as String?;

    final byMode =
        (stats['distance_by_mode'] as Map<String, dynamic>?) ?? {};

    final counterStats = (stats['counters'] as List?)
            ?.cast<Map<String, dynamic>>() ??
        const <Map<String, dynamic>>[];

    final sleepingCounts =
        (stats['sleeping_counts'] as Map<String, dynamic>?) ?? {};
    final sleepingEntries = sleepingCounts.entries
        .where((e) => (e.value as num? ?? 0) > 0)
        .toList()
      ..sort((a, b) => (b.value as num).compareTo(a.value as num));
    final totalSleepingNights =
        sleepingEntries.fold<int>(0, (s, e) => s + (e.value as num).toInt());

    // Filter to modes with non-zero distance.
    final modeEntries = _modeColors.entries
        .where((e) => ((byMode[e.key] as num?)?.toDouble() ?? 0.0) > 0)
        .toList();

    final totalModeM = modeEntries.fold<double>(
        0, (acc, e) => acc + ((byMode[e.key] as num?)?.toDouble() ?? 0.0));

    // Sort activity types: ride first, then alphabetical.
    final sortedActivityTypes = activityCounts.keys.toList()
      ..sort((a, b) {
        if (a == 'ride') return -1;
        if (b == 'ride') return 1;
        return a.compareTo(b);
      });

    // Sort segment types in a fixed display order.
    const segOrder = ['flight', 'train', 'bus', 'boat'];
    final sortedSegTypes = segmentCounts.keys.toList()
      ..sort((a, b) {
        final ai = segOrder.indexOf(a);
        final bi = segOrder.indexOf(b);
        if (ai == -1 && bi == -1) return a.compareTo(b);
        if (ai == -1) return 1;
        if (bi == -1) return -1;
        return ai.compareTo(bi);
      });

    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // ── Summary cards ──────────────────────────────────────────────
          _SectionHeader('Overview'),
          Row(
            children: [
              Expanded(
                child: _StatCard(
                  icon: Icons.route,
                  label: 'Total distance',
                  value: _fmtDistance(totalDistM),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: _StatCard(
                  icon: Icons.timer_outlined,
                  label: 'Moving time',
                  value: _fmtDuration(totalMovS),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: _StatCard(
                  icon: Icons.terrain,
                  label: 'Elevation gain',
                  value: _fmtElevation(totalElevM),
                ),
              ),
            ],
          ),

          // ── Activity & segment counts ──────────────────────────────────
          if (activityCounts.isNotEmpty || segmentCounts.isNotEmpty) ...[
            _SectionHeader('Counts'),
            Card(
              child: Padding(
                padding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (activityCounts.isNotEmpty) ...[
                      Text('Activities',
                          style: Theme.of(context)
                              .textTheme
                              .bodySmall
                              ?.copyWith(
                                  color: Theme.of(context)
                                      .colorScheme
                                      .onSurfaceVariant)),
                      const SizedBox(height: 4),
                      ...sortedActivityTypes.map((type) => _CountRow(
                            label: _capitalize(type),
                            value:
                                '${activityCounts[type]}',
                          )),
                    ],
                    if (activityCounts.isNotEmpty && segmentCounts.isNotEmpty)
                      const Divider(height: 20),
                    if (segmentCounts.isNotEmpty) ...[
                      Text('Transportation segments',
                          style: Theme.of(context)
                              .textTheme
                              .bodySmall
                              ?.copyWith(
                                  color: Theme.of(context)
                                      .colorScheme
                                      .onSurfaceVariant)),
                      const SizedBox(height: 4),
                      ...sortedSegTypes.map((type) => _CountRow(
                            label: _modeLabels[type] ?? _capitalize(type),
                            value: '${segmentCounts[type]}',
                          )),
                    ],
                  ],
                ),
              ),
            ),
          ],

          // ── Ride highlights ────────────────────────────────────────────
          if (rideDays > 0) ...[
            _SectionHeader('Ride highlights'),
            Card(
              child: Column(
                children: [
                  ListTile(
                    leading: const Icon(Icons.calendar_today_outlined),
                    title: const Text('Days with rides'),
                    trailing: Text('$rideDays',
                        style: Theme.of(context).textTheme.titleMedium),
                  ),
                  if (rideAvgDistPerDay > 0)
                    ListTile(
                      leading: const Icon(Icons.straighten),
                      title: const Text('Average distance per day'),
                      trailing: Text(
                        _fmtDistance(rideAvgDistPerDay),
                        style: Theme.of(context).textTheme.bodyMedium,
                      ),
                    ),
                  if (rideTotalElev > 0)
                    ListTile(
                      leading: const Icon(Icons.terrain),
                      title: const Text('Total elevation gain'),
                      trailing: Text(
                        _fmtElevation(rideTotalElev),
                        style: Theme.of(context).textTheme.bodyMedium,
                      ),
                    ),
                  if (bestRideDist > 0)
                    ListTile(
                      leading: const Icon(Icons.emoji_events_outlined),
                      title: const Text('Best day — distance'),
                      trailing: Text(
                        '${_fmtDistance(bestRideDist)}'
                        '${bestRideDistDay != null ? '  ·  ${_fmtDate(bestRideDistDay)}' : ''}',
                        style: Theme.of(context).textTheme.bodyMedium,
                      ),
                    ),
                  if (bestRideElev > 0)
                    ListTile(
                      leading: const Icon(Icons.trending_up),
                      title: const Text('Best day — elevation'),
                      trailing: Text(
                        '${_fmtElevation(bestRideElev)}'
                        '${bestRideElevDay != null ? '  ·  ${_fmtDate(bestRideElevDay)}' : ''}',
                        style: Theme.of(context).textTheme.bodyMedium,
                      ),
                    ),
                ],
              ),
            ),
          ],

          // ── Distance by mode pie chart ─────────────────────────────────
          if (modeEntries.isNotEmpty) ...[
            _SectionHeader('Distance by mode'),
            SizedBox(
              height: 240,
              child: PieChart(
                PieChartData(
                  sectionsSpace: 2,
                  centerSpaceRadius: 48,
                  sections: modeEntries.map((e) {
                    final m = (byMode[e.key] as num?)?.toDouble() ?? 0.0;
                    final pct = totalModeM > 0 ? m / totalModeM * 100 : 0.0;
                    return PieChartSectionData(
                      color: e.value,
                      value: m,
                      title: '${pct.toStringAsFixed(0)}%',
                      radius: 72,
                      titleStyle: const TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                        color: Colors.white,
                      ),
                    );
                  }).toList(),
                ),
              ),
            ),
            const SizedBox(height: 12),
            // Legend
            Wrap(
              spacing: 16,
              runSpacing: 8,
              children: modeEntries.map((e) {
                final m = (byMode[e.key] as num?)?.toDouble() ?? 0.0;
                return Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Container(
                      width: 12,
                      height: 12,
                      decoration: BoxDecoration(
                          color: e.value, shape: BoxShape.circle),
                    ),
                    const SizedBox(width: 4),
                    Text('${_modeLabels[e.key] ?? e.key}  '
                        '${_fmtDistance(m)}'),
                  ],
                );
              }).toList(),
            ),
          ],

          // ── Sleeping nested donut ──────────────────────────────────────
          if (sleepingEntries.isNotEmpty) ...[
            _SectionHeader('Nights by sleeping mode'),
            Builder(builder: (context) {
              const groupOrder = ['Outdoors', 'Indoors', 'Other', 'No data'];

              // Inner ring: group → total count
              final groupCounts = <String, int>{};
              for (final e in sleepingEntries) {
                final g = e.key == 'No data'
                    ? 'No data'
                    : (sleepingOptionGroups[e.key] ?? 'Other');
                groupCounts[g] = (groupCounts[g] ?? 0) + (e.value as num).toInt();
              }

              // Outer ring: ordered by group, then by count desc within group
              final orderedOuter = <(String, MapEntry<String, dynamic>)>[];
              for (final g in groupOrder) {
                final members = sleepingEntries
                    .where((e) => (e.key == 'No data'
                            ? 'No data'
                            : (sleepingOptionGroups[e.key] ?? 'Other')) == g)
                    .toList()
                  ..sort((a, b) => (b.value as num).compareTo(a.value as num));
                for (final m in members) { orderedOuter.add((g, m)); }
              }

              // Pre-compute local index within each group for colour shading
              final counters = <String, int>{};
              final localIdxList = orderedOuter.map((o) {
                final idx = counters[o.$1] ?? 0;
                counters[o.$1] = idx + 1;
                return idx;
              }).toList();

              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SizedBox(
                    height: 260,
                    child: Stack(
                      alignment: Alignment.center,
                      children: [
                        // Outer ring — individual modes
                        PieChart(PieChartData(
                          centerSpaceRadius: 70,
                          sectionsSpace: 1,
                          sections: orderedOuter.indexed.map((pair) {
                            final globalIdx = pair.$1;
                            final group = pair.$2.$1;
                            final entry = pair.$2.$2;
                            final count = (entry.value as num).toInt();
                            final pct = totalSleepingNights > 0
                                ? count / totalSleepingNights * 100
                                : 0.0;
                            return PieChartSectionData(
                              color: _outerModeColor(group, localIdxList[globalIdx]),
                              value: count.toDouble(),
                              title: pct >= 5 ? '${pct.toStringAsFixed(0)}%' : '',
                              radius: 46,
                              titleStyle: const TextStyle(
                                fontSize: 10,
                                fontWeight: FontWeight.bold,
                                color: Colors.white,
                              ),
                            );
                          }).toList(),
                        )),
                        // Inner ring — groups
                        PieChart(PieChartData(
                          centerSpaceRadius: 32,
                          sectionsSpace: 2,
                          sections: groupOrder
                              .where((g) => groupCounts.containsKey(g))
                              .map((g) {
                            final count = groupCounts[g]!;
                            final pct = totalSleepingNights > 0
                                ? count / totalSleepingNights * 100
                                : 0.0;
                            return PieChartSectionData(
                              color: _groupColors[g] ?? const Color(0xFF9E9E9E),
                              value: count.toDouble(),
                              title: pct >= 8 ? g : '',
                              radius: 36,
                              titleStyle: const TextStyle(
                                fontSize: 10,
                                fontWeight: FontWeight.bold,
                                color: Colors.white,
                              ),
                            );
                          }).toList(),
                        )),
                      ],
                    ),
                  ),
                  const SizedBox(height: 12),
                  // Two-level legend
                  ...groupOrder
                      .where((g) => groupCounts.containsKey(g))
                      .map((g) {
                    final groupCount = groupCounts[g]!;
                    final members = orderedOuter
                        .where((o) => o.$1 == g)
                        .toList();
                    return Padding(
                      padding: const EdgeInsets.only(bottom: 6),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(children: [
                            Container(
                              width: 12, height: 12,
                              decoration: BoxDecoration(
                                color: _groupColors[g] ?? const Color(0xFF9E9E9E),
                                shape: BoxShape.circle,
                              ),
                            ),
                            const SizedBox(width: 6),
                            Text(
                              '$g  $groupCount',
                              style: Theme.of(context).textTheme.bodyMedium
                                  ?.copyWith(fontWeight: FontWeight.w600),
                            ),
                          ]),
                          Padding(
                            padding: const EdgeInsets.only(left: 18, top: 2),
                            child: Wrap(
                              spacing: 10,
                              runSpacing: 2,
                              children: members.indexed.map((mp) {
                                final localIdx = mp.$1;
                                final entry = mp.$2.$2;
                                final count = (entry.value as num).toInt();
                                return Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    Container(
                                      width: 8, height: 8,
                                      decoration: BoxDecoration(
                                        color: _outerModeColor(g, localIdx),
                                        shape: BoxShape.circle,
                                      ),
                                    ),
                                    const SizedBox(width: 4),
                                    Text(
                                      '${entry.key}  $count',
                                      style: Theme.of(context).textTheme.bodySmall,
                                    ),
                                  ],
                                );
                              }).toList(),
                            ),
                          ),
                        ],
                      ),
                    );
                  }),
                ],
              );
            }),
          ],

          // ── Counters ───────────────────────────────────────────────────
          if (counterStats.isNotEmpty) ...[
            _SectionHeader('Counters'),
            _CounterSection(counterStats: counterStats),
          ],

          const SizedBox(height: 24),
        ],
      ),
    );
  }
}

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
