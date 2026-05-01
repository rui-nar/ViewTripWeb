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

// ── Sleeping colours (cycling palette) ────────────────────────────────────────

const _sleepingPalette = [
  Color(0xFF6366F1), // indigo
  Color(0xFF10B981), // emerald
  Color(0xFFF59E0B), // amber
  Color(0xFFEF4444), // red
  Color(0xFF3B82F6), // blue
  Color(0xFFEC4899), // pink
  Color(0xFF14B8A6), // teal
  Color(0xFFF97316), // orange
];

Color _sleepingColor(int index) => _sleepingPalette[index % _sleepingPalette.length];

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

  const ProjectStatsScreen({
    super.key,
    required this.projectName,
    this.availableTags = const [],
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
                return _StatsBody(stats: s, projectName: widget.projectName);
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

  const _StatsBody({required this.stats, required this.projectName});

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

          // ── Sleeping pie chart ─────────────────────────────────────────
          if (sleepingEntries.isNotEmpty) ...[
            _SectionHeader('Nights by sleeping mode'),
            SizedBox(
              height: 240,
              child: PieChart(
                PieChartData(
                  sectionsSpace: 2,
                  centerSpaceRadius: 48,
                  sections: sleepingEntries.indexed.map((pair) {
                    final idx = pair.$1;
                    final entry = pair.$2;
                    final count = (entry.value as num).toInt();
                    final pct = totalSleepingNights > 0
                        ? count / totalSleepingNights * 100
                        : 0.0;
                    return PieChartSectionData(
                      color: _sleepingColor(idx),
                      value: count.toDouble(),
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
            Wrap(
              spacing: 16,
              runSpacing: 8,
              children: sleepingEntries.indexed.map((pair) {
                final idx = pair.$1;
                final entry = pair.$2;
                final count = (entry.value as num).toInt();
                return Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Container(
                      width: 12,
                      height: 12,
                      decoration: BoxDecoration(
                          color: _sleepingColor(idx), shape: BoxShape.circle),
                    ),
                    const SizedBox(width: 4),
                    Text('${entry.key}  ·  ${count}n'),
                  ],
                );
              }).toList(),
            ),
          ],

          const SizedBox(height: 24),
        ],
      ),
    );
  }
}
