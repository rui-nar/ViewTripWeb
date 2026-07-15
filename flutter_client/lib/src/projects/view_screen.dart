/// View-mode project screen — map + elevation chart, no editing controls.
///
/// Accessible to authenticated project owners via `/view?project=name`.
/// Shows the same map as manage mode but without the activity panel,
/// and with the Esri World Imagery (satellite) basemap.
library;

import 'package:flutter/material.dart';
import 'package:flutter_map_animations/flutter_map_animations.dart';
import 'package:go_router/go_router.dart';
import 'package:latlong2/latlong.dart';
import 'package:provider/provider.dart';

import '../api/client.dart' show api;
import '../core/current_location.dart' show currentDeviceLatLng;
import 'activity_panel.dart';
import 'basemaps.dart';
import 'elevation_chart.dart';
import 'map_panel.dart';
import 'people_screen.dart';
import 'project_add_fab.dart';
import 'project_notifier.dart';
import 'project_service.dart';
import 'sync_import_dialog.dart';
import 'sync_import_notifier.dart';

// ── Service — calls /api/projects/{name}/meta first, full details in background

class _ViewProjectService extends ProjectService {
  final String projectName;

  _ViewProjectService(this.projectName);

  /// Returns the lightweight /meta response so load() can render the UI quickly.
  /// Full details are fetched separately via fetchFullDetails() after load()
  /// returns, giving meta exclusive NAS uplink bandwidth.
  @override
  Future<Map<String, dynamic>> getDetails(String name) async {
    final meta = await api.get('/api/projects/$name/meta') as Map<String, dynamic>;
    return meta;
  }

  /// Fetches the full ~3 MB response (elevation_profile included).
  /// Called by ViewProjectNotifier.loadView() after load() has returned.
  Future<Map<String, dynamic>> fetchFullDetails(String name) async {
    final data = await api.get('/api/projects/$name');
    return data as Map<String, dynamic>;
  }
}

// ── Notifier — progressive two-phase load ────────────────────────────────────

class ViewProjectNotifier extends ProjectNotifier {
  final _ViewProjectService _viewSvc;
  bool _disposed = false;

  ViewProjectNotifier._internal(_ViewProjectService super.svc)
      : _viewSvc = svc;

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
    isGeoLoaded = false;

    // Phase 1: load() calls _viewSvc.getDetails() which returns the
    // lightweight /meta response in ~1 s.  isLoading goes false after that.
    await load(projectName);
    if (_disposed) return;
    isMetaLoaded = true;
    // The /meta response now carries a downsampled (low-res) elevation profile,
    // so the chart can render immediately instead of waiting for the full
    // profile; Phase 2 below upgrades it in place.
    isElevationLoaded = true;
    notifyListeners(); // project name, map, activity panel + elevation chart visible

    // Phase 2 (background): fetch full ~3 MB response for elevation data.
    // Fired here — after load() has returned — so meta had exclusive bandwidth.
    try {
      final fullDetails = await _viewSvc.fetchFullDetails(projectName);
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

  /// Camera position carried over from edit mode via the mode toggle, so
  /// switching modes doesn't reset the map viewport to fit-all-bounds.
  final double? initialLat;
  final double? initialLng;
  final double? initialZoom;

  const ViewScreen({
    super.key,
    required this.projectName,
    this.initialLat,
    this.initialLng,
    this.initialZoom,
  });

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      create: (_) => ViewProjectNotifier(projectName),
      child: _ViewBody(
        projectName: projectName,
        initialLat: initialLat,
        initialLng: initialLng,
        initialZoom: initialZoom,
      ),
    );
  }
}

// ── Screen body ───────────────────────────────────────────────────────────────

class _ViewBody extends StatefulWidget {
  final String projectName;
  final double? initialLat;
  final double? initialLng;
  final double? initialZoom;
  const _ViewBody({
    required this.projectName,
    this.initialLat,
    this.initialLng,
    this.initialZoom,
  });

  @override
  State<_ViewBody> createState() => _ViewBodyState();
}

class _ViewBodyState extends State<_ViewBody> with TickerProviderStateMixin {
  late final AnimatedMapController _mapController =
      AnimatedMapController(vsync: this, duration: const Duration(milliseconds: 500));
  bool _autoZoom = false;

  // Highlighted point set when the user taps an encounter's place icon
  // (issue #72); cleared on the next unrelated map tap/selection.
  LatLng? _focusedLatLng;

  /// Zooms the map in on (lat, lon) and drops a highlighted pin there.
  void _focusLocation(double lat, double lon) {
    final target = LatLng(lat, lon);
    final currentZoom = _mapController.mapController.camera.zoom;
    setState(() => _focusedLatLng = target);
    _mapController.centerOnPoint(
      target,
      zoom: currentZoom < 15 ? 15 : currentZoom,
    );
  }

