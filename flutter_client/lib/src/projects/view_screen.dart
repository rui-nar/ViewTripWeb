/// View-mode project screen — map + elevation chart, no editing controls.
///
/// Accessible to authenticated project owners via `/view?project=name`.
/// Shows the same map as manage mode but without the activity panel,
/// and with the Esri World Imagery (satellite) basemap.
library;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../api/client.dart' show api;
import 'activity_panel.dart';
import 'basemaps.dart';
import 'elevation_chart.dart';
import 'map_panel.dart';
import 'project_notifier.dart';
import 'project_service.dart';
import 'sync_import_dialog.dart';
import 'sync_import_notifier.dart';

// ── Service — calls /api/projects/{name}/meta first, full details in background

class _ViewProjectService extends ProjectService {
  final String projectName;

  /// Resolves with the full ~3 MB response (elevation_profile included).
  /// Assigned by getDetails(); awaited by ViewProjectNotifier.loadView().
  late Future<Map<String, dynamic>> fullDetailsFuture;

  _ViewProjectService(this.projectName);

  /// Fires GET /meta and GET / in parallel.  Returns meta quickly so
  /// ProjectNotifier.load() can render the UI; stores the full-details
  /// future for ViewProjectNotifier.loadView() to await for phase 2.
  @override
  Future<Map<String, dynamic>> getDetails(String name) async {
    fullDetailsFuture = api.get('/api/projects/$name').then(
      (data) => data as Map<String, dynamic>,
    );
    return await api.get('/api/projects/$name/meta') as Map<String, dynamic>;
  }
}

// ── Notifier — progressive two-phase load ────────────────────────────────────

class ViewProjectNotifier extends ProjectNotifier {
  final _ViewProjectService _viewSvc;
  bool _disposed = false;

  ViewProjectNotifier._internal(_ViewProjectService svc)
      : _viewSvc = svc,
        super(svc);

  factory ViewProjectNotifier(String projectName) {
    final svc = _ViewProjectService(projectName);
    return ViewProjectNotifier._internal(svc);
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }

  Future<void> loadView(String projectName) async {
    isMetaLoaded = false;
    isElevationLoaded = false;

    // Phase 1: load() calls _viewSvc.getDetails() which returns the
    // lightweight /meta response in ~1 s.  isLoading goes false after that.
    await load(projectName);
    if (_disposed) return;
    isMetaLoaded = true;
    notifyListeners(); // project name, map, activity panel visible

    // Phase 2 (background): await the full ~3 MB response for elevation data.
    try {
      final fullDetails = await _viewSvc.fullDetailsFuture;
      if (_disposed || currentLoadKey != projectName) return;
      final rawActs = fullDetails['activities'];
      if (rawActs is List) {
        applyFullActivities(rawActs.cast<Map<String, dynamic>>());
      }
      isElevationLoaded = true;
      notifyListeners(); // elevation chart renders
    } catch (_) {
      // Non-fatal — elevation placeholder stays visible
    }
  }
}

// ── Entry point ───────────────────────────────────────────────────────────────

class ViewScreen extends StatelessWidget {
  final String projectName;
  const ViewScreen({super.key, required this.projectName});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      create: (_) => ViewProjectNotifier(projectName),
      child: _ViewBody(projectName: projectName),
    );
  }
}

// ── Screen body ───────────────────────────────────────────────────────────────

class _ViewBody extends StatefulWidget {
  final String projectName;
  const _ViewBody({required this.projectName});

  @override
  State<_ViewBody> createState() => _ViewBodyState();
}

class _ViewBodyState extends State<_ViewBody> {
  final MapController _mapController = MapController();
  bool _autoZoom = false;

