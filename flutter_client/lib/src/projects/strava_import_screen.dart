import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

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

  Future<void> _addSelected(StravaImportNotifier notifier) async {
    final added = await notifier.addSelected(widget.projectName);
    if (!mounted) return;
    if (notifier.error == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Added $added activities to project.')),
      );
      context.pop();
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(notifier.error!)),
      );
    }
  }

  String _formatDate(StravaImportNotifier n) {
    if (n.startDate == null && n.endDate == null) return 'All dates';
    if (n.startDate != null && n.endDate != null) {
      return '${_fmtDay(n.startDate!)} – ${_fmtDay(n.endDate!)}';
    }
    if (n.startDate != null) return 'From ${_fmtDay(n.startDate!)}';
    return 'Until ${_fmtDay(n.endDate!)}';
  }

  String _fmtDay(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Consumer<StravaImportNotifier>(
      builder: (context, notifier, _) {
        return Scaffold(
            appBar: AppBar(
              title: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('Import from Strava'),
                  Text(
                    widget.projectName,
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: theme.colorScheme.onSurface.withValues(alpha: 0.7)),
                  ),
                ],
              ),
            ),
            body: Column(
              children: [
                // ── Filter bar ────────────────────────────────────────────
                Container(
                  color: theme.colorScheme.surfaceContainerHighest,
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      // Date range chip
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
                          TextButton.icon(
                            icon: const Icon(Icons.refresh, size: 18),
                            label: const Text('Refresh'),
                            onPressed: notifier.isLoading
                                ? null
                                : () =>
                                    notifier.load(projectName: widget.projectName),
                          ),
                        ],
                      ),
                      // Activity type chips
                      if (notifier.allTypes.isNotEmpty)
                        Wrap(
                          spacing: 6,
                          children: notifier.allTypes.map((type) {
                            final selected =
                                notifier.selectedTypes.contains(type);
                            return FilterChip(
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

                // ── Selection controls ────────────────────────────────────
                if (notifier.activities.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                    child: Row(
                      children: [
                        Text(
                          '${notifier.selectedIds.length} / ${notifier.activities.length} selected',
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
                  ),

                // ── Activity list ─────────────────────────────────────────
                Expanded(
                  child: notifier.isLoading
                      ? const Center(child: CircularProgressIndicator())
                      : notifier.error != null
                          ? Center(
                              child: Padding(
                                padding: const EdgeInsets.all(24),
                                child: Text(notifier.error!,
                                    style: TextStyle(
                                        color: theme.colorScheme.error)),
                              ),
                            )
                          : notifier.activities.isEmpty
                              ? Center(
                                  child: Text('No activities found.',
                                      style: theme.textTheme.bodyMedium),
                                )
                              : ListView.builder(
                                  itemCount: notifier.activities.length,
                                  itemBuilder: (context, i) {
                                    final a = notifier.activities[i];
                                    final id = a['id'] as int;
                                    final inProject =
                                        a['in_project'] == true;
                                    final selected =
                                        notifier.selectedIds.contains(id);
                                    final type = a['type'] as String? ?? '';
                                    final name = a['name'] as String? ?? '';
                                    final distRaw = a['distance'] as num?;
                                    final dist = distRaw != null
                                        ? '${(distRaw / 1000).toStringAsFixed(1)} km'
                                        : '';
                                    final dateStr =
                                        (a['start_date_local'] as String? ?? '')
                                            .split('T')
                                            .first;

                                    return ListTile(
                                      leading: Checkbox(
                                        value: selected,
                                        onChanged: (_) =>
                                            notifier.toggleSelect(id),
                                      ),
                                      title: Text(
                                        name,
                                        style: inProject && !selected
                                            ? TextStyle(
                                                color: theme
                                                    .colorScheme.onSurface
                                                    .withValues(alpha: 0.4))
                                            : null,
                                      ),
                                      subtitle: Text('$type  $dist  $dateStr'),
                                      trailing: inProject
                                          ? Tooltip(
                                              message: 'Already in project',
                                              child: Icon(Icons.check,
                                                  size: 16,
                                                  color: theme
                                                      .colorScheme.primary),
                                            )
                                          : null,
                                      onTap: () => notifier.toggleSelect(id),
                                    );
                                  },
                                ),
                ),
              ],
            ),

            // ── Bottom bar ────────────────────────────────────────────────
            bottomNavigationBar: SafeArea(
              child: Padding(
                padding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                child: ElevatedButton.icon(
                  onPressed: notifier.isLoading ||
                          notifier.selectedIds.isEmpty
                      ? null
                      : () => _addSelected(notifier),
                  icon: const Icon(Icons.add),
                  label: Text(
                    notifier.selectedIds.isEmpty
                        ? 'Select activities to add'
                        : 'Add ${notifier.selectedIds.length} to project',
                  ),
                  style: ElevatedButton.styleFrom(
                    minimumSize: const Size(double.infinity, 48),
                  ),
                ),
              ),
            ),
          );
      },
    );
  }
}