  void _clearFocusedLocation() {
    if (_focusedLatLng != null) setState(() => _focusedLatLng = null);
  }

  // Locate-me pin (issue #88); replaced (not accumulated) on each tap.
  LatLng? _hereLatLng;
  bool _locatingHere = false;

  /// Fetches the device's current location and pans the map to it at the
  /// CURRENT zoom (iso-zoom — unlike [_focusLocation], no zoom floor).
  /// Silent-fail on denied/unavailable/timed-out location, matching this
  /// app's established convention (see `current_location.dart`).
  Future<void> _locateMe() async {
    setState(() => _locatingHere = true);
    final here = await currentDeviceLatLng();
    if (!mounted) return;
    setState(() {
      _locatingHere = false;
      if (here != null) _hereLatLng = here;
    });
    if (here != null) {
      final currentZoom = _mapController.mapController.camera.zoom;
      _mapController.centerOnPoint(here, zoom: currentZoom);
    }
  }

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
      floatingActionButton:
          buildProjectAddFab(context, context.read<ViewProjectNotifier>()),
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
              onSelectionChanged: (s) {
                final cam = _mapController.mapController.camera;
                context.go(
                    '/app?project=${Uri.encodeComponent(widget.projectName)}'
                    '&lat=${cam.center.latitude}&lng=${cam.center.longitude}&zoom=${cam.zoom}');
              },
              style: const ButtonStyle(
                  visualDensity: VisualDensity.compact,
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap),
            ),
          ),

          // People directory (#40)
          IconButton(
            tooltip: 'Encounters',
            icon: const Icon(Icons.groups_outlined),
            onPressed: () async {
              final result = await Navigator.of(context).push(MaterialPageRoute(
                builder: (_) => PeopleScreen(
                    notifier: context.read<ViewProjectNotifier>()),
              ));
              if (!mounted) return;
              // A location tapped inside PeopleScreen (issue #72) — focus it
              // on this screen's map.
              if (result is Map) {
                final lat = (result['lat'] as num?)?.toDouble();
                final lon = (result['lon'] as num?)?.toDouble();
                if (lat != null && lon != null) _focusLocation(lat, lon);
              }
            },
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
                  initialLat: widget.initialLat,
                  initialLng: widget.initialLng,
                  initialZoom: widget.initialZoom,
                  focusedLatLng: _focusedLatLng,
                  onLocationTap: _focusLocation,
                  onClearFocusedLocation: _clearFocusedLocation,
                  hereLatLng: _hereLatLng,
                  locatingHere: _locatingHere,
                  onLocateMe: _locateMe,
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
  final AnimatedMapController mapController;
  final bool autoZoom;
  final double? initialLat;
  final double? initialLng;
  final double? initialZoom;
  final LatLng? focusedLatLng;
  final void Function(double lat, double lon)? onLocationTap;
  final VoidCallback? onClearFocusedLocation;
  final LatLng? hereLatLng;
  final bool locatingHere;
  final VoidCallback? onLocateMe;

  const _ViewLayout({
    required this.notifier,
    required this.mapController,
    required this.autoZoom,
    this.initialLat,
    this.initialLng,
    this.initialZoom,
    this.focusedLatLng,
    this.onLocationTap,
    this.onClearFocusedLocation,
    this.hereLatLng,
    this.locatingHere = false,
    this.onLocateMe,
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
            color: notifier.effectiveElevationChartColor,
          )
        : const ElevationLoadingPlaceholder();

    final mapPanel = MapPanel(
      notifier: notifier,
      mapController: mapController,
      basemapUrl: kActiveViewBasemapUrl,
      labelsUrl: kActiveViewLabelsOverlayUrl,
      basemapStyleUri: kActiveViewStyleUri,
      autoZoom: autoZoom,
      initialLat: initialLat,
      initialLng: initialLng,
      initialZoom: initialZoom,
      // Owner-only — this screen is authenticated, unlike shared_project_screen.dart
      // which reuses MapPanel for public/unauthenticated links (issue #71).
      showEncounters: true,
      focusedLatLng: focusedLatLng,
      onLocationTap: onLocationTap,
      onClearFocusedLocation: onClearFocusedLocation,
      // Owner-only, same reasoning as showEncounters above (issue #88) —
      // shared_project_screen.dart's public MapPanel never sets this.
      showLocateMe: true,
      hereLatLng: hereLatLng,
      locatingHere: locatingHere,
      onLocateMe: onLocateMe,
    );

    return Column(
      children: [
        Expanded(child: mapPanel),
        elevChart,
      ],
    );
  }
}
