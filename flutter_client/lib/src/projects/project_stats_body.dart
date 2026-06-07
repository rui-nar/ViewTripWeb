part of 'project_stats_screen.dart';

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

    final rideSeries = (stats['ride_time_series'] as List?)
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

    final distPerTagRaw =
        (stats['distance_per_tag'] as Map<String, dynamic>?) ?? {};
    final tagPieEntries = distPerTagRaw.entries
        .map((e) => MapEntry(e.key, (e.value as num).toDouble()))
        .where((e) => e.value > 0)
        .toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    final totalTagDist =
        tagPieEntries.fold<double>(0, (s, e) => s + e.value);

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
          // ── Distance per tag pie chart ────────────────────────────────
          if (tagPieEntries.length >= 2) ...[
            _SectionHeader('Distance by tag'),
            SizedBox(
              height: 220,
              child: PieChart(
                PieChartData(
                  sectionsSpace: 2,
                  centerSpaceRadius: 44,
                  sections: tagPieEntries.indexed.map((pair) {
                    final idx = pair.$1;
                    final e = pair.$2;
                    final pct = totalTagDist > 0
                        ? e.value / totalTagDist * 100
                        : 0.0;
                    return PieChartSectionData(
                      color: _counterPalette[idx % _counterPalette.length],
                      value: e.value,
                      title: '${pct.toStringAsFixed(0)}%',
                      radius: 68,
                      titleStyle: const TextStyle(
                        fontSize: 11,
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
              children: tagPieEntries.indexed.map((pair) {
                final idx = pair.$1;
                final e = pair.$2;
                return Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Container(
                      width: 12,
                      height: 12,
                      decoration: BoxDecoration(
                        color: _counterPalette[idx % _counterPalette.length],
                        shape: BoxShape.circle,
                      ),
                    ),
                    const SizedBox(width: 4),
                    Text('${e.key}  ${_fmtDistance(e.value)}'),
                  ],
                );
              }).toList(),
            ),
            const SizedBox(height: 8),
          ],

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

          // ── Ride progression chart ────────────────────────────────────
          if (rideSeries.isNotEmpty) ...[
            _SectionHeader('Progression'),
            _RideTimeSeriesSection(rawSeries: rideSeries),
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
              final groupIdxCounters = <String, int>{};
              final localIdxList = orderedOuter.map((o) {
                final idx = groupIdxCounters[o.$1] ?? 0;
                groupIdxCounters[o.$1] = idx + 1;
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
