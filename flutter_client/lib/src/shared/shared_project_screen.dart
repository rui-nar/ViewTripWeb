/// Read-only project view for users accessing a shared link (no auth required).
library;

import 'package:flutter/material.dart';
import 'package:flutter_map_animations/flutter_map_animations.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../api/client.dart' show api;
import '../auth/auth_notifier.dart';
import '../projects/basemaps.dart';
import '../projects/elevation_chart.dart' show ElevationChart, ElevationLoadingPlaceholder;
import '../projects/map_panel.dart';
import '../projects/memory_detail_modal.dart';
import '../projects/project_notifier.dart';
import '../projects/project_service.dart';
import '../projects/project_stats_screen.dart';
import 'anonymous_id.dart';

// ── Shared service — calls /api/share/{token}, appends ?aid= when provided ───

class _SharedProjectService extends ProjectService {
  final String token;
  final String? anonymousId;
  String ownerName = '';

  _SharedProjectService(this.token, {this.anonymousId});

  String get _aidParam =>
      anonymousId != null ? '?aid=${Uri.encodeComponent(anonymousId!)}' : '';

  /// Returns the lightweight /meta response (~363 KB) so load() can render
  /// the UI quickly.  Full details are fetched separately via fetchFullDetails()
  /// after load() returns, giving meta exclusive NAS uplink bandwidth.
  @override
  Future<Map<String, dynamic>> getDetails(String _) async {
    final meta =
        await api.get('/api/share/$token/meta$_aidParam') as Map<String, dynamic>;
    ownerName = (meta['owner_name'] as String?) ?? '';
    return meta;
  }

  /// Fetches the full ~3 MB response (elevation_profile included).
  /// Called by SharedProjectNotifier.loadShared() after load() has returned,
  /// so meta gets exclusive bandwidth before this request fires.
  Future<Map<String, dynamic>> fetchFullDetails() async {
    final data = await api.get('/api/share/$token$_aidParam');
    final m = data as Map<String, dynamic>;
    ownerName = (m['owner_name'] as String?) ?? '';
    return m;
  }

  @override
  Future<Map<String, dynamic>> getGeo(String _) async {
    final data = await api.get('/api/share/$token/geo$_aidParam');
    return data as Map<String, dynamic>;
  }

  @override
  Future<Map<String, dynamic>> getLowResGeo(String _) async {
    final data = await api.get('/api/share/$token/geo/low-res');
    return data as Map<String, dynamic>;
  }

  @override
  Future<Map<String, dynamic>> getStats(String _, {List<String> tags = const []}) async {
    final query = tags.isEmpty
        ? ''
        : '?${tags.map((t) => 'tags=${Uri.encodeComponent(t)}').join('&')}';
    final data = await api.get('/api/share/$token/stats$query');
    return data as Map<String, dynamic>;
  }
}

// ── Shared notifier ───────────────────────────────────────────────────────────

class SharedProjectNotifier extends ProjectNotifier {
  final String token;
  final _SharedProjectService _sharedSvc;
  String get ownerName => _sharedSvc.ownerName;
  @override
  ProjectService get service => _sharedSvc;
  bool _disposed = false;

  @override
  bool get loadOwnerExtras => false;

  @override
  String photoThumbUrl(String memId, String uuid) =>
      '$apiBaseUrl/api/share/$token/photos/$memId/$uuid/thumb';

  @override
  String photoFullUrl(String memId, String uuid) =>
      '$apiBaseUrl/api/share/$token/photos/$memId/$uuid';

  @override
  Map<String, String> get photoAuthHeaders => const {};

  SharedProjectNotifier._internal(this.token, _SharedProjectService svc)
      : _sharedSvc = svc,
        super(svc);

  factory SharedProjectNotifier(String token, {String? anonymousId}) {
    final svc = _SharedProjectService(token, anonymousId: anonymousId);
    return SharedProjectNotifier._internal(token, svc);
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }

  Future<void> loadShared() async {
    isMetaLoaded = false;
    isElevationLoaded = false;
    isGeoLoaded = false;

    // Phase 1: load() calls _sharedSvc.getDetails() which returns the
    // lightweight /meta response in ~1 s.  isLoading goes false after that.
    await load(token);
    if (_disposed) return;
    isMetaLoaded = true;
    // The /meta response now carries a downsampled (low-res) elevation profile,
    // so the chart can render immediately; Phase 2 below upgrades it in place.
    isElevationLoaded = true;
    notifyListeners(); // project name, activity list, memories, elevation chart visible

    // Phase 2 (background): fetch the full ~3 MB response for elevation data.
    // Fired here — after load() has returned — so meta had exclusive bandwidth.
    try {
      final fullDetails = await _sharedSvc.fetchFullDetails();
      if (_disposed || currentLoadKey != token) return;
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

// ── Screen ────────────────────────────────────────────────────────────────────

class SharedProjectScreen extends StatefulWidget {
  final String token;

  /// When set, the memory with this stable public_id is opened automatically
  /// once the project has loaded (deep link `/share/<token>?memory=<id>`).
  final String? initialMemoryPublicId;

  const SharedProjectScreen({
    super.key,
    required this.token,
    this.initialMemoryPublicId,
  });

  @override
  State<SharedProjectScreen> createState() => _SharedProjectScreenState();
}

class _SharedProjectScreenState extends State<SharedProjectScreen> {
  SharedProjectNotifier? _notifier;

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    final anonId = await getOrCreateAnonId();
    if (!mounted) return;
    final notifier = SharedProjectNotifier(widget.token, anonymousId: anonId)
      ..loadShared();
    setState(() => _notifier = notifier);
  }

  @override
  void dispose() {
    _notifier?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_notifier == null) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
    }
    return ChangeNotifierProvider.value(
      value: _notifier!,
      child: _SharedProjectView(
        token: widget.token,
        initialMemoryPublicId: widget.initialMemoryPublicId,
      ),
    );
  }
}