  void _openSyncDialog(BuildContext context) {
    final notifier = context.read<ViewProjectNotifier>();
    final pending = notifier.pendingSync;
    if (pending == null) return;
    showDialog<void>(
      context: context,
      useRootNavigator: true,
      builder: (_) => ChangeNotifierProvider(
        create: (_) => SyncImportNotifier(
          stravaActivities: pending.strava,
          psSteps: pending.polarsteps,
        ),
        child: SyncImportDialog(projectName: widget.projectName),
      ),
    ).then((_) {
      if (!mounted) return;
      notifier.markSynced();
      notifier.loadView(widget.projectName);
    });
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<ViewProjectNotifier>().loadView(widget.projectName);
    });
  }

  @override
  void dispose() {
    _mapController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final title = context.select<ViewProjectNotifier, String>(
      (n) => n.projectName ?? widget.projectName,
    );
    final isLoading = context.select<ViewProjectNotifier, bool>((n) => n.isLoading);

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/projects'),
        ),
        title: Text(
          title.isEmpty ? 'ViewTripWeb' : title,
          overflow: TextOverflow.ellipsis,
        ),
        actions: [
          // Mode toggle — manage / view (active)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 4),
            child: SegmentedButton<bool>(
              segments: const [
                ButtonSegment(
                  value: false,
                  icon: Icon(Icons.edit_outlined),
                  tooltip: 'Manage mode',
                ),
                ButtonSegment(
                  value: true,
                  icon: Icon(Icons.visibility_outlined),
                  tooltip: 'View mode',
                ),
              ],
              selected: const {true},
              onSelectionChanged: (s) => context.go(
                  '/app?project=${Uri.encodeComponent(widget.projectName)}'),
              style: const ButtonStyle(
                  visualDensity: VisualDensity.compact,
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap),
            ),
          ),
          Consumer<ViewProjectNotifier>(
            builder: (_, n, __) {
              final active = n.tagFilter.isNotEmpty;
              return IconButton(
                icon: Badge(
                  isLabelVisible: active,
                  label: Text('${n.tagFilter.length}'),
                  child: Icon(
                    Icons.label_outline,
                    color: active ? Theme.of(context).colorScheme.primary : null,
                  ),
                ),
                tooltip: 'Filter by tag',
                onPressed: n.availableTags.isEmpty
                    ? null
                    : () => showModalBottomSheet<void>(
                          context: context,
                          useRootNavigator: true,
                          builder: (_) => TagFilterSheet(
                              notifier: n, readOnly: true),
                        ),
              );
            },
          ),
          IconButton(
            icon: Icon(
              Icons.fit_screen,
              color: _autoZoom ? Theme.of(context).colorScheme.primary : null,
            ),
            tooltip: _autoZoom ? 'Auto-zoom on (tap to disable)' : 'Auto-zoom to selection',
            onPressed: () => setState(() => _autoZoom = !_autoZoom),
          ),
          IconButton(
            icon: const Icon(Icons.bar_chart_outlined),
            tooltip: 'Statistics',
            onPressed: isLoading ? null : () => context.push(
              '/stats?project=${Uri.encodeComponent(widget.projectName)}',
              extra: {
                'tags': context.read<ViewProjectNotifier>().availableTags,
                'groups': context.read<ViewProjectNotifier>().sleepingOptionGroups,
              },
            ),
          ),
          IconButton(
            icon: const Icon(Icons.settings_outlined),
            tooltip: 'Settings',
            onPressed: () => context.push('/settings'),
          ),
          IconButton(
            icon: const Icon(Icons.arrow_back),
            tooltip: 'Back to projects',
            onPressed: () => context.go('/projects'),
          ),
          const SizedBox(width: 4),
        ],
      ),
      body: Column(
        children: [
          // ── Auto-sync banner ─────────────────────────────────────────────
          Selector<ViewProjectNotifier, bool>(
            selector: (_, n) => n.pendingSync != null,
            builder: (context, hasSync, __) {
              if (!hasSync) return const SizedBox.shrink();
              final n = context.read<ViewProjectNotifier>();
              final strava = n.pendingSync!.strava.length;
              final ps = n.pendingSync!.polarsteps.length;
              final parts = [
                if (strava > 0) '$strava Strava ${strava == 1 ? 'activity' : 'activities'}',
                if (ps > 0) '$ps Polarsteps ${ps == 1 ? 'step' : 'steps'}',
              ];
              return MaterialBanner(
                padding: const EdgeInsets.fromLTRB(16, 8, 8, 8),
                content: Text('New: ${parts.join(' and ')}'),
                leading: const Icon(Icons.sync, size: 20),
                actions: [
                  TextButton(
                    onPressed: () => context.read<ViewProjectNotifier>().markSynced(),
                    child: const Text('Later'),
                  ),
                  TextButton(
                    onPressed: () => _openSyncDialog(context),
                    child: const Text('Import'),
                  ),
                ],
              );
            },
          ),
          Expanded(
            child: Consumer<ViewProjectNotifier>(
              builder: (context, notifier, _) {
                if (!notifier.isMetaLoaded && notifier.geo == null) {
                  if (notifier.error != null) {
                    return Center(
                      child: Padding(
                        padding: const EdgeInsets.all(24),
                        child: Text(
                          notifier.error!,
                          style: TextStyle(
                              color: Theme.of(context).colorScheme.error),
                          textAlign: TextAlign.center,
                        ),
                      ),
                    );
                  }
                  return const Center(child: CircularProgressIndicator());
                }
                return _ViewLayout(
                  notifier: notifier,
                  mapController: _mapController,
                  autoZoom: _autoZoom,
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

// ── Layout: map + elevation chart ─────────────────────────────────────────────

class _ViewLayout extends StatelessWidget {
  final ViewProjectNotifier notifier;
  final MapController mapController;
  final bool autoZoom;

  const _ViewLayout({
    required this.notifier,
    required this.mapController,
    required this.autoZoom,
  });

  @override
  Widget build(BuildContext context) {
    final selActId = notifier.selectedActivityId;
    final elevChart = notifier.isElevationLoaded
        ? ElevationChart(
            activities: notifier.activities,
            selectedActivityId: selActId,
            onCursorChanged: (pos) =>
                notifier.elevationCursorNotifier.value = pos,
            mapCursorNotifier: notifier.mapCursorDistNotifier,
            track: selActId != null
                ? notifier.perActivityTracks[selActId.toString()] ??
                    notifier.fullTrack
                : notifier.fullTrack,
          )
        : const ElevationLoadingPlaceholder();

    final mapPanel = MapPanel(
      notifier: notifier,
      mapController: mapController,
      basemapUrl: kActiveViewBasemapUrl,
      labelsUrl: kActiveViewLabelsOverlayUrl,
      basemapStyleUri: kActiveViewStyleUri,
    );

    return Column(
      children: [
        Expanded(child: mapPanel),
        elevChart,
      ],
    );
  }
}
