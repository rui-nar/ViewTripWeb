import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import 'polarsteps_import_notifier.dart';
import 'project_notifier.dart';

class PolarstepsImportScreen extends StatefulWidget {
  final String projectName;

  const PolarstepsImportScreen({super.key, required this.projectName});

  @override
  State<PolarstepsImportScreen> createState() =>
      _PolarstepsImportScreenState();
}

class _PolarstepsImportScreenState
    extends State<PolarstepsImportScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final n = context.read<PolarstepsImportNotifier>();
      n.projectName = widget.projectName;
      n.loadTrips();
    });
  }

  Future<void> _import() async {
    final notifier = context.read<PolarstepsImportNotifier>();
    final added = await notifier.importSelected(widget.projectName);
    if (!mounted) return;
    if (added > 0) {
      // Reload the project so the newly-added memories appear immediately
      // in the activity panel and on the map when we pop back to AppScreen.
      final projectNotifier = context.read<ProjectNotifier>();
      projectNotifier.load(widget.projectName);
      projectNotifier.startPhotoPolling(widget.projectName);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('$added ${added == 1 ? 'memory' : 'memories'} added')),
      );
      context.pop();
    } else if (notifier.error == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('No steps were imported')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<PolarstepsImportNotifier>(
      builder: (context, notifier, _) {
        return Scaffold(
          appBar: AppBar(
            leading: BackButton(onPressed: () => context.pop()),
            title: Text(
              notifier.selectedTrip != null
                  ? notifier.selectedTrip!['name'] as String? ?? 'Steps'
                  : 'Import from Polarsteps',
            ),
            actions: [
              if (notifier.selectedTrip != null)
                TextButton(
                  onPressed: notifier.isImporting ? null : notifier.clearTrip,
                  child: const Text('Change trip'),
                ),
            ],
          ),
          body: _buildBody(context, notifier),
          bottomNavigationBar: notifier.selectedTrip != null
              ? _buildBottomBar(context, notifier)
              : null,
        );
      },
    );
  }

  Widget _buildBody(
      BuildContext context, PolarstepsImportNotifier notifier) {
    if (notifier.tokenExpired) {
      return _ReconnectPanel(notifier: notifier);
    }

    if (notifier.polarstepsNotConnected) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.link_off, size: 48),
              const SizedBox(height: 16),
              const Text(
                'Polarsteps not connected',
                style: TextStyle(fontSize: 18),
              ),
              const SizedBox(height: 8),
              const Text(
                'Go to Settings to paste your Polarsteps token.',
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 16),
              OutlinedButton(
                onPressed: () => context.push('/settings'),
                child: const Text('Open Settings'),
              ),
            ],
          ),
        ),
      );
    }

    if (notifier.isLoadingTrips) {
      return const Center(child: CircularProgressIndicator());
    }

    if (notifier.error != null && notifier.selectedTrip == null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(notifier.error!),
        ),
      );
    }

    // Phase 1: pick a trip
    if (notifier.selectedTrip == null) {
      return _TripList(notifier: notifier);
    }

    // Phase 2: step list
    return _StepList(notifier: notifier);
  }

  Widget _buildBottomBar(
      BuildContext context, PolarstepsImportNotifier notifier) {
    final count = notifier.selectedStepIds.length;
    final isImporting = notifier.isImporting;

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
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
                onPressed: (count == 0 || isImporting) ? null : _import,
                child: isImporting
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: Colors.white),
                      )
                    : Text('Import $count ${count == 1 ? 'step' : 'steps'}'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ── Reconnect panel (token expired) ─────────────────────────────────────────────

class _ReconnectPanel extends StatefulWidget {
  final PolarstepsImportNotifier notifier;

  const _ReconnectPanel({required this.notifier});

  @override
  State<_ReconnectPanel> createState() => _ReconnectPanelState();
}

class _ReconnectPanelState extends State<_ReconnectPanel> {
  final _tokenCtrl = TextEditingController();

  @override
  void dispose() {
    _tokenCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    await widget.notifier.reconnect(_tokenCtrl.text);
    // On success the notifier clears tokenExpired and resumes; this panel is
    // then replaced by the trip/step list. On failure it stays with an error.
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final n = widget.notifier;
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(32),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Icon(Icons.lock_clock_outlined,
                  size: 48, color: theme.colorScheme.primary),
              const SizedBox(height: 16),
              Text(
                'Your Polarsteps session expired',
                textAlign: TextAlign.center,
                style: theme.textTheme.titleMedium,
              ),
              const SizedBox(height: 8),
              Text(
                'Paste a fresh remember_token to reconnect — your selection is kept '
                'and the import continues right where it left off.',
                textAlign: TextAlign.center,
                style: theme.textTheme.bodySmall,
              ),
              const SizedBox(height: 8),
              Text(
                'In your browser: DevTools → Application → Cookies → polarsteps.com → '
                'copy the remember_token value.',
                textAlign: TextAlign.center,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _tokenCtrl,
                obscureText: true,
                enabled: !n.reconnecting,
                onSubmitted: (_) => n.reconnecting ? null : _submit(),
                decoration: const InputDecoration(
                  labelText: 'remember_token',
                  hintText: 'Paste cookie value here…',
                  border: OutlineInputBorder(),
                  isDense: true,
                ),
              ),
              if (n.error != null) ...[
                const SizedBox(height: 8),
                Text(
                  n.error!,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                      color: theme.colorScheme.error, fontSize: 12),
                ),
              ],
              const SizedBox(height: 16),
              FilledButton(
                onPressed: n.reconnecting ? null : _submit,
                child: n.reconnecting
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: Colors.white),
                      )
                    : const Text('Reconnect & resume'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ── Trip list (phase 1) ────────────────────────────────────────────────────────

class _TripList extends StatelessWidget {
  final PolarstepsImportNotifier notifier;

  const _TripList({required this.notifier});

  @override
  Widget build(BuildContext context) {
    if (notifier.trips.isEmpty) {
      return const Center(child: Text('No trips found'));
    }
    return ListView.separated(
      padding: const EdgeInsets.symmetric(vertical: 8),
      itemCount: notifier.trips.length,
      separatorBuilder: (_, __) => const Divider(height: 1),
      itemBuilder: (context, i) {
        final trip = notifier.trips[i];
        final name = trip['name'] as String? ?? 'Trip ${i + 1}';
        final start = trip['start_date'] as String?;
        final end = trip['end_date'] as String?;
        final count = (trip['steps_count'] as int?) ?? 0;

        String subtitle = '';
        if (start != null) subtitle = start;
        if (end != null && end != start) subtitle += ' – $end';
        if (count > 0) {
          subtitle +=
              subtitle.isNotEmpty ? '  ·  $count steps' : '$count steps';
        }

        return ListTile(
          title: Text(name),
          subtitle: subtitle.isNotEmpty ? Text(subtitle) : null,
          trailing: const Icon(Icons.chevron_right),
          onTap: () => notifier.selectTrip(trip),
        );
      },
    );
  }
}

// ── Step list (phase 2) ────────────────────────────────────────────────────────

class _StepList extends StatelessWidget {
  final PolarstepsImportNotifier notifier;

  const _StepList({required this.notifier});

  @override
  Widget build(BuildContext context) {
    if (notifier.isLoadingSteps) {
      return const Center(child: CircularProgressIndicator());
    }

    if (notifier.steps.isEmpty) {
      return const Center(child: Text('No published steps found'));
    }

    final allSelected =
        notifier.selectedStepIds.length == notifier.steps.length;

    return Column(
      children: [
        // Select all / clear bar
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
          child: Row(
            children: [
              Text(
                '${notifier.steps.length} steps',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              const Spacer(),
              TextButton(
                onPressed: allSelected
                    ? notifier.clearSelection
                    : notifier.selectAll,
                child: Text(allSelected ? 'Clear' : 'Select all'),
              ),
            ],
          ),
        ),
        const Divider(height: 1),
        Expanded(
          child: ListView.separated(
            itemCount: notifier.steps.length,
            separatorBuilder: (_, __) => const Divider(height: 1),
            itemBuilder: (context, i) {
              final ri = notifier.steps.length - 1 - i;
              final step = notifier.steps[ri];
              final id = step['id'] as int?;
              final name =
                  (step['name'] as String?)?.isNotEmpty == true
                      ? step['name'] as String
                      : 'Step ${ri + 1}';
              final date = step['date'] as String?;
              final locationName = step['location_name'] as String?;
              final photos =
                  (step['photos'] as List?)?.cast<Map<String, dynamic>>() ??
                      [];
              final thumbUrl = photos.isNotEmpty
                  ? photos.first['thumb_url'] as String?
                  : null;
              final alreadyImported =
                  id != null && notifier.alreadyImportedIds.contains(id);
              final selected =
                  !alreadyImported && id != null && notifier.selectedStepIds.contains(id);

              return CheckboxListTile(
                value: alreadyImported ? false : selected,
                onChanged: alreadyImported || id == null || notifier.isImporting
                    ? null
                    : (_) => notifier.toggleStep(id),
                title: Text(name, maxLines: 1, overflow: TextOverflow.ellipsis),
                subtitle: alreadyImported
                    ? Text(
                        'Already imported',
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.outline,
                          fontSize: 12,
                        ),
                      )
                    : Text(
                        [
                          if (date != null) date,
                          if (locationName != null) locationName,
                          if (photos.isNotEmpty)
                            '${photos.length} photo${photos.length > 1 ? 's' : ''}',
                        ].join('  ·  '),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                secondary: thumbUrl != null
                    ? ClipRRect(
                        borderRadius: BorderRadius.circular(4),
                        child: Image.network(
                          thumbUrl,
                          width: 48,
                          height: 48,
                          fit: BoxFit.cover,
                          errorBuilder: (_, __, ___) =>
                              const SizedBox(width: 48, height: 48),
                        ),
                      )
                    : null,
              );
            },
          ),
        ),
      ],
    );
  }
}
