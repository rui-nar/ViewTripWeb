import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import 'project_notifier.dart';
import 'strava_import_notifier.dart';

class StravaImportScreen extends StatefulWidget {
  final String projectName;

  const StravaImportScreen({super.key, required this.projectName});

  @override
  State<StravaImportScreen> createState() => _StravaImportScreenState();
}

class _StravaImportScreenState extends State<StravaImportScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context
          .read<StravaImportNotifier>()
          .load(projectName: widget.projectName);
    });
  }

  Future<void> _pickDateRange(StravaImportNotifier notifier) async {
    final now = DateTime.now();
    final initial = DateTimeRange(
      start: notifier.startDate ?? now.subtract(const Duration(days: 365)),
      end: notifier.endDate ?? now,
    );
    final picked = await showDateRangePicker(
      context: context,
      firstDate: DateTime(2000),
      lastDate: now,
      initialDateRange: initial,
    );
    if (picked != null) {
      notifier.setDateRange(picked.start, picked.end);
      notifier.load(projectName: widget.projectName);
    }
  }

  Future<void> _addSelected(BuildContext ctx) async {
    final notifier = ctx.read<StravaImportNotifier>();
    final added = await notifier.addSelected(widget.projectName);
    if (!mounted) return;
    if (notifier.error == null) {
      // Reload the project so the newly-added activities appear immediately
      // in the activity list when we pop back to AppScreen.
      context.read<ProjectNotifier>().load(widget.projectName);
      final pending = notifier.pendingEnrichment;
      final msg = pending > 0
          ? 'Added $added activities. '
            '$pending ${pending == 1 ? "activity" : "activities"} '
            'will have full track data in ~15 min (Strava rate limit).'
          : 'Added $added activities to project.';
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(msg),
          duration: Duration(seconds: pending > 0 ? 8 : 4),
        ),
      );
      context.pop();
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(notifier.error!)),
      );
    }
  }

  static String _formatDate(StravaImportNotifier n) {
    if (n.startDate == null && n.endDate == null) return 'All dates';
    if (n.startDate != null && n.endDate != null) {
      return '${_fmtDay(n.startDate!)} – ${_fmtDay(n.endDate!)}';
    }
    if (n.startDate != null) return 'From ${_fmtDay(n.startDate!)}';
    return 'Until ${_fmtDay(n.endDate!)}';
  }

  static String _fmtDay(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      // AppBar is fully static — projectName comes from widget, no notifier.
      appBar: AppBar(
        leading: BackButton(onPressed: () => context.pop()),
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Import from Strava'),
            Text(
              widget.projectName,
              style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurface.withValues(alpha: 0.7)),
            ),
          ],
        ),
      ),
      body: Column(
        children: [
          // ── Filter bar ───────────────────────────────────────────────────
          // Consumer scoped here: rebuilds on load/filter changes only, NOT
          // on checkbox toggles (those only change selectedIds + newCount).
          Consumer<StravaImportNotifier>(
            builder: (ctx, notifier, _) => Container(
              color: theme.colorScheme.surfaceContainerHighest,
              padding:
                  const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      ActionChip(
                        avatar: const Icon(Icons.date_range, size: 16),
                        label: Text(_formatDate(notifier)),
                        onPressed: notifier.isLoading
                            ? null
                            : () => _pickDateRange(notifier),
                      ),
                      if (notifier.startDate != null ||
                          notifier.endDate != null) ...[
                        const SizedBox(width: 8),
                        IconButton(
                          icon: const Icon(Icons.close, size: 18),
                          tooltip: 'Clear date filter',
                          onPressed: () {
                            notifier.setDateRange(null, null);
                            notifier.load(projectName: widget.projectName);
                          },
                        ),
                      ],
                      const Spacer(),
                      if (notifier.lastResultCached && !notifier.isLoading)
                        Tooltip(
                          message:
                              'Showing cached results. Tap Refresh↺ to re-fetch from Strava.',
                          child: Padding(
                            padding: const EdgeInsets.only(right: 4),
                            child: Icon(Icons.cloud_done_outlined,
                                size: 16,
                                color: theme.colorScheme.onSurface
                                    .withValues(alpha: 0.4)),
                          ),
                        ),
                      TextButton.icon(
                        icon: const Icon(Icons.refresh, size: 18),
                        label: const Text('Refresh'),
                        onPressed: notifier.isLoading
                            ? null
                            : () => notifier.load(
                                  projectName: widget.projectName,
                                  refresh: true,
                                ),
                      ),
                    ],
                  ),
                  if (notifier.allTypes.isNotEmpty)
                    Wrap(
                      spacing: 6,
                      children: notifier.allTypes.map((type) {
                        final selected =
                            notifier.selectedTypes.contains(type);
                        return FilterChip(
                          key: ValueKey(type),
                          label: Text(type),
                          selected: selected,
                          onSelected: (_) {
                            notifier.toggleType(type);
                            notifier.load(projectName: widget.projectName);
                          },
                        );
                      }).toList(),
                    ),
                ],
              ),
            ),
          ),

          // ── Selection count row ──────────────────────────────────────────
          // Selector on (selectedLen, activitiesLen, totalCount) — rebuilds
          // on checkbox taps and load, but NOT on filter chip taps alone.
          Selector<StravaImportNotifier, (int, int, int)>(
            selector: (_, n) =>
                (n.selectedIds.length, n.activities.length, n.totalCount),
            builder: (ctx, counts, __) {
              final (selectedLen, activitiesLen, total) = counts;
              if (activitiesLen == 0) return const SizedBox.shrink();
              final notifier = ctx.read<StravaImportNotifier>();
              return Padding(
                padding: const EdgeInsets.symmetric(
                    horizontal: 16, vertical: 4),
                child: Row(
                  children: [
                    Text(
                      '$selectedLen / $activitiesLen selected'
                      '${total > activitiesLen ? ' ($total total)' : ''}',
                      style: theme.textTheme.bodySmall,
                    ),
                    const Spacer(),
                    TextButton(
                      onPressed: notifier.selectAll,
                      child: const Text('Select all'),
                    ),
                    TextButton(
                      onPressed: notifier.clearSelection,
                      child: const Text('Clear'),
                    ),
                  ],
                ),
              );
            },
          ),

          // ── Activity list body ───────────────────────────────────────────
          // Consumer for structural changes (isLoading, error, activities).
          // Individual tiles use their own Selector for selection state so
          // only the tapped tile rebuilds on each checkbox tap.
          Expanded(
            child: Consumer<StravaImportNotifier>(
              builder: (ctx, notifier, _) {
                if (notifier.isLoading) {
                  return const Center(child: CircularProgressIndicator());
                }
                if (notifier.stravaNotConnected) {
                  return Center(
                    child: Padding(
                      padding: const EdgeInsets.all(32),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.link_off,
                              size: 48,
                              color: theme.colorScheme.onSurface
                                  .withValues(alpha: 0.4)),
                          const SizedBox(height: 16),
                          Text(
                            'Strava not connected',
                            style: theme.textTheme.titleMedium,
                          ),
                          const SizedBox(height: 8),
                          Text(
                            'Connect your Strava account in Settings\nbefore importing activities.',
                            textAlign: TextAlign.center,
                            style: theme.textTheme.bodyMedium?.copyWith(
                                color: theme.colorScheme.onSurface
                                    .withValues(alpha: 0.6)),
                          ),
                          const SizedBox(height: 24),
                          FilledButton.icon(
                            icon: const Icon(Icons.settings_outlined),
                            label: const Text('Go to Settings'),
                            onPressed: () => context.go('/settings'),
                          ),
                        ],
                      ),
                    ),
                  );
                }
                if (notifier.error != null) {
                  return Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Text(notifier.error!,
                          style:
                              TextStyle(color: theme.colorScheme.error)),
                    ),
                  );
                }
                if (notifier.activities.isEmpty) {
                  return Center(
                    child: Text('No activities found.',
                        style: theme.textTheme.bodyMedium),
                  );
                }
                return ListView.builder(
                  // +1 for the Load more / spinner / footer row
                  itemCount: notifier.activities.length + 1,
                  itemBuilder: (context, i) {
                    if (i == notifier.activities.length) {
                      return _LoadMoreFooter(
                        notifier: notifier,
                        theme: theme,
                      );
                    }
                    final a = notifier.activities[i];
                    final id = a['id'] as int;
                    final inProject = a['in_project'] == true;
                    return _ActivityTile(
                      key: ValueKey(id),
                      activity: a,
                      onToggle: () => notifier.toggleSelect(id),
                      onRefetch: inProject
                          ? () async {
                              final pn = context.read<ProjectNotifier>();
                              await pn.refreshActivity(id);
                              if (!context.mounted) return;
                              final err = pn.error;
                              ScaffoldMessenger.of(context).showSnackBar(
                                SnackBar(
                                  content: Text(err != null
                                      ? 'Re-fetch failed: $err'
                                      : 'Activity updated.'),
                                  duration: Duration(seconds: err != null ? 6 : 3),
                                ),
                              );
                            }
                          : null,
                    );
                  },
                );
              },
            ),
          ),
        ],
      ),

      // ── Bottom bar ────────────────────────────────────────────────────────
      // Selector on (newCount, isLoading) — rebuilds only when those change,
      // NOT on every checkbox tap that doesn't change the count.
      bottomNavigationBar: Selector<StravaImportNotifier, (int, bool)>(
        selector: (_, n) => (n.newCount, n.isLoading),
        builder: (ctx, state, __) {
          final (newCount, isLoading) = state;
          return SafeArea(
            child: Padding(
              padding:
                  const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: ElevatedButton.icon(
                onPressed: isLoading || newCount == 0
                    ? null
                    : () => _addSelected(ctx),
                icon: const Icon(Icons.add),
                label: Text(
                  newCount == 0
                      ? 'Select activities to add'
                      : 'Add $newCount to project',
                ),
                style: ElevatedButton.styleFrom(
                  minimumSize: const Size(double.infinity, 48),
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}

// ── _ActivityTile ─────────────────────────────────────────────────────────────
// Uses Selector<bool> scoped to selectedIds.contains(id) so only THIS tile
// rebuilds when its selection state changes, not the whole list.

class _ActivityTile extends StatefulWidget {
  final Map<String, dynamic> activity;
  final VoidCallback onToggle;
  final Future<void> Function()? onRefetch;

  const _ActivityTile({
    super.key,
    required this.activity,
    required this.onToggle,
    this.onRefetch,
  });

  @override
  State<_ActivityTile> createState() => _ActivityTileState();
}

class _ActivityTileState extends State<_ActivityTile> {
  bool _refetching = false;

  Future<void> _handleRefetch() async {
    setState(() => _refetching = true);
    try {
      await widget.onRefetch!();
    } finally {
      if (mounted) setState(() => _refetching = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final activity = widget.activity;
    final id = activity['id'] as int;
    final inProject = activity['in_project'] == true;
    final type = activity['type'] as String? ?? '';
    final name = activity['name'] as String? ?? '';
    final distRaw = activity['distance'] as num?;
    final dist =
        distRaw != null ? '${(distRaw / 1000).toStringAsFixed(1)} km' : '';
    final dateStr =
        (activity['start_date_local'] as String? ?? '').split('T').first;

    return Selector<StravaImportNotifier, bool>(
      selector: (_, n) => n.selectedIds.contains(id),
      builder: (context, selected, __) {
        final theme = Theme.of(context);
        return ListTile(
          leading: Checkbox(
            value: selected,
            onChanged: (_) => widget.onToggle(),
          ),
          title: Text(
            name,
            style: inProject && !selected
                ? TextStyle(
                    color: theme.colorScheme.onSurface
                        .withValues(alpha: 0.4))
                : null,
          ),
          subtitle: Text('$type  $dist  $dateStr'),
          trailing: inProject
              ? Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (widget.onRefetch != null)
                      _refetching
                          ? const SizedBox(
                              width: 24,
                              height: 24,
                              child: Padding(
                                padding: EdgeInsets.all(4),
                                child: CircularProgressIndicator(strokeWidth: 2),
                              ),
                            )
                          : IconButton(
                              icon: const Icon(Icons.refresh, size: 18),
                              tooltip: 'Re-fetch from Strava',
                              visualDensity: VisualDensity.compact,
                              onPressed: _handleRefetch,
                            ),
                    Tooltip(
                      message: 'Already in project',
                      child: Icon(Icons.check,
                          size: 16, color: theme.colorScheme.primary),
                    ),
                  ],
                )
              : null,
          onTap: widget.onToggle,
        );
      },
    );
  }
}

// ── _LoadMoreFooter ───────────────────────────────────────────────────────────

class _LoadMoreFooter extends StatelessWidget {
  final StravaImportNotifier notifier;
  final ThemeData theme;

  const _LoadMoreFooter({required this.notifier, required this.theme});

  @override
  Widget build(BuildContext context) {
    if (notifier.isLoadingMore) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 16),
        child: Center(child: CircularProgressIndicator()),
      );
    }
    if (notifier.hasMore) {
      return Padding(
        padding:
            const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        child: OutlinedButton(
          onPressed: notifier.loadMore,
          child: Text(
            'Load more '
            '(${notifier.activities.length} / ${notifier.totalCount})',
          ),
        ),
      );
    }
    if (notifier.activities.isNotEmpty) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 12),
        child: Center(
          child: Text(
            'All ${notifier.totalCount} activities loaded',
            style: theme.textTheme.bodySmall?.copyWith(
              color:
                  theme.colorScheme.onSurface.withValues(alpha: 0.4),
            ),
          ),
        ),
      );
    }
    return const SizedBox.shrink();
  }
}
