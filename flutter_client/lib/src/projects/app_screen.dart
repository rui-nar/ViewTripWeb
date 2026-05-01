/// Main app screen — map + activity panel for an open project.
// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use
library;

// dart:html is intentional — ViewTripWeb targets Flutter Web only.
import 'dart:html' as html;
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import 'package:flutter/services.dart';

import 'basemaps.dart';
import 'elevation_chart.dart';
import 'project_notifier.dart';
import 'activity_panel.dart';
import 'map_panel.dart';
import 'image_export.dart';
import 'project_settings_dialog.dart';

// ── AppScreen ─────────────────────────────────────────────────────────────────

class AppScreen extends StatefulWidget {
  final String projectName;

  const AppScreen({super.key, required this.projectName});

  @override
  State<AppScreen> createState() => _AppScreenState();
}

class _AppScreenState extends State<AppScreen> {
  final MapController _mapController = MapController();
  final GlobalKey<ManageMapPanelState> _mapPanelKey = GlobalKey();
  // Survives ManageMapPanelState recreation — prevents re-fitting after user pans.
  final ValueNotifier<bool> _mapFitted = ValueNotifier(false);
  bool _panelOpen = false;
  void _togglePanel() => setState(() => _panelOpen = !_panelOpen);
  bool _autoZoom = false;
  bool _isExporting = false;
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
    _mapFitted.dispose();
    super.dispose();
  }


  Future<void> _downloadFile(String apiPath, String fallbackFilename) async {
    setState(() => _isExporting = true);
    try {
      final res = await context
          .read<ProjectNotifier>()
          .fetchExportBytes(apiPath);
      String filename = fallbackFilename;
      final cd = res.headers['content-disposition'] ?? '';
      final match = RegExp(r'filename="([^"]+)"').firstMatch(cd);
      if (match != null) filename = match.group(1)!;

      final mimeType =
          res.headers['content-type'] ?? 'application/octet-stream';
      final blob = html.Blob([res.bodyBytes], mimeType);
      final url = html.Url.createObjectUrlFromBlob(blob);
      html.AnchorElement(href: url)
        ..setAttribute('download', filename)
        ..click();
      html.Url.revokeObjectUrl(url);

      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$filename downloaded')));
      }
    } on Exception catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(
              'Export failed: ${e.toString().replaceFirst('Exception: ', '')}')));
    } finally {
      if (mounted) setState(() => _isExporting = false);
    }
  }

  Future<void> _exportOptions() async {
    final name = widget.projectName;
    final enc = Uri.encodeComponent(name);

    final notifier = context.read<ProjectNotifier>();
    final hasMemoryPhotos = notifier.items.any(
      (i) =>
          i['item_type'] == 'memory' &&
          ((i['memory']?['photos'] as List?)?.isNotEmpty ?? false),
    );

    if (!mounted) return;
    final choice = await showDialog<String>(
      context: context,
      builder: (ctx) => SimpleDialog(
        title: const Text('Export project'),
        children: [
          SimpleDialogOption(
            onPressed: () => Navigator.of(ctx).pop('gpx'),
            child: const ListTile(
              leading: Icon(Icons.map_outlined),
              title: Text('GPX file'),
              subtitle: Text('Memories as waypoints, no photos'),
            ),
          ),
          SimpleDialogOption(
            onPressed: () => Navigator.of(ctx).pop('gettracks'),
            child: const ListTile(
              leading: Icon(Icons.article_outlined),
              title: Text('.gettracks file'),
              subtitle: Text('Full project data, no photo files'),
            ),
          ),
          if (hasMemoryPhotos)
            SimpleDialogOption(
              onPressed: () => Navigator.of(ctx).pop('zip'),
              child: const ListTile(
                leading: Icon(Icons.archive_outlined),
                title: Text('ZIP archive'),
                subtitle: Text('.gettracks + all memory photos'),
              ),
            ),
          SimpleDialogOption(
            onPressed: () => Navigator.of(ctx).pop('image'),
            child: const ListTile(
              leading: Icon(Icons.photo_outlined),
              title: Text('Export image (PNG)'),
              subtitle: Text('Map + elevation chart as a high-quality image'),
            ),
          ),
          SimpleDialogOption(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const ListTile(
              leading: Icon(Icons.close),
              title: Text('Cancel'),
            ),
          ),
        ],
      ),
    );

    if (choice == null || !mounted) return;
    if (choice == 'gpx') {
      await _downloadFile('/api/projects/$enc/export', '$name.gpx');
    } else if (choice == 'gettracks') {
      await _downloadFile(
          '/api/projects/$enc/export-gettracks', '$name.gettracks');
    } else if (choice == 'zip') {
      await _downloadFile('/api/projects/$enc/export-zip', '$name.zip');
    } else if (choice == 'image') {
      await _exportImage();
    }
  }

  Future<void> _exportImage() async {
    if (!mounted) return;
    if (_isExporting) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Export already in progress')));
      return;
    }
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => ImageExportDialog(
        projectName: widget.projectName,
        onExport: _startExport,
      ),
    );
  }

  Future<void> _startExport(ImageExportOptions opts) async {
    if (!mounted) return;
    setState(() => _isExporting = true);
    try {
      await performOffscreenExport(
        context: context,
        notifier: context.read<ProjectNotifier>(),
        projectName: widget.projectName,
        opts: opts,
      );
    } finally {
      if (mounted) setState(() => _isExporting = false);
    }
  }

  Future<void> _showRenameDialog(BuildContext context) async {
    final notifier = context.read<ProjectNotifier>();
    final ctrl = TextEditingController(text: notifier.projectName ?? '');
    await showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Rename project'),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          decoration: const InputDecoration(
            labelText: 'Project name',
            border: OutlineInputBorder(),
          ),
          onSubmitted: (_) => Navigator.of(ctx).pop(),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('Rename'),
          ),
        ],
      ),
    );
    final newName = ctrl.text.trim();
    ctrl.dispose();
    if (newName.isEmpty || newName == notifier.projectName) return;
    final result = await notifier.renameProject(newName);
    if (!context.mounted) return;
    if (result != null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Renamed to "$result"')),
      );
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(notifier.error ?? 'Rename failed')),
      );
    }
  }

  void _showTagFilterSheet(BuildContext context, ProjectNotifier notifier,
      {required bool readOnly}) {
    showModalBottomSheet<void>(
      context: context,
      useRootNavigator: true,
      builder: (_) => TagFilterSheet(notifier: notifier, readOnly: readOnly),
    );
  }

  Future<void> _showShareDialog() async {
    final notifier = context.read<ProjectNotifier>();
    // Capture before any await so the messenger is available inside the dialog.
    final messenger = ScaffoldMessenger.of(context);
    try {
      final token = await notifier.createShareToken();
      if (!mounted) return;

      final shareUrl = '${Uri.base.origin}/share/$token';

      await showDialog<void>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Share project'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text('Anyone with this link can view the project read-only:'),
              const SizedBox(height: 12),
              SelectableText(shareUrl),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () async {
                await Clipboard.setData(ClipboardData(text: shareUrl));
                messenger.showSnackBar(
                  const SnackBar(content: Text('Link copied to clipboard')),
                );
              },
              child: const Text('Copy link'),
            ),
            TextButton(
              onPressed: () async {
                Navigator.of(ctx).pop();
                await notifier.revokeShareToken();
                messenger.showSnackBar(
                  const SnackBar(content: Text('Share link revoked')),
                );
              },
              child: const Text('Revoke'),
            ),
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(),
              child: const Text('Close'),
            ),
          ],
        ),
      );
    } on Exception catch (e) {
      if (!mounted) return;
      messenger.showSnackBar(
        SnackBar(content: Text(
            'Share failed: ${e.toString().replaceFirst('Exception: ', '')}')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    // Only rebuild AppScreen (AppBar + LayoutBuilder) when the title changes.
    // ActivityPanel and MapPanel subscribe to the notifier themselves via Consumer,
    // so they still react to every notifyListeners() without pulling the AppBar
    // through an unnecessary rebuild on every selectActivity() call.
    final title = context.select<ProjectNotifier, String>(
      (n) => n.projectName ?? widget.projectName,
    );

    final isNarrow = MediaQuery.sizeOf(context).width < 720;

    return Scaffold(
      appBar: AppBar(
        automaticallyImplyLeading: false,
        title: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Flexible(
              child: Text(
                title.isEmpty ? 'ViewTripWeb' : title,
                overflow: TextOverflow.ellipsis,
              ),
            ),
            IconButton(
              icon: const Icon(Icons.edit_outlined, size: 18),
              tooltip: 'Rename project',
              visualDensity: VisualDensity.compact,
              onPressed: () => _showRenameDialog(context),
            ),
          ],
        ),
        actions: [
          // Hamburger — narrow only
          if (isNarrow)
            IconButton(
              icon: AnimatedSwitcher(
                duration: const Duration(milliseconds: 200),
                child: Icon(
                  _panelOpen ? Icons.menu_open : Icons.menu,
                  key: ValueKey(_panelOpen),
                ),
              ),
              onPressed: _togglePanel,
            ),

          // View mode toggle — always
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
              selected: const {false},
              onSelectionChanged: (s) => context.go(
                  '/view?project=${Uri.encodeComponent(widget.projectName)}'),
              style: const ButtonStyle(
                  visualDensity: VisualDensity.compact,
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap),
            ),
          ),

          // Tag filter — always visible
          Consumer<ProjectNotifier>(
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
                    : () => _showTagFilterSheet(context, n, readOnly: false),
              );
            },
          ),

          // Auto-zoom — always visible
          IconButton(
            icon: Icon(
              Icons.fit_screen,
              color: _autoZoom ? Theme.of(context).colorScheme.primary : null,
            ),
            tooltip: _autoZoom ? 'Auto-zoom on (tap to disable)' : 'Auto-zoom to selection',
            onPressed: () => setState(() => _autoZoom = !_autoZoom),
          ),

          if (isNarrow) ...[
            // ── Narrow: stats + strava visible; rest in overflow ──────────
            IconButton(
              icon: const Icon(Icons.bar_chart_outlined),
              tooltip: 'Statistics',
              onPressed: () => context.push(
                '/stats?project=${Uri.encodeComponent(widget.projectName)}',
                extra: context.read<ProjectNotifier>().availableTags,
              ),
            ),
            IconButton(
              icon: const Icon(Icons.playlist_add),
              tooltip: 'Import activities from Strava',
              onPressed: () => context.push(
                  '/strava-import?project=${Uri.encodeComponent(widget.projectName)}'),
            ),
            PopupMenuButton<int>(
              icon: const Icon(Icons.more_vert),
              tooltip: 'More options',
              onSelected: (v) {
                switch (v) {
                  case 0: if (!_isExporting) _exportOptions();
                  case 1: _showShareDialog();
                  case 2: showDialog<void>(
                    context: context,
                    useRootNavigator: true,
                    builder: (_) => ProjectSettingsDialog(
                      notifier: context.read<ProjectNotifier>(),
                    ),
                  );
                  case 3: context.push('/settings');
                  case 4: context.go('/projects');
                }
              },
              itemBuilder: (_) => [
                PopupMenuItem(
                  value: 0,
                  enabled: !_isExporting,
                  child: ListTile(
                    leading: _isExporting
                        ? const SizedBox(width: 24, height: 24,
                            child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(Icons.download),
                    title: const Text('Export project'),
                    enabled: !_isExporting,
                  ),
                ),
                const PopupMenuItem(
                  value: 1,
                  child: ListTile(
                    leading: Icon(Icons.share_outlined),
                    title: Text('Share'),
                  ),
                ),
                const PopupMenuItem(
                  value: 2,
                  child: ListTile(
                    leading: Icon(Icons.tune),
                    title: Text('Project settings'),
                  ),
                ),
                const PopupMenuItem(
                  value: 3,
                  child: ListTile(
                    leading: Icon(Icons.settings_outlined),
                    title: Text('Settings'),
                  ),
                ),
                const PopupMenuItem(
                  value: 4,
                  child: ListTile(
                    leading: Icon(Icons.arrow_back),
                    title: Text('Back to projects'),
                  ),
                ),
              ],
            ),
          ] else ...[
            // ── Wide: all icons in original order ─────────────────────────
            IconButton(
              icon: _isExporting
                  ? const SizedBox(width: 20, height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.download),
              tooltip: 'Export project',
              onPressed: _isExporting ? null : _exportOptions,
            ),
            IconButton(
              icon: const Icon(Icons.playlist_add),
              tooltip: 'Import activities from Strava',
              onPressed: () => context.push(
                  '/strava-import?project=${Uri.encodeComponent(widget.projectName)}'),
            ),
            IconButton(
              icon: const Icon(Icons.share_outlined),
              tooltip: 'Share project',
              onPressed: _showShareDialog,
            ),
            IconButton(
              icon: const Icon(Icons.bar_chart_outlined),
              tooltip: 'Statistics',
              onPressed: () => context.push(
                '/stats?project=${Uri.encodeComponent(widget.projectName)}',
                extra: context.read<ProjectNotifier>().availableTags,
              ),
            ),
            IconButton(
              icon: const Icon(Icons.tune),
              tooltip: 'Project settings',
              onPressed: () => showDialog<void>(
                context: context,
                useRootNavigator: true,
                builder: (_) => ProjectSettingsDialog(
                  notifier: context.read<ProjectNotifier>(),
                ),
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
        ],
      ),
      body: LayoutBuilder(
        builder: (context, constraints) {
          // Auto-close the panel when switching to wide layout.
          if (constraints.maxWidth >= 720 && _panelOpen) {
            WidgetsBinding.instance.addPostFrameCallback((_) {
              if (mounted && _panelOpen) setState(() => _panelOpen = false);
            });
          }
          if (constraints.maxWidth >= 720) {
            // ── Wide layout: side-by-side ────────────────────────────────
            return Row(
              children: [
                SizedBox(
                  width: 280,
                  child: Consumer<ProjectNotifier>(
                    builder: (_, n, __) => ActivityPanel(
                      notifier: n,
                      mapController: _mapController,
                    ),
                  ),
                ),
                Expanded(
                  child: Stack(
                    children: [
                      Consumer<ProjectNotifier>(
                        builder: (_, n, __) => ManageMapPanel(
                          key: _mapPanelKey,
                          notifier: n,
                          mapController: _mapController,
                          autoZoom: _autoZoom,
                          basemapUrl: kActiveManageBasemapUrl,
                          basemapSubdomains: kActiveManageSubdomains,
                          fittedNotifier: _mapFitted,
                        ),
                      ),
                      Positioned(
                        bottom: 0, left: 0, right: 0,
                        child: Builder(builder: (ctx) => Container(
                          color: Theme.of(ctx).colorScheme.surface.withOpacity(0.5),
                          child: Selector<ProjectNotifier,
                              (List<Map<String, dynamic>>, Object?, String?, Set<String>)>(
                            selector: (_, n) => (
                              n.activities,
                              n.selectedActivityId as Object?,
                              n.selectedDay,
                              n.selectedDays,
                            ),
                            shouldRebuild: (a, b) =>
                                !identical(a.$1, b.$1) ||
                                a.$2?.toString() != b.$2?.toString() ||
                                a.$3 != b.$3 ||
                                !ManageMapPanelState.setEquals(a.$4, b.$4),
                            builder: (ctx, tuple, __) {
                              final n = ctx.read<ProjectNotifier>();
                              final allActivities = tuple.$1;
                              final selActId = tuple.$2;
                              final selDay = tuple.$3;
                              final selDays = tuple.$4;
                              final effectiveDays = selDays.isNotEmpty
                                  ? selDays
                                  : (selDay != null ? {selDay} : <String>{});
                              final activities = effectiveDays.isEmpty
                                  ? allActivities
                                  : allActivities.where((a) =>
                                      effectiveDays.contains(
                                        (a['start_date_local'] as String? ?? '')
                                            .split('T').first)).toList();
                              return ElevationChart(
                                activities: activities,
                                selectedActivityId: selActId,
                                onCursorChanged: (pos) =>
                                    n.elevationCursorNotifier.value = pos,
                                mapCursorNotifier: n.mapCursorDistNotifier,
                                track: selActId != null
                                    ? n.perActivityTracks[selActId.toString()] ?? n.fullTrack
                                    : n.fullTrack,
                              );
                            },
                          ),
                        )),
                      ),
                    ],
                  ),
                ),
              ],
            );
          } else {
            // ── Narrow layout: full-screen map + slide-in activity panel ──
            final mapHeight = constraints.maxHeight;
            return Stack(
              children: [
                // Base: full-height map
                Consumer<ProjectNotifier>(
                  builder: (_, n, __) => ManageMapPanel(
                    key: _mapPanelKey,
                    notifier: n,
                    mapController: _mapController,
                    autoZoom: _autoZoom,
                    basemapUrl: kActiveManageBasemapUrl,
                    basemapSubdomains: kActiveManageSubdomains,
                    fittedNotifier: _mapFitted,
                  ),
                ),

                // Elevation chart overlaid at bottom
                Positioned(
                  bottom: 0, left: 0, right: 0,
                  child: Builder(builder: (ctx) => Container(
                    color: Theme.of(ctx).colorScheme.surface.withOpacity(0.42),
                    child: Selector<ProjectNotifier,
                        (List<Map<String, dynamic>>, Object?, String?)>(
                      selector: (_, n) => (
                        n.activities,
                        n.selectedActivityId as Object?,
                        n.selectedDay,
                      ),
                      shouldRebuild: (a, b) =>
                          !identical(a.$1, b.$1) ||
                          a.$2?.toString() != b.$2?.toString() ||
                          a.$3 != b.$3,
                      builder: (ctx, tuple, __) {
                        final n = ctx.read<ProjectNotifier>();
                        final allActivities = tuple.$1;
                        final selActId = tuple.$2;
                        final selDay = tuple.$3;
                        final activities = selDay != null
                            ? allActivities.where((a) =>
                                (a['start_date_local'] as String? ?? '')
                                    .split('T').first == selDay).toList()
                            : allActivities;
                        return ElevationChart(
                          activities: activities,
                          selectedActivityId: selActId,
                          onCursorChanged: (pos) =>
                              n.elevationCursorNotifier.value = pos,
                          mapCursorNotifier: n.mapCursorDistNotifier,
                          track: selActId != null
                              ? n.perActivityTracks[selActId.toString()] ?? n.fullTrack
                              : n.fullTrack,
                        );
                      },
                    ),
                  )),
                ),

                // Overlay: activity panel slides in from the left
                AnimatedSlide(
                  offset: _panelOpen ? Offset.zero : const Offset(-1.0, 0),
                  duration: const Duration(milliseconds: 280),
                  curve: Curves.easeInOut,
                  child: Align(
                    alignment: Alignment.topLeft,
                    child: Consumer<ProjectNotifier>(
                      builder: (_, n, __) => MobileActivityPanelOverlay(
                        notifier: n,
                        mapController: _mapController,
                        height: mapHeight,
                      ),
                    ),
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

// ── Image export ──────────────────────────────────────────────────────────────

