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

import '../auth/auth_notifier.dart';
import 'app_screen.dart';
import 'basemaps.dart';
import 'project_notifier.dart';
import 'project_service.dart';

// ── Entry point ───────────────────────────────────────────────────────────────

class ViewScreen extends StatelessWidget {
  final String projectName;
  const ViewScreen({super.key, required this.projectName});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      create: (_) => ProjectNotifier(ProjectService()),
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

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<ProjectNotifier>().load(widget.projectName);
    });
  }

  @override
  void dispose() {
    _mapController.dispose();
    super.dispose();
  }

  Future<void> _logout() async {
    await context.read<AuthNotifier>().logout();
    if (mounted) context.go('/login');
  }

  @override
  Widget build(BuildContext context) {
    final title = context.select<ProjectNotifier, String>(
      (n) => n.projectName ?? widget.projectName,
    );

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
            onPressed: () => context.push(
                '/stats?project=${Uri.encodeComponent(widget.projectName)}'),
          ),
          IconButton(
            icon: const Icon(Icons.settings_outlined),
            tooltip: 'Settings',
            onPressed: () => context.push('/settings'),
          ),
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: 'Logout',
            onPressed: _logout,
          ),
          const SizedBox(width: 4),
        ],
      ),
      body: Consumer<ProjectNotifier>(
        builder: (context, notifier, _) {
          if (notifier.isLoading && notifier.geo == null) {
            return const Center(child: CircularProgressIndicator());
          }
          if (notifier.error != null && notifier.geo == null) {
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
          return _ViewLayout(
            notifier: notifier,
            mapController: _mapController,
            autoZoom: _autoZoom,
          );
        },
      ),
    );
  }
}

// ── Layout: map + elevation chart, no activity panel ─────────────────────────

class _ViewLayout extends StatelessWidget {
  final ProjectNotifier notifier;
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
    final elevChart = ElevationChart(
      activities: notifier.activities,
      selectedActivityId: selActId,
      onCursorChanged: (pos) =>
          notifier.elevationCursorNotifier.value = pos,
      mapCursorNotifier: notifier.mapCursorDistNotifier,
      track: selActId != null
          ? notifier.perActivityTracks[selActId.toString()] ??
              notifier.fullTrack
          : notifier.fullTrack,
    );

    final mapPanel = MapPanel(
      notifier: notifier,
      mapController: mapController,
      basemapUrl: kViewBasemapUrl,
      labelsUrl: kViewLabelsUrl,
    );

    return Column(
      children: [
        Expanded(child: mapPanel),
        elevChart,
      ],
    );
  }
}
