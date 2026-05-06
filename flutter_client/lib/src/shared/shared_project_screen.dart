/// Read-only project view for users accessing a shared link (no auth required).
library;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:provider/provider.dart';

import '../api/client.dart';
import '../projects/basemaps.dart';
import '../projects/elevation_chart.dart';
import '../projects/map_panel.dart';
import '../projects/project_notifier.dart';
import '../projects/project_service.dart';

// ── Shared service — calls /api/share/{token} with no auth ───────────────────

class _SharedProjectService extends ProjectService {
  final String token;
  _SharedProjectService(this.token);

  @override
  Future<Map<String, dynamic>> getDetails(String _) async {
    final data = await api.get('/api/share/$token');
    return data as Map<String, dynamic>;
  }

  @override
  Future<Map<String, dynamic>> getGeo(String _) async {
    final data = await api.get('/api/share/$token/geo');
    return data as Map<String, dynamic>;
  }
}

// ── Shared notifier — extends ProjectNotifier so existing widgets reuse it ───

class SharedProjectNotifier extends ProjectNotifier {
  final String token;

  SharedProjectNotifier(this.token)
      : super(_SharedProjectService(token));

  /// Load the shared project. Passes token as name (service ignores the arg).
  Future<void> loadShared() => load(token);
}

// ── Screen ────────────────────────────────────────────────────────────────────

class SharedProjectScreen extends StatelessWidget {
  final String token;
  const SharedProjectScreen({super.key, required this.token});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      create: (_) => SharedProjectNotifier(token)..loadShared(),
      child: _SharedProjectView(token: token),
    );
  }
}

class _SharedProjectView extends StatefulWidget {
  final String token;
  const _SharedProjectView({required this.token});

  @override
  State<_SharedProjectView> createState() => _SharedProjectViewState();
}

class _SharedProjectViewState extends State<_SharedProjectView> {
  final MapController _mapController = MapController();

  @override
  void dispose() {
    _mapController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final notifier = context.watch<SharedProjectNotifier>();
    // Present the notifier as ProjectNotifier so MapPanel / ElevationChart work.
    final pn = notifier as ProjectNotifier;
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: Text(
          notifier.projectName?.isNotEmpty == true
              ? notifier.projectName!
              : 'Shared project',
        ),
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(28),
          child: Container(
            color: theme.colorScheme.secondaryContainer,
            width: double.infinity,
            padding:
                const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
            child: Row(
              children: [
                Icon(Icons.lock_outlined,
                    size: 14,
                    color: theme.colorScheme.onSecondaryContainer),
                const SizedBox(width: 6),
                Text(
                  'View only — you are viewing a shared project',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSecondaryContainer,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
      body: notifier.isLoading
          ? const Center(child: CircularProgressIndicator())
          : notifier.error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(
                      notifier.error!,
                      style: TextStyle(color: theme.colorScheme.error),
                      textAlign: TextAlign.center,
                    ),
                  ),
                )
              : LayoutBuilder(
                  builder: (context, constraints) {
                    final wide = constraints.maxWidth >= 720;
                    final mapPanel = MapPanel(
                      notifier: pn,
                      mapController: _mapController,
                      basemapUrl: kActiveViewBasemapUrl,
                      labelsUrl: kActiveViewLabelsUrl,
                      basemapStyleUri: kActiveViewStyleUri,
                    );
                    final activityList = _ReadOnlyActivityList(notifier: pn);
                    final selectedId = notifier.selectedActivityId;
                    final elevChart = ElevationChart(
                      activities: notifier.activities,
                      selectedActivityId: selectedId,
                      track: selectedId == null
                          ? notifier.fullTrack
                          : notifier.perActivityTracks[selectedId.toString()] ?? notifier.fullTrack,
                      onCursorChanged: (pos) =>
                          notifier.elevationCursorNotifier.value = pos,
                      mapCursorNotifier: notifier.mapCursorDistNotifier,
                    );

                    if (wide) {
                      return Row(
                        children: [
                          SizedBox(width: 260, child: activityList),
                          Expanded(
                            child: Column(
                              children: [
                                Expanded(child: mapPanel),
                                elevChart,
                              ],
                            ),
                          ),
                        ],
                      );
                    } else {
                      return Column(
                        children: [
                          Expanded(child: mapPanel),
                          SizedBox(
                            height: constraints.maxHeight * 0.4,
                            child: Column(
                              children: [
                                Expanded(child: activityList),
                                elevChart,
                              ],
                            ),
                          ),
                        ],
                      );
                    }
                  },
                ),
    );
  }
}

// ── Read-only activity list ───────────────────────────────────────────────────

class _ReadOnlyActivityList extends StatelessWidget {
  final ProjectNotifier notifier;
  const _ReadOnlyActivityList({required this.notifier});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final activities = notifier.activities;

    if (activities.isEmpty) {
      return Center(
        child: Text('No activities', style: theme.textTheme.bodySmall),
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.symmetric(vertical: 8),
      itemCount: activities.length,
      itemBuilder: (context, i) {
        final act = activities[i];
        final id = act['id'];
        final name = act['name'] as String? ?? 'Activity';
        final type = act['type'] as String? ?? '';
        final distM = (act['distance'] as num? ?? 0).toDouble();
        final distKm = (distM / 1000).toStringAsFixed(1);
        final isSelected =
            notifier.selectedActivityId?.toString() == id?.toString();

        return ListTile(
          dense: true,
          selected: isSelected,
          selectedTileColor:
              theme.colorScheme.primaryContainer.withValues(alpha: 0.4),
          leading: Icon(
            _sportIcon(type),
            size: 18,
            color: isSelected ? theme.colorScheme.primary : null,
          ),
          title: Text(name,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: theme.textTheme.bodyMedium),
          subtitle: Text('$distKm km',
              style: theme.textTheme.bodySmall),
          onTap: () => notifier.selectActivity(id),
        );
      },
    );
  }

  IconData _sportIcon(String type) {
    return switch (type.toLowerCase()) {
      'ride' || 'virtualride' || 'ebikeride' => Icons.directions_bike,
      'run' || 'virtualrun' => Icons.directions_run,
      'hike' || 'walk' => Icons.hiking,
      'swim' => Icons.pool,
      'alpineski' || 'nordicski' || 'snowboard' => Icons.downhill_skiing,
      _ => Icons.route,
    };
  }
}
