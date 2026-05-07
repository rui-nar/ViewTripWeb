import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'sync_import_notifier.dart';

class SyncImportDialog extends StatefulWidget {
  final String projectName;

  const SyncImportDialog({super.key, required this.projectName});

  @override
  State<SyncImportDialog> createState() => _SyncImportDialogState();
}

class _SyncImportDialogState extends State<SyncImportDialog> {
  Future<void> _import() async {
    final notifier = context.read<SyncImportNotifier>();
    final added = await notifier.importSelected(widget.projectName);
    if (!mounted) return;
    if (notifier.error == null || added > 0) {
      Navigator.of(context).pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<SyncImportNotifier>(
      builder: (context, notifier, _) {
        final hasStrava = notifier.stravaActivities.isNotEmpty;
        final hasPs = notifier.psSteps.isNotEmpty;
        final hasBoth = hasStrava && hasPs;
        final tabCount = (hasStrava ? 1 : 0) + (hasPs ? 1 : 0);

        final Widget listContent = hasBoth
            ? TabBarView(
                children: [
                  _StravaList(notifier: notifier),
                  _PsList(notifier: notifier),
                ],
              )
            : (hasStrava
                ? _StravaList(notifier: notifier)
                : _PsList(notifier: notifier));

        return Dialog(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            child: DefaultTabController(
              length: tabCount,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  // Title row
                  Padding(
                    padding: const EdgeInsets.fromLTRB(20, 16, 8, 0),
                    child: Row(
                      children: [
                        Expanded(
                          child: Text(
                            'New activities found',
                            style: Theme.of(context).textTheme.titleLarge,
                          ),
                        ),
                        IconButton(
                          onPressed: () => Navigator.of(context).pop(),
                          icon: const Icon(Icons.close),
                        ),
                      ],
                    ),
                  ),

                  // Tab bar (both sources) or subtitle (single source)
                  if (hasBoth)
                    TabBar(
                      tabs: [
                        Tab(text: 'Strava (${notifier.stravaActivities.length})'),
                        Tab(text: 'Polarsteps (${notifier.psSteps.length})'),
                      ],
                    )
                  else
                    Padding(
                      padding: const EdgeInsets.fromLTRB(20, 4, 20, 4),
                      child: Align(
                        alignment: Alignment.centerLeft,
                        child: Text(
                          hasStrava
                              ? '${notifier.stravaActivities.length} new Strava '
                                '${notifier.stravaActivities.length == 1 ? 'activity' : 'activities'}'
                              : '${notifier.psSteps.length} new Polarsteps '
                                '${notifier.psSteps.length == 1 ? 'step' : 'steps'}',
                          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                                color: Theme.of(context)
                                    .colorScheme
                                    .onSurface
                                    .withValues(alpha: 0.6),
                              ),
                        ),
                      ),
                    ),

                  const Divider(height: 1),

                  SizedBox(height: 360, child: listContent),

                  const Divider(height: 1),

                  _BottomBar(notifier: notifier, onImport: _import),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}

// ── Strava tab ─────────────────────────────────────────────────────────────────

class _StravaList extends StatelessWidget {
  final SyncImportNotifier notifier;

  const _StravaList({required this.notifier});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final activities = notifier.stravaActivities;

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
          child: Row(
            children: [
              Text(
                '${notifier.selectedStravaIds.length} / ${activities.length} selected',
                style: theme.textTheme.bodySmall,
              ),
              const Spacer(),
              TextButton(
                onPressed: notifier.selectAllStrava,
                child: const Text('Select all'),
              ),
              TextButton(
                onPressed: notifier.clearStrava,
                child: const Text('Clear'),
              ),
            ],
          ),
        ),
        Expanded(
          child: ListView.builder(
            itemCount: activities.length,
            itemBuilder: (context, i) {
              final a = activities[i];
              final id = a['id'];
              final name = a['name'] as String? ?? '';
              final type = a['type'] as String? ?? '';
              final distRaw = a['distance'] as num?;
              final dist = distRaw != null
                  ? '${(distRaw / 1000).toStringAsFixed(1)} km'
                  : '';
              final dateStr =
                  (a['start_date_local'] as String? ?? '').split('T').first;
              final selected = notifier.selectedStravaIds.contains(id);
              return CheckboxListTile(
                value: selected,
                onChanged: (_) => notifier.toggleStrava(id),
                title: Text(name),
                subtitle: Text(
                  [type, dist, dateStr].where((s) => s.isNotEmpty).join('  ·  '),
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}

// ── Polarsteps tab ─────────────────────────────────────────────────────────────

class _PsList extends StatelessWidget {
  final SyncImportNotifier notifier;

  const _PsList({required this.notifier});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final steps = notifier.psSteps;

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
          child: Row(
            children: [
              Text(
                '${notifier.selectedPsIds.length} / ${steps.length} selected',
                style: theme.textTheme.bodySmall,
              ),
              const Spacer(),
              TextButton(
                onPressed: notifier.selectAllPs,
                child: const Text('Select all'),
              ),
              TextButton(
                onPressed: notifier.clearPs,
                child: const Text('Clear'),
              ),
            ],
          ),
        ),
        Expanded(
          child: ListView.builder(
            itemCount: steps.length,
            itemBuilder: (context, i) {
              final s = steps[i];
              final id = s['id'] as int?;
              if (id == null) return const SizedBox.shrink();
              final name = s['name'] as String?;
              final date = s['date'] as String? ?? '';
              final desc = s['description'] as String?;
              final photoCount = (s['photos'] as List?)?.length ?? 0;
              final selected = notifier.selectedPsIds.contains(id);

              final title =
                  (name?.isNotEmpty == true) ? name! : (date.isNotEmpty ? date : 'Step ${i + 1}');
              final parts = <String>[];
              if (name?.isNotEmpty == true && date.isNotEmpty) parts.add(date);
              if (desc != null && desc.isNotEmpty) {
                parts.add(desc.length > 60 ? '${desc.substring(0, 60)}…' : desc);
              }
              if (photoCount > 0) {
                parts.add('$photoCount photo${photoCount == 1 ? '' : 's'}');
              }

              return CheckboxListTile(
                value: selected,
                onChanged: (_) => notifier.togglePs(id),
                title: Text(title),
                subtitle: parts.isNotEmpty ? Text(parts.join('  ·  ')) : null,
              );
            },
          ),
        ),
      ],
    );
  }
}

// ── Bottom bar ─────────────────────────────────────────────────────────────────

class _BottomBar extends StatelessWidget {
  final SyncImportNotifier notifier;
  final VoidCallback onImport;

  const _BottomBar({required this.notifier, required this.onImport});

  @override
  Widget build(BuildContext context) {
    final count = notifier.selectedCount;
    final isImporting = notifier.isImporting;

    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 16),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (isImporting) ...[
            LinearProgressIndicator(
              value: notifier.importTotal > 0
                  ? notifier.importedCount / notifier.importTotal
                  : null,
            ),
            const SizedBox(height: 6),
            Text(
              'Importing ${notifier.importedCount} / ${notifier.importTotal}…',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 8),
          ],
          if (notifier.error != null) ...[
            Text(
              notifier.error!,
              style: TextStyle(
                  color: Theme.of(context).colorScheme.error, fontSize: 12),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 8),
          ],
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: (count == 0 || isImporting) ? null : onImport,
              child: isImporting
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: Colors.white),
                    )
                  : Text('Import $count ${count == 1 ? 'item' : 'items'}'),
            ),
          ),
        ],
      ),
    );
  }
}