class _SharedProjectView extends StatefulWidget {
  final String token;
  final String? initialMemoryPublicId;
  const _SharedProjectView({required this.token, this.initialMemoryPublicId});

  @override
  State<_SharedProjectView> createState() => _SharedProjectViewState();
}

class _SharedProjectViewState extends State<_SharedProjectView>
    with TickerProviderStateMixin {
  late final AnimatedMapController _mapController =
      AnimatedMapController(vsync: this, duration: const Duration(milliseconds: 500));

  bool _deepLinkHandled = false;

  @override
  void dispose() {
    _mapController.dispose();
    super.dispose();
  }

  /// Opens the deep-linked memory once the project has loaded. Matches on the
  /// stable public_id; if not found (e.g. the memory was removed), it silently
  /// leaves the reader at the trip root.
  void _maybeOpenDeepLinkedMemory(ProjectNotifier pn) {
    if (_deepLinkHandled || widget.initialMemoryPublicId == null) return;
    if (!pn.isMetaLoaded) return;
    _deepLinkHandled = true;

    final match = pn.items.firstWhere(
      (i) =>
          i['item_type'] == 'memory' &&
          (i['memory'] as Map?)?['public_id'] == widget.initialMemoryPublicId,
      orElse: () => const <String, dynamic>{},
    );
    final mem = match['memory'];
    if (mem is! Map) return;

    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      showMemoryDetail(
        context,
        pn,
        mem.cast<String, dynamic>(),
        readOnly: true,
        shareToken: widget.token,
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    final notifier = context.watch<SharedProjectNotifier>();
    final pn = notifier as ProjectNotifier;
    _maybeOpenDeepLinkedMemory(pn);
    final theme = Theme.of(context);
    final authUser = context.watch<AuthNotifier>().user;
    final isAnonymous = authUser == null;

    return Scaffold(
      appBar: AppBar(
        title: Text(
          notifier.projectName?.isNotEmpty == true
              ? notifier.ownerName.isNotEmpty
                  ? '${notifier.projectName} — shared by ${notifier.ownerName}'
                  : notifier.projectName!
              : 'Shared project',
        ),
        actions: [
          if (notifier.isMetaLoaded)
            IconButton(
              icon: const Icon(Icons.bar_chart_outlined),
              tooltip: 'Statistics',
              onPressed: () => Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) => ProjectStatsScreen(
                    projectName: notifier.projectName ?? '',
                    availableTags: notifier.availableTags,
                    sleepingOptionGroups: notifier.sleepingOptionGroups,
                    service: notifier.service,
                  ),
                ),
              ),
            ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(28),
          child: Container(
            color: theme.colorScheme.secondaryContainer,
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
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
      body: Column(
        children: [
          if (isAnonymous) _AnonBanner(token: widget.token),
          Expanded(
            child: !notifier.isMetaLoaded
                ? (notifier.error != null
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
                    : const Center(child: CircularProgressIndicator()))
                : LayoutBuilder(
                    builder: (context, constraints) {
                      final wide = constraints.maxWidth >= 720;
                      final mapPanel = MapPanel(
                        notifier: pn,
                        mapController: _mapController,
                        basemapUrl: kActiveViewBasemapUrl,
                        labelsUrl: kActiveViewLabelsOverlayUrl,
                        basemapStyleUri: kActiveViewStyleUri,
                      );
                      final activityList = _ReadOnlyActivityList(notifier: pn);
                      final selectedId = notifier.selectedActivityId;
                      final elevChart = notifier.isElevationLoaded
                          ? ElevationChart(
                              activities: notifier.activities,
                              selectedActivityId: selectedId,
                              track: selectedId == null
                                  ? notifier.fullTrack
                                  : notifier.perActivityTracks[
                                          selectedId.toString()] ??
                                      notifier.fullTrack,
                              onCursorChanged: (pos) =>
                                  notifier.elevationCursorNotifier.value = pos,
                              mapCursorNotifier: notifier.mapCursorDistNotifier,
                              color: pn.effectiveElevationChartColor,
                            )
                          : const ElevationLoadingPlaceholder();

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
          ),
        ],
      ),
    );
  }
}

// ── Anonymous visitor banner ──────────────────────────────────────────────────

class _AnonBanner extends StatelessWidget {
  final String token;
  const _AnonBanner({required this.token});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Material(
      color: theme.colorScheme.tertiaryContainer,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        child: Row(
          children: [
            Icon(Icons.person_outline,
                size: 18, color: theme.colorScheme.onTertiaryContainer),
            const SizedBox(width: 10),
            Text(
              'Browsing as a guest — ',
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onTertiaryContainer,
              ),
            ),
            InkWell(
              onTap: () => context.go('/login?return_to=/share/$token'),
              child: Text(
                'login/register',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onTertiaryContainer,
                  decoration: TextDecoration.underline,
                ),
              ),
            ),
            Text(
              ' to enable the full experience',
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onTertiaryContainer,
              ),
            ),
          ],
        ),
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
          subtitle: Text('$distKm km', style: theme.textTheme.bodySmall),
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
