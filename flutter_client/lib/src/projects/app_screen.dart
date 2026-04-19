/// Main app screen — map + activity panel for an open project.
// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use
library;

// dart:html is intentional — ViewTripWeb targets Flutter Web only.
import 'dart:html' as html;
import 'dart:ui' as ui;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:go_router/go_router.dart';
import 'package:latlong2/latlong.dart';
import 'package:provider/provider.dart';

import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';

import '../api/client.dart';
import '../auth/auth_notifier.dart';
import '../map/polyline_decoder.dart';
import 'basemaps.dart';
import 'project_notifier.dart';
import 'memory_detail_modal.dart';
import 'memory_dialog.dart';
import 'day_meta_editor.dart';
import 'project_settings_dialog.dart';
import 'segment_dialog.dart';

// ── Export constants ──────────────────────────────────────────────────────────
const _kExportMapWidth    = 2400.0;
const _kExportMapHeight   = 1600.0;
const _kExportChartHeight = 200.0;

// ── AppScreen ─────────────────────────────────────────────────────────────────

class AppScreen extends StatefulWidget {
  final String projectName;

  const AppScreen({super.key, required this.projectName});

  @override
  State<AppScreen> createState() => _AppScreenState();
}

class _AppScreenState extends State<AppScreen> {
  final MapController _mapController = MapController();
  final GlobalKey<_Stage1MapPanelState> _mapPanelKey = GlobalKey();
  // Survives _Stage1MapPanelState recreation — prevents re-fitting after user pans.
  final ValueNotifier<bool> _mapFitted = ValueNotifier(false);
  bool _panelOpen = false;
  void _togglePanel() => setState(() => _panelOpen = !_panelOpen);
  bool _autoZoom = false;
  bool _isExporting = false;
  OverlayEntry? _exportOverlay;

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

  Future<void> _logout() async {
    await context.read<AuthNotifier>().logout();
    if (mounted) context.go('/login');
  }

  Future<void> _downloadFile(String apiPath, String fallbackFilename) async {
    setState(() => _isExporting = true);
    try {
      final res = await api.getRaw(apiPath);
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
    } on ApiException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Export failed: ${e.body}')));
    } finally {
      if (mounted) setState(() => _isExporting = false);
    }
  }

  Future<void> _exportOptions() async {
    final name = widget.projectName;
    final enc = Uri.encodeComponent(name);

    // Check whether any memory items have photos attached.
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
    if (_exportOverlay != null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Export already in progress')));
      return;
    }
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => _ImageExportDialog(
        projectName: widget.projectName,
        onExport: _startOffscreenExport,
      ),
    );
  }

  static bool _uint8ListEquals(Uint8List a, Uint8List b) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (a[i] != b[i]) return false;
    }
    return true;
  }

  /// Returns true if the thumbnail is a near-uniform (blank/grey) image —
  /// i.e., tiles haven't started rendering yet.
  static bool _isThumbnailBlank(Uint8List bytes) {
    if (bytes.length < 16) return true;
    final ref = bytes[0];
    // Sample R channel every 4 bytes (RGBA). Any pixel differing by >12
    // from the first means real content has appeared.
    for (var i = 0; i < bytes.length; i += 4) {
      if ((bytes[i] - ref).abs() > 12) return false;
    }
    return true;
  }

  Future<void> _startOffscreenExport(_ImageExportOptions opts) async {
    final notifier = context.read<ProjectNotifier>();
    final geo = notifier.geo;
    if (geo == null) return;

    // Build polylines and collect all points for camera fit.
    final allPoints = <LatLng>[];
    final polylines = <Polyline>[];
    final features = geo['features'];
    if (features is List) {
      for (final feature in features) {
        if (feature is! Map) continue;
        final geometry = feature['geometry'] as Map? ?? {};
        final coords = geometry['coordinates'];
        if (coords is! List) continue;
        final points = <LatLng>[];
        for (final c in coords) {
          if (c is List && c.length >= 2) {
            points.add(LatLng((c[1] as num).toDouble(), (c[0] as num).toDouble()));
          }
        }
        if (points.isEmpty) continue;
        allPoints.addAll(points);
        final props = feature['properties'] as Map? ?? {};
        final isSegment = props['type'] == 'segment';
        polylines.add(Polyline(
          points: points,
          color: isSegment ? const Color(0xFF888888) : const Color(0xFFF97316),
          strokeWidth: isSegment ? 2.0 : 2.5,
        ));
      }
    }

    final exportKey  = GlobalKey();
    final exportCtrl = MapController();

    // Render at the actual screen width so the widget is within the browser
    // viewport — Flutter Web culls off-screen widgets and tiles never load.
    // Scale down from _kExportMapWidth proportionally, then use a matching
    // pixelRatio in toImage() to get back to the target 2400×1600 resolution.
    final screenSize = MediaQuery.of(context).size;
    final renderW = screenSize.width.clamp(600.0, _kExportMapWidth);
    final renderScale = renderW / _kExportMapWidth;
    final renderMapH  = _kExportMapHeight   * renderScale;
    final renderChartH = _kExportChartHeight * renderScale;
    final totalRenderH = renderMapH + (opts.includeChart ? renderChartH : 0);
    final captureRatio = _kExportMapWidth / renderW; // upscale back to 2400 px

    _exportOverlay = OverlayEntry(builder: (_) {
      // Widget renders at renderW×totalRenderH at position 0,0 — fully within
      // the viewport so Flutter paints it and the tile provider fetches tiles.
      // toImage(pixelRatio: captureRatio) upscales the capture to the target
      // 2400×1600 resolution. No transform or opacity tricks needed.
      return Positioned(
        left: 0,
        top: 0,
        child: IgnorePointer(
          child: SizedBox(
            width: renderW,
            height: totalRenderH,
            child: RepaintBoundary(
              key: exportKey,
              child: Container(
                color: Colors.white,
                child: Column(
                  children: [
                    Expanded(
                      child: FlutterMap(
                        mapController: exportCtrl,
                        options: MapOptions(
                          initialCameraFit: allPoints.isNotEmpty
                              ? CameraFit.bounds(
                                  bounds: LatLngBounds.fromPoints(allPoints),
                                  padding: const EdgeInsets.all(48))
                              : null,
                          interactionOptions: const InteractionOptions(
                              flags: InteractiveFlag.none),
                        ),
                        children: [
                          TileLayer(
                            urlTemplate: kActiveViewBasemapUrl,
                            userAgentPackageName: 'com.viewtrip.client',
                            tileProvider: NetworkTileProvider(),
                            maxNativeZoom: 22,
                          ),
                          TileLayer(
                            urlTemplate: kActiveViewLabelsUrl,
                            subdomains: kActiveViewLabelsSubdomains,
                            userAgentPackageName: 'com.viewtrip.client',
                            tileProvider: NetworkTileProvider(),
                            maxNativeZoom: 22,
                          ),
                          if (polylines.isNotEmpty)
                            PolylineLayer(
                                polylines: polylines,
                                simplificationTolerance: 0),
                        ],
                      ),
                    ),
                    if (opts.includeChart)
                      SizedBox(
                        height: renderChartH,
                        child: ElevationChart(
                          activities: notifier.activities,
                          selectedActivityId: null,
                          track: notifier.fullTrack,
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ),
        ),
      );
    });

    Overlay.of(context).insert(_exportOverlay!);

    final messenger = ScaffoldMessenger.of(context);
    messenger.showSnackBar(const SnackBar(
      content: Row(children: [
        SizedBox(width: 16, height: 16,
            child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)),
        SizedBox(width: 12),
        Text('Preparing map export…'),
      ]),
      duration: Duration(seconds: 60),
    ));

    // Wait for tiles to settle: poll low-res thumbnails until two consecutive
    // captures are pixel-identical (or a 12 s deadline is reached).
    await Future.delayed(const Duration(seconds: 1)); // initial paint pass
    {
      Uint8List? prevBytes;
      for (var i = 0; i < 18; i++) {
        final b = exportKey.currentContext?.findRenderObject()
            as RenderRepaintBoundary?;
        if (b == null) break;
        // Use pixelRatio 0.05 → ~120×80 px thumbnail — fast to capture & compare.
        final probe = await b.toImage(pixelRatio: 0.05);
        final bd = await probe.toByteData();
        probe.dispose();
        if (bd == null) break;
        final bytes = bd.buffer.asUint8List();
        if (prevBytes != null &&
            _uint8ListEquals(prevBytes, bytes) &&
            !_isThumbnailBlank(bytes)) { break; }
        prevBytes = bytes;
        await Future.delayed(const Duration(milliseconds: 600));
      }
    }

    try {
      final boundary = exportKey.currentContext?.findRenderObject()
          as RenderRepaintBoundary?;
      if (boundary == null) return;

      ui.Image image = await boundary.toImage(pixelRatio: captureRatio);

      // Composite onto white background + optional title overlay.
      {
        final recorder = ui.PictureRecorder();
        final canvas = Canvas(recorder);
        canvas.drawRect(
          Rect.fromLTWH(0, 0, image.width.toDouble(), image.height.toDouble()),
          Paint()..color = const Color(0xFFFFFFFF),
        );
        canvas.drawImage(image, Offset.zero, Paint());
        if (opts.includeTitle) {
          final tp = TextPainter(
            text: TextSpan(
              text: widget.projectName,
              style: const TextStyle(
                color: Colors.black,
                fontSize: 18,
                fontWeight: FontWeight.bold,
              ),
            ),
            textDirection: TextDirection.ltr,
          )..layout(maxWidth: image.width.toDouble() - 32);
          tp.paint(canvas, const Offset(16, 16));
        }
        final picture = recorder.endRecording();
        image = await picture.toImage(image.width, image.height);
      }

      final byteData = await image.toByteData(format: ui.ImageByteFormat.png);
      if (byteData == null) return;
      final bytes = byteData.buffer.asUint8List();
      final blob = html.Blob([bytes], 'image/png');
      final url  = html.Url.createObjectUrlFromBlob(blob);
      html.AnchorElement(href: url)
        ..setAttribute('download', '${widget.projectName}.png')
        ..click();
      html.Url.revokeObjectUrl(url);

      messenger.hideCurrentSnackBar();
      messenger.showSnackBar(const SnackBar(
          content: Text('Export complete'), duration: Duration(seconds: 3)));
    } finally {
      _exportOverlay?.remove();
      _exportOverlay = null;
      exportCtrl.dispose();
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
    final name = widget.projectName;
    // Capture before any await so the messenger is available inside the dialog.
    final messenger = ScaffoldMessenger.of(context);
    try {
      final result = await api.post(
        '/api/projects/${Uri.encodeComponent(name)}/share',
        {},
      ) as Map<String, dynamic>;
      final token = result['share_token'] as String? ?? '';
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
                await api.delete(
                    '/api/projects/${Uri.encodeComponent(name)}/share');
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
    } on ApiException catch (e) {
      if (!mounted) return;
      messenger.showSnackBar(
        SnackBar(content: Text('Share failed: ${e.body}')),
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

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/projects'),
        ),
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
          IconButton(
            icon: Icon(
              Icons.fit_screen,
              color: _autoZoom ? Theme.of(context).colorScheme.primary : null,
            ),
            tooltip: _autoZoom ? 'Auto-zoom on (tap to disable)' : 'Auto-zoom to selection',
            onPressed: () => setState(() => _autoZoom = !_autoZoom),
          ),
          IconButton(
            icon: _isExporting
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
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
            icon: const Icon(Icons.logout),
            tooltip: 'Logout',
            onPressed: _logout,
          ),
          const SizedBox(width: 4),
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
                        builder: (_, n, __) => _Stage1MapPanel(
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
                                !_Stage1MapPanelState._setEquals(a.$4, b.$4),
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
                  builder: (_, n, __) => _Stage1MapPanel(
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
                      builder: (_, n, __) => _MobileActivityPanelOverlay(
                        notifier: n,
                        mapController: _mapController,
                        height: mapHeight,
                      ),
                    ),
                  ),
                ),

                // Toggle FAB: sits just above the elevation chart
                Positioned(
                  left: 12,
                  bottom: 172,
                  child: Builder(builder: (ctx) {
                    final theme = Theme.of(ctx);
                    return FloatingActionButton.small(
                      heroTag: 'activityPanelToggle',
                      backgroundColor: theme.colorScheme.surface,
                      foregroundColor: theme.colorScheme.onSurface,
                      onPressed: _togglePanel,
                      child: AnimatedRotation(
                        turns: _panelOpen ? 0.5 : 0.0,
                        duration: const Duration(milliseconds: 280),
                        child: const Icon(Icons.chevron_right),
                      ),
                    );
                  }),
                ),
              ],
            );
          }
        },
      ),
    );
  }
}

// ── MapPanel ──────────────────────────────────────────────────────────────────

class MapPanel extends StatefulWidget {
  final ProjectNotifier notifier;
  final MapController mapController;
  final String basemapUrl;
  final List<String> basemapSubdomains;
  final String? labelsUrl;

  const MapPanel({
    super.key,
    required this.notifier,
    required this.mapController,
    required this.basemapUrl,
    this.basemapSubdomains = const [],
    this.labelsUrl,
  });

  @override
  State<MapPanel> createState() => _MapPanelState();
}

class _MapPanelState extends State<MapPanel> {
  bool _fittedBounds = false;
  // Polyline + bounds cache — only rebuilt when geo or selection changes.
  Map<String, dynamic>? _lastGeo;
  dynamic _lastSelectedId = _sentinel;
  dynamic _lastSelectedSegId = _sentinel;
  List<Polyline> _cachedPolylines = [];
  List<LatLng> _cachedAllPoints = [];
  List<Marker> _cachedSegmentMarkers = [];
  late final NetworkTileProvider _tileProvider;

  static const _sentinel = Object(); // distinct from null

  @override
  void initState() {
    super.initState();
    _tileProvider = NetworkTileProvider();
  }

  List<Polyline> _buildPolylines(
    Map<String, dynamic> geo,
    dynamic selectedActivityId,
    dynamic selectedSegmentId,
  ) {
    final features = geo['features'];
    if (features is! List) return [];

    final polylines = <Polyline>[];
    final hasSelection = selectedActivityId != null || selectedSegmentId != null;
    for (final feature in features) {
      if (feature is! Map) continue;
      final props = feature['properties'] as Map? ?? {};
      final geometry = feature['geometry'] as Map? ?? {};
      final coords = geometry['coordinates'];
      if (coords is! List) continue;

      final points = <LatLng>[];
      for (final c in coords) {
        if (c is List && c.length >= 2) {
          final lon = (c[0] as num).toDouble();
          final lat = (c[1] as num).toDouble();
          points.add(LatLng(lat, lon));
        }
      }
      if (points.isEmpty) continue;

      final isSegment = props['type'] == 'segment';
      final isSelAct = selectedActivityId != null &&
          props['activity_id']?.toString() == selectedActivityId.toString();
      final isSelSeg = selectedSegmentId != null &&
          props['segment_id']?.toString() == selectedSegmentId.toString();

      final Color color;
      final double strokeWidth;
      if (isSegment) {
        if (isSelSeg) {
          color = const Color(0xFF44AAFF);   // bright blue — selected segment
          strokeWidth = 4.0;
        } else if (hasSelection) {
          color = const Color(0x60888888);   // dimmed grey
          strokeWidth = 2.0;
        } else {
          color = const Color(0xFF888888);   // normal grey
          strokeWidth = 2.0;
        }
      } else {
        if (isSelAct) {
          color = const Color(0xFFEF4444);   // red — selected activity
          strokeWidth = 5.0;
        } else if (hasSelection) {
          color = const Color(0x60F97316);   // dimmed orange
          strokeWidth = 2.5;
        } else {
          color = const Color(0xFFF97316);   // full orange
          strokeWidth = 2.5;
        }
      }
      polylines.add(Polyline(points: points, color: color, strokeWidth: strokeWidth));
    }
    return polylines;
  }

  static IconData _iconForSegmentType(String? type) {
    switch (type?.toLowerCase()) {
      case 'flight': return Icons.flight;
      case 'train':  return Icons.train;
      case 'bus':    return Icons.directions_bus;
      case 'boat':   return Icons.directions_boat;
      default:       return Icons.route;
    }
  }

  List<Marker> _buildSegmentMarkers(
    Map<String, dynamic> geo,
    dynamic selectedSegmentId,
    bool hasSelection,
  ) {
    final features = geo['features'];
    if (features is! List) return [];
    final markers = <Marker>[];
    for (final feature in features) {
      if (feature is! Map) continue;
      final props = feature['properties'] as Map? ?? {};
      if (props['type'] != 'segment') continue;
      final coords = (feature['geometry'] as Map? ?? {})['coordinates'];
      if (coords is! List || coords.isEmpty) continue;

      final mid = coords[coords.length ~/ 2];
      if (mid is! List || mid.length < 2) continue;
      final point = LatLng((mid[1] as num).toDouble(), (mid[0] as num).toDouble());

      final segId = props['segment_id']?.toString();
      final isSelected = selectedSegmentId != null &&
          segId == selectedSegmentId.toString();

      final bgColor = isSelected
          ? const Color(0xFF44AAFF)
          : hasSelection
              ? const Color(0x60888888)
              : const Color(0xFF888888);

      markers.add(Marker(
        point: point,
        width: 22,
        height: 22,
        child: Container(
          decoration: BoxDecoration(color: bgColor, shape: BoxShape.circle),
          child: Icon(
            _iconForSegmentType(props['segment_type'] as String?),
            color: Colors.white,
            size: 13,
          ),
        ),
      ));
    }
    return markers;
  }

  List<LatLng> _allPoints(List<Polyline> polylines) {
    return polylines.expand((p) => p.points).toList();
  }

  void _fitBoundsOnce(List<LatLng> points) {
    if (_fittedBounds || points.isEmpty) return;
    _fittedBounds = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      double minLat = points.first.latitude;
      double maxLat = points.first.latitude;
      double minLon = points.first.longitude;
      double maxLon = points.first.longitude;
      for (final p in points) {
        if (p.latitude < minLat) minLat = p.latitude;
        if (p.latitude > maxLat) maxLat = p.latitude;
        if (p.longitude < minLon) minLon = p.longitude;
        if (p.longitude > maxLon) maxLon = p.longitude;
      }
      widget.mapController.fitCamera(
        CameraFit.bounds(
          bounds: LatLngBounds(
            LatLng(minLat, minLon),
            LatLng(maxLat, maxLon),
          ),
          padding: const EdgeInsets.fromLTRB(32, 32, 32, 32 + 160),
        ),
      );
    });
  }

  @override
  void didUpdateWidget(MapPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    // Reset fit flag when a different notifier instance is passed (new project).
    if (oldWidget.notifier != widget.notifier) {
      _fittedBounds = false;
    }
  }

  void _onMapTap(LatLng latlng) {
    final track = widget.notifier.fullTrack;
    if (track.isEmpty) return;
    int nearest = 0;
    double minDist = double.infinity;
    for (int i = 0; i < track.length; i++) {
      final dLat = track[i].$2.latitude  - latlng.latitude;
      final dLon = track[i].$2.longitude - latlng.longitude;
      final d = dLat * dLat + dLon * dLon;
      if (d < minDist) { minDist = d; nearest = i; }
    }
    widget.notifier.elevationCursorNotifier.value = track[nearest].$2;
    widget.notifier.mapCursorDistNotifier.value   = track[nearest].$1;
  }

  @override
  Widget build(BuildContext context) {
    final notifier = widget.notifier;

    // Recompute polylines only when geo or selection changes.
    final geo = notifier.geo;
    final selActId = notifier.selectedActivityId;
    final selSegId = notifier.selectedSegmentId;
    final selectionChanged = selActId != _lastSelectedId ||
        selSegId?.toString() != _lastSelectedSegId?.toString();
    if (!identical(geo, _lastGeo) || selectionChanged) {
      _lastGeo = geo;
      _lastSelectedId = selActId;
      _lastSelectedSegId = selSegId;
      _cachedPolylines = geo != null ? _buildPolylines(geo, selActId, selSegId) : [];
      _cachedAllPoints = _allPoints(_cachedPolylines);
      final hasSelection = selActId != null || selSegId != null;
      _cachedSegmentMarkers = geo != null
          ? _buildSegmentMarkers(geo, selSegId, hasSelection)
          : [];
      // Only re-fit when the selection changes (user picks a different
      // activity/segment). A geo update from progressive track loading
      // should never reset the viewport the user has already panned/zoomed.
      if (selectionChanged) _fittedBounds = false;
    }
    final polylines = _cachedPolylines;
    final allPoints = _cachedAllPoints;

    if (allPoints.isNotEmpty && !notifier.isLoading) {
      _fitBoundsOnce(allPoints);
    }

    // FlutterMap stays mounted throughout loading so the MapController stays
    // attached and tiles don't get torn down on every load.  A spinner is
    // overlaid on top while data is in flight.
    return Stack(
      children: [
        FlutterMap(
          mapController: widget.mapController,
          options: MapOptions(
            initialCenter: const LatLng(0, 0),
            initialZoom: 2,
            interactionOptions: const InteractionOptions(
              flags: InteractiveFlag.all & ~InteractiveFlag.rotate,
            ),
            onTap: (_, latlng) => _onMapTap(latlng),
          ),
          children: [
            TileLayer(
              urlTemplate: widget.basemapUrl,
              subdomains: widget.basemapSubdomains,
              userAgentPackageName: 'com.viewtrip.client',
              tileProvider: _tileProvider,
              maxNativeZoom: 22,
              retinaMode: RetinaMode.isHighDensity(context),
            ),
            if (widget.labelsUrl != null)
              ColorFiltered(
                colorFilter: ColorFilter.matrix(<double>[
                  1, 0, 0, 0, 0,
                  0, 1, 0, 0, 0,
                  0, 0, 1, 0, 0,
                  0, 0, 0, 0.5, 0,
                ]),
                child: TileLayer(
                  urlTemplate: widget.labelsUrl!,
                  subdomains: kActiveViewLabelsSubdomains,
                  userAgentPackageName: 'com.viewtrip.client',
                  tileProvider: _tileProvider,
                  maxNativeZoom: 22,
                ),
              ),
            if (polylines.isNotEmpty)
              PolylineLayer(
                polylines: polylines,
                // Reduce GPU path vertices at low zoom — detail preserved when zoomed in.
                simplificationTolerance: 0.5,
              ),
            if (_cachedSegmentMarkers.isNotEmpty)
              MarkerLayer(markers: _cachedSegmentMarkers),
            // Preview arc uses ValueListenableBuilder so only this layer rebuilds
            // when the segment dialog updates coordinates — not the whole map.
            ValueListenableBuilder<List<LatLng>?>(
              valueListenable: notifier.previewArcNotifier,
              builder: (_, arc, __) {
                if (arc == null) return const SizedBox.shrink();
                return PolylineLayer(
                  polylines: [
                    Polyline(
                      points: arc,
                      color: const Color(0xCC6366F1),
                      strokeWidth: 2.5,
                    ),
                  ],
                );
              },
            ),
            // Elevation cursor — driven by chart hover/tap and by map taps.
            ValueListenableBuilder<LatLng?>(
              valueListenable: notifier.elevationCursorNotifier,
              builder: (_, cursor, __) {
                if (cursor == null) return const SizedBox.shrink();
                return MarkerLayer(
                  markers: [
                    Marker(
                      point: cursor,
                      width: 16,
                      height: 16,
                      child: Container(
                        decoration: BoxDecoration(
                          color: const Color(0xFFF97316),
                          shape: BoxShape.circle,
                          border: Border.all(color: Colors.white, width: 2),
                        ),
                      ),
                    ),
                  ],
                );
              },
            ),
          ],
        ),
        if (notifier.isLoading)
          const Center(child: CircularProgressIndicator()),
      ],
    );
  }
}

// ── ActivityPanel ─────────────────────────────────────────────────────────────

class ActivityPanel extends StatefulWidget {
  final ProjectNotifier notifier;
  final MapController? mapController;
  final ScrollController? scrollController;
  const ActivityPanel({
    super.key,
    required this.notifier,
    this.mapController,
    this.scrollController,
  });

  @override
  State<ActivityPanel> createState() => _ActivityPanelState();
}

// ── Day-grouping display list helpers ─────────────────────────────────────────

class _DayHeader {
  final int dayNumber;
  final DateTime date;
  final String dateKey; // "YYYY-MM-DD"
  const _DayHeader(this.dayNumber, this.date, this.dateKey);
}

class _PanelItem {
  final int originalIndex;
  final Map<String, dynamic> item;
  final String? dateKey;
  const _PanelItem(this.originalIndex, this.item, this.dateKey);
}

// ─────────────────────────────────────────────────────────────────────────────

class _ActivityPanelState extends State<ActivityPanel> {
  // activityById cache — rebuilt only when the activities list reference changes.
  List<Map<String, dynamic>>? _lastActivities;
  Map<dynamic, Map<String, dynamic>> _activityById = {};

  // Day grouping state
  Set<int> _collapsedDays = {};
  String? _selectedDay; // "YYYY-MM-DD"

  // Multi-select state
  bool _multiSelect = false;
  final Set<String> _selectedDays = {};
  String? _anchorDayKey; // last day tapped without Shift — range-select anchor

  // Narrow-layout: day keys whose edit strip is revealed by swipe-right
  final Set<String> _expandedDayEdits = {};

  // Memories-only filter toggle
  bool _memoriesOnly = false;

  // Display list cache — rebuilt when items or activities change.
  List<Map<String, dynamic>>? _lastItems;
  List<Object> _displayList = [];
  bool _initialCollapseApplied = false;

  // Theme-derived styles cached in didChangeDependencies so copyWith is not
  // called on every build().
  TextStyle? _segmentTitleStyle;

  static const _months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  static String _fmtGroupDate(DateTime d) => '${_months[d.month - 1]} ${d.day}';

  void _refreshActivityById(List<Map<String, dynamic>> activities) {
    if (identical(activities, _lastActivities)) return;
    _lastActivities = activities;
    _activityById = {for (final a in activities) a['id']: a};
  }

  void _rebuildDisplayList(
    List<Map<String, dynamic>> items,
    String? tripStartOverride,
  ) {
    if (identical(items, _lastItems) && tripStartOverride == _lastTripStart) return;
    _lastItems = items;
    _lastTripStart = tripStartOverride;
    _displayList = _buildDisplayList(items, _activityById, tripStartOverride);
    // Collapse all days on first load only; never reset after that.
    // Only apply once we have actual day headers (items may be empty on initState).
    if (!_initialCollapseApplied && _displayList.any((o) => o is _DayHeader)) {
      _initialCollapseApplied = true;
      _collapsedDays = {
        for (final o in _displayList) if (o is _DayHeader) o.dayNumber
      };
      // Rebuild now that _collapsedDays is populated — _buildDisplayList filters
      // children using _collapsedDays, so the first call above produced an
      // uncollapsed list.
      _displayList = _buildDisplayList(items, _activityById, tripStartOverride);
    }
  }

  void _toggleMultiSelect() {
    setState(() {
      _multiSelect = false;
      _selectedDays.clear();
      _anchorDayKey = null;
      widget.notifier.selectDays({});
    });
  }

  void _enterMultiSelectWithDay(String dateKey) {
    setState(() {
      _multiSelect = true;
      // Carry the existing single-selected day into the multi-select set
      // so Ctrl+click or long-press never silently drops what was selected.
      if (_selectedDay != null) _selectedDays.add(_selectedDay!);
      _selectedDays.add(dateKey);
      _anchorDayKey = dateKey;
      _selectedDay = null;
    });
    widget.notifier.selectDays(Set.from(_selectedDays));
  }

  void _handleMultiSelectTap(String dateKey) {
    final isShift = HardwareKeyboard.instance.isShiftPressed;
    setState(() {
      if (isShift && _anchorDayKey != null) {
        final keys = _orderedDayKeys();
        final a = keys.indexOf(_anchorDayKey!);
        final b = keys.indexOf(dateKey);
        if (a != -1 && b != -1) {
          final lo = a < b ? a : b;
          final hi = a < b ? b : a;
          _selectedDays.addAll(keys.sublist(lo, hi + 1));
        }
        // anchor unchanged on Shift-click
      } else {
        if (_selectedDays.contains(dateKey)) {
          _selectedDays.remove(dateKey);
        } else {
          _selectedDays.add(dateKey);
        }
        _anchorDayKey = dateKey;
        if (_selectedDays.isEmpty) {
          _multiSelect = false;
          _anchorDayKey = null;
        }
      }
    });
    widget.notifier.selectDays(Set.from(_selectedDays));
  }

  List<String> _orderedDayKeys() => _displayList
      .whereType<_DayHeader>()
      .map((h) => h.dateKey)
      .toList();

  void _showBulkTagDialog(BuildContext context, ProjectNotifier notifier) {
    showDialog<void>(
      context: context,
      useRootNavigator: true,
      builder: (_) => _BulkTagDialog(
        notifier: notifier,
        selectedDays: Set.of(_selectedDays),
      ),
    );
  }

  String? _lastTripStart;

  List<Object> _buildDisplayList(
    List<Map<String, dynamic>> items,
    Map<dynamic, Map<String, dynamic>> activityById,
    String? tripStartOverride,
  ) {
    if (items.isEmpty) return [];

    // Assign each item a date ("YYYY-MM-DD"), propagating forward.
    final itemDates = <String?>[];
    String? lastDate;
    for (final item in items) {
      String? d;
      if (item['item_type'] == 'activity') {
        final a = activityById[item['activity_id']];
        final ds = a?['start_date_local'] as String?;
        d = ds?.split('T').first;
        if (d != null) lastDate = d;
      } else if (item['item_type'] == 'memory') {
        d = item['memory']?['date'] as String? ?? lastDate;
      } else {
        d = item['segment']?['date'] as String? ?? lastDate;
      }
      itemDates.add(d);
    }

    // Determine trip start: use override if set, else earliest date in items.
    final allDates = itemDates.whereType<String>().toSet().toList()..sort();
    if (allDates.isEmpty) {
      return [for (int i = 0; i < items.length; i++) _PanelItem(i, items[i], null)];
    }
    final tripStartStr = tripStartOverride ?? allDates.first;
    final ts = DateTime.parse(tripStartStr);
    // Use UTC dates for the day-number difference so DST transitions don't
    // shorten a "day" to 23 hours and cause an off-by-one.
    final tripStartDate = DateTime.utc(ts.year, ts.month, ts.day);

    // Sort unique date keys ascending, then build display list in that order.
    final sortedDates = allDates.toList(); // already sorted ascending

    // Build a map from dateKey → list of (originalIndex, item) pairs.
    final byDate = <String, List<(int, Map<String, dynamic>)>>{};
    final undated = <(int, Map<String, dynamic>)>[];
    for (int i = 0; i < items.length; i++) {
      final dk = itemDates[i];
      if (dk == null) {
        undated.add((i, items[i]));
      } else {
        byDate.putIfAbsent(dk, () => []).add((i, items[i]));
      }
    }

    final result = <Object>[];
    for (final dk in sortedDates) {
      final d = DateTime.parse(dk);
      final groupDate = DateTime.utc(d.year, d.month, d.day);
      final dayNum = groupDate.difference(tripStartDate).inDays + 1;
      result.add(_DayHeader(dayNum, d, dk));
      if (!_collapsedDays.contains(dayNum)) {
        for (final (int idx, Map<String, dynamic> item) in byDate[dk] ?? []) {
          result.add(_PanelItem(idx, item, dk));
        }
      }
    }
    // Undated items always appear at the end, uncollapsible.
    for (final (int idx, Map<String, dynamic> item) in undated) {
      result.add(_PanelItem(idx, item, null));
    }
    return result;
  }

  @override
  void initState() {
    super.initState();
    _refreshActivityById(widget.notifier.activities);
    _rebuildDisplayList(widget.notifier.items, widget.notifier.tripStart);
  }

  @override
  void didUpdateWidget(ActivityPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    _refreshActivityById(widget.notifier.activities);
    _rebuildDisplayList(widget.notifier.items, widget.notifier.tripStart);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final theme = Theme.of(context);
    _segmentTitleStyle =
        theme.textTheme.bodyMedium?.copyWith(fontStyle: FontStyle.italic);
  }

  static IconData _iconForActivityType(String? type) {
    switch (type?.toLowerCase()) {
      case 'run':
        return Icons.directions_run;
      case 'ride':
        return Icons.directions_bike;
      case 'hike':
        return Icons.hiking;
      default:
        return Icons.map;
    }
  }

  static IconData _iconForSegmentType(String? type) {
    switch (type?.toLowerCase()) {
      case 'flight':
        return Icons.flight;
      case 'train':
        return Icons.train;
      case 'bus':
        return Icons.directions_bus;
      case 'boat':
        return Icons.directions_boat;
      default:
        return Icons.route;
    }
  }

  static String _formatDuration(dynamic seconds) {
    if (seconds == null) return '--';
    final total = (seconds as num).toInt();
    final h = total ~/ 3600;
    final m = (total % 3600) ~/ 60;
    if (h > 0) return '${h}h ${m}m';
    return '${m}m';
  }

  static String _fmtMemDate(String date, String? time) {
    final d = DateTime.tryParse(date);
    if (d == null) return date;
    final part = '${_months[d.month - 1]} ${d.day}';
    return time == null ? part : '$part · $time';
  }

  void _dismissWithUndo({
    required BuildContext context,
    required ProjectNotifier notifier,
    required String label,
    required Future<void> Function() onConfirm,
  }) {
    final messenger = ScaffoldMessenger.of(context);
    messenger.clearSnackBars();
    final controller = messenger.showSnackBar(SnackBar(
      content: Text(label),
      duration: const Duration(seconds: 5),
      action: SnackBarAction(
        label: 'Undo',
        onPressed: () {
          final name = notifier.projectName;
          if (name != null) notifier.load(name);
        },
      ),
    ));
    controller.closed.then((reason) {
      if (reason != SnackBarClosedReason.action) {
        onConfirm();
      }
    });
  }

  void _flyToActivity(Map<String, dynamic> activity) {
    // Highlight the tapped activity on the map (toggle if already selected).
    widget.notifier.selectActivity(activity['id']);
    final raw = activity['start_latlng'];
    if (raw is! List || raw.length < 2) return;
    final target = LatLng((raw[0] as num).toDouble(), (raw[1] as num).toDouble());
    final mc = widget.mapController;
    if (mc == null) return;
    if (!mc.camera.visibleBounds.contains(target)) {
      mc.move(target, mc.camera.zoom.clamp(10.0, 15.0));
    }
  }

  void _flyToSegment(Map<String, dynamic> seg) {
    widget.notifier.selectSegment(seg['id']);
    final start = seg['start'] as Map?;
    final end   = seg['end']   as Map?;
    if (start == null || end == null) return;
    final lat = ((start['lat'] as num? ?? 0) + (end['lat'] as num? ?? 0)) / 2;
    final lon = ((start['lon'] as num? ?? 0) + (end['lon'] as num? ?? 0)) / 2;
    final target = LatLng(lat, lon);
    final mc = widget.mapController;
    if (mc == null) return;
    if (!mc.camera.visibleBounds.contains(target)) {
      mc.move(target, mc.camera.zoom.clamp(4.0, 10.0));
    }
  }

  void _flyToMemory(Map<String, dynamic> mem) {
    widget.notifier.selectMemory(mem['id']);
    final lat = (mem['lat'] as num?)?.toDouble();
    final lon = (mem['lon'] as num?)?.toDouble();
    if (lat != null && lon != null) {
      final target = LatLng(lat, lon);
      final mc = widget.mapController;
      if (mc != null && !mc.camera.visibleBounds.contains(target)) {
        mc.move(target, mc.camera.zoom.clamp(8.0, 15.0));
      }
    }
    showMemoryDetail(context, widget.notifier, mem);
  }

  int? _lastOriginalIndexForDay(String dateKey) {
    int? last;
    for (final e in _displayList) {
      if (e is _PanelItem && e.dateKey == dateKey) last = e.originalIndex;
    }
    return last;
  }

  List<Object> _applyTagFilter(
    List<Object> list,
    Set<String> filter,
    Map<String, Map<String, dynamic>> dayMeta,
  ) {
    if (filter.isEmpty) return list;
    final result = <Object>[];
    bool include = false;
    for (final entry in list) {
      if (entry is _DayHeader) {
        final rawTags = dayMeta[entry.dateKey]?['tags'];
        final tags = rawTags is List ? rawTags.cast<String>().toSet() : const <String>{};
        include = tags.any((t) => filter.contains(t));
        if (include) result.add(entry);
      } else if (include) {
        result.add(entry);
      }
    }
    return result;
  }

  List<Object> _applyMemoriesFilter(List<Object> list) {
    // Build an uncollapsed version of the display list so collapsed days
    // don't hide their memory items from the filter.
    final uncollapsed = <Object>[];
    for (final entry in list) {
      if (entry is _DayHeader) {
        uncollapsed.add(entry);
        final dk = entry.dateKey;
        // Always include all items for this day regardless of collapse state.
        for (int i = 0; i < _lastItems!.length; i++) {
          final item = _lastItems![i];
          // Determine item date the same way _buildDisplayList does.
          String? d;
          if (item['item_type'] == 'activity') {
            final a = _activityById[item['activity_id']];
            d = (a?['start_date_local'] as String?)?.split('T').first;
          } else if (item['item_type'] == 'memory') {
            d = item['memory']?['date'] as String?;
          } else {
            d = item['segment']?['date'] as String?;
          }
          if (d == dk) uncollapsed.add(_PanelItem(i, item, dk));
        }
      }
    }

    final result = <Object>[];
    _DayHeader? pendingHeader;
    for (final entry in uncollapsed) {
      if (entry is _DayHeader) {
        pendingHeader = entry;
      } else if (entry is _PanelItem) {
        if (entry.item['item_type'] == 'memory') {
          if (pendingHeader != null) {
            result.add(pendingHeader);
            pendingHeader = null;
          }
          result.add(entry);
        }
      }
    }
    return result;
  }

  @override
  Widget build(BuildContext context) {
    final notifier = widget.notifier;
    final theme = Theme.of(context);
    final items = notifier.items;

    final activityById = _activityById;

    // Styles are pre-computed in didChangeDependencies() — no copyWith in build().

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // ── Header ────────────────────────────────────────────────────────────
        Container(
          padding: const EdgeInsets.fromLTRB(4, 2, 4, 2),
          decoration: BoxDecoration(
            border: Border(
              bottom: BorderSide(color: theme.dividerColor),
            ),
          ),
          child: Row(
            children: [
              if (_multiSelect) ...[
                IconButton(
                  icon: const Icon(Icons.close, size: 20),
                  tooltip: 'Exit multi-select',
                  visualDensity: VisualDensity.compact,
                  onPressed: _toggleMultiSelect,
                ),
                const SizedBox(width: 4),
                Text(
                  '${_selectedDays.length} day${_selectedDays.length == 1 ? '' : 's'}',
                  style: theme.textTheme.labelMedium,
                ),
                if (_selectedDays.isNotEmpty)
                  IconButton(
                    icon: const Icon(Icons.label_outlined, size: 20),
                    tooltip: 'Tag selected days',
                    visualDensity: VisualDensity.compact,
                    onPressed: () => _showBulkTagDialog(context, notifier),
                  ),
              ] else ...[
                IconButton(
                  icon: const Icon(Icons.unfold_less, size: 20),
                  tooltip: 'Collapse all',
                  visualDensity: VisualDensity.compact,
                  onPressed: () => setState(() {
                    _collapsedDays = {
                      for (final o in _displayList) if (o is _DayHeader) o.dayNumber
                    };
                    _lastItems = null;
                  }),
                ),
                IconButton(
                  icon: const Icon(Icons.unfold_more, size: 20),
                  tooltip: 'Expand all',
                  visualDensity: VisualDensity.compact,
                  onPressed: () => setState(() {
                    _collapsedDays = {};
                    _lastItems = null;
                  }),
                ),
              ],
              const Spacer(),
              IconButton(
                icon: Icon(
                  Icons.photo_library_outlined,
                  size: 20,
                  color: _memoriesOnly ? theme.colorScheme.primary : null,
                ),
                tooltip: _memoriesOnly ? 'Show all' : 'Memories only',
                visualDensity: VisualDensity.compact,
                onPressed: () => setState(() => _memoriesOnly = !_memoriesOnly),
              ),
            ],
          ),
        ),

        // ── Items list (activities + segments, reorderable, day-grouped) ────────
        Expanded(
          child: items.isEmpty && !notifier.isLoading
              ? Center(
                  child: Text(
                    notifier.error != null
                        ? 'Error: ${notifier.error}'
                        : 'No activities — use sync or import',
                    style: theme.textTheme.bodySmall,
                    textAlign: TextAlign.center,
                  ),
                )
              : Builder(builder: (context) {
                  // Rebuild display list if items changed.
                  _rebuildDisplayList(items, notifier.tripStart);
                  var displayList = _displayList;
                  final tagFilter = notifier.tagFilter;
                  if (tagFilter.isNotEmpty) {
                    displayList = _applyTagFilter(
                        displayList, tagFilter, notifier.dayMeta);
                  }
                  if (_memoriesOnly) {
                    displayList = _applyMemoriesFilter(displayList);
                  }
                  return ReorderableListView.builder(
                    scrollController: widget.scrollController,
                    buildDefaultDragHandles: false,
                    onReorder: (fromV, toV) {
                      final fromEntry = fromV < displayList.length
                          ? displayList[fromV] : null;
                      if (fromEntry is! _PanelItem) return;
                      final fromOrig = fromEntry.originalIndex;
                      final adjToV = toV > fromV ? toV - 1 : toV;
                      int origCount = 0;
                      int? toOrig;
                      for (int k = 0; k < displayList.length; k++) {
                        if (k == adjToV) { toOrig = origCount; break; }
                        if (displayList[k] is _PanelItem) origCount++;
                      }
                      toOrig ??= notifier.items.length - 1;
                      notifier.reorderItems(fromOrig, toOrig);
                    },
                    itemCount: displayList.length,
                    itemBuilder: (context, vi) {
                      final entry = displayList[vi];

                      // ── Day header ──────────────────────────────────────────
                      if (entry is _DayHeader) {
                        final h = entry;
                        final isCollapsed = _collapsedDays.contains(h.dayNumber);
                        final isMultiChecked = _selectedDays.contains(h.dateKey);
                        final isSingleSelected = !_multiSelect && _selectedDay == h.dateKey;
                        final isHighlighted = _multiSelect ? isMultiChecked : isSingleSelected;
                        final isWide = MediaQuery.of(context).size.width >= 720;
                        final isEditExpanded = !isWide && _expandedDayEdits.contains(h.dateKey);

                        Widget headerRow = InkWell(
                          key: isWide ? ValueKey('header_${h.dayNumber}') : null,
                          onTap: () {
                            if (!isWide) {
                              setState(() => _expandedDayEdits.remove(h.dateKey));
                            }
                            if (_multiSelect) {
                              _handleMultiSelectTap(h.dateKey);
                            } else {
                              final isCtrl =
                                  HardwareKeyboard.instance.isControlPressed ||
                                  HardwareKeyboard.instance.isMetaPressed;
                              final isShift =
                                  HardwareKeyboard.instance.isShiftPressed;
                              if (isShift && _selectedDay != null) {
                                // Range-select from the single-selected day
                                // into multi-select mode.
                                final anchor = _selectedDay!;
                                setState(() {
                                  _multiSelect = true;
                                  _selectedDay = null;
                                  _anchorDayKey = anchor;
                                  final keys = _orderedDayKeys();
                                  final a = keys.indexOf(anchor);
                                  final b = keys.indexOf(h.dateKey);
                                  if (a != -1 && b != -1) {
                                    final lo = a < b ? a : b;
                                    final hi = a < b ? b : a;
                                    _selectedDays
                                        .addAll(keys.sublist(lo, hi + 1));
                                  }
                                });
                                notifier
                                    .selectDays(Set.from(_selectedDays));
                              } else if (isCtrl) {
                                _enterMultiSelectWithDay(h.dateKey);
                              } else {
                                final newDay =
                                    isSingleSelected ? null : h.dateKey;
                                setState(() => _selectedDay = newDay);
                                notifier.selectDay(newDay);
                              }
                            }
                          },
                          onLongPress: () => _enterMultiSelectWithDay(h.dateKey),
                          child: Container(
                            decoration: BoxDecoration(
                              color: isHighlighted
                                  ? theme.colorScheme.primaryContainer
                                      .withValues(alpha: 0.4)
                                  : null,
                              border: (_multiSelect && isMultiChecked)
                                  ? Border(
                                      left: BorderSide(
                                        color: theme.colorScheme.primary,
                                        width: 3,
                                      ),
                                    )
                                  : null,
                            ),
                            padding: const EdgeInsets.fromLTRB(4, 2, 8, 0),
                            child: Row(children: [
                              IconButton(
                                icon: Icon(
                                  isCollapsed
                                      ? Icons.chevron_right
                                      : Icons.expand_more,
                                  size: 20,
                                ),
                                visualDensity: VisualDensity.compact,
                                onPressed: () => setState(() {
                                  if (isCollapsed) {
                                    _collapsedDays.remove(h.dayNumber);
                                  } else {
                                    _collapsedDays.add(h.dayNumber);
                                  }
                                  _lastItems = null;
                                }),
                              ),
                              Text(
                                'Day ${h.dayNumber} · ${_fmtGroupDate(h.date)}',
                                style: theme.textTheme.labelMedium?.copyWith(
                                  color: isHighlighted
                                      ? theme.colorScheme.primary
                                      : theme.colorScheme.onSurfaceVariant,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                              // Tag badges
                              ...() {
                                final rawTags = notifier.dayMeta[h.dateKey]?['tags'];
                                final tags = rawTags is List
                                    ? rawTags.cast<String>()
                                    : <String>[];
                                return [
                                  for (final tag in tags)
                                    Padding(
                                      padding: const EdgeInsets.only(left: 4),
                                      child: Container(
                                        padding: const EdgeInsets.symmetric(
                                            horizontal: 4, vertical: 1),
                                        decoration: BoxDecoration(
                                          color: theme.colorScheme
                                              .secondaryContainer,
                                          borderRadius:
                                              BorderRadius.circular(4),
                                        ),
                                        child: Text(
                                          tag,
                                          style: theme.textTheme.labelSmall
                                              ?.copyWith(
                                            fontSize: 9,
                                            height: 1.1,
                                            color: theme.colorScheme
                                                .onSecondaryContainer,
                                          ),
                                        ),
                                      ),
                                    ),
                                ];
                              }(),
                              const Spacer(),
                              if (isWide)
                                IconButton(
                                  icon: const Icon(Icons.edit_outlined, size: 16),
                                  tooltip: 'Edit day',
                                  visualDensity: VisualDensity.compact,
                                  onPressed: () => showDayMetaDialog(context, notifier, h.dateKey),
                                ),
                              IconButton(
                                icon: const Icon(
                                    Icons.add_photo_alternate_outlined,
                                    size: 16),
                                tooltip: 'Add memory',
                                visualDensity: VisualDensity.compact,
                                onPressed: () => showDialog(
                                  context: context,
                                  useRootNavigator: true,
                                  builder: (_) => MemoryDialog(
                                    notifier: notifier,
                                    initialDate: h.dateKey,
                                    insertAfterIndex:
                                        _lastOriginalIndexForDay(h.dateKey),
                                  ),
                                ),
                              ),
                            ]),
                          ),
                        );

                        if (!isWide) {
                          headerRow = GestureDetector(
                            key: ValueKey('header_${h.dayNumber}'),
                            onHorizontalDragEnd: (details) {
                              if ((details.primaryVelocity ?? 0) > 0) {
                                setState(() {
                                  if (isEditExpanded) {
                                    _expandedDayEdits.remove(h.dateKey);
                                  } else {
                                    _expandedDayEdits.add(h.dateKey);
                                  }
                                });
                              }
                            },
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                headerRow,
                                AnimatedContainer(
                                  duration: const Duration(milliseconds: 200),
                                  curve: Curves.easeOut,
                                  height: isEditExpanded ? 40.0 : 0.0,
                                  clipBehavior: Clip.hardEdge,
                                  decoration: const BoxDecoration(),
                                  child: Row(
                                    mainAxisAlignment: MainAxisAlignment.end,
                                    children: [
                                      TextButton.icon(
                                        icon: const Icon(Icons.edit_outlined, size: 16),
                                        label: const Text('Edit day'),
                                        onPressed: () {
                                          setState(() => _expandedDayEdits.remove(h.dateKey));
                                          showDayMetaSheet(context, notifier, h.dateKey);
                                        },
                                      ),
                                      const SizedBox(width: 8),
                                    ],
                                  ),
                                ),
                              ],
                            ),
                          );
                        }

                        return headerRow;
                      }

                      // ── Activity or segment item ─────────────────────────────
                      final panelItem = entry as _PanelItem;
                      final i = panelItem.originalIndex;
                      final item = panelItem.item;
                      final isActivity = item['item_type'] == 'activity';
                      final dragHandle = ReorderableDragStartListener(
                        index: vi,
                        child: const Icon(Icons.drag_handle,
                            size: 18, color: Colors.grey),
                      );

                      if (isActivity) {
                        final a = activityById[item['activity_id']];
                        if (a == null) {
                          return Dismissible(
                            key: ValueKey('act_${item['activity_id']}'),
                            direction: DismissDirection.endToStart,
                            onDismissed: (_) => _dismissWithUndo(
                              context: context,
                              notifier: notifier,
                              label: 'Activity removed',
                              onConfirm: () => notifier.removeItem(i),
                            ),
                            background: Container(
                              color: theme.colorScheme.error,
                              alignment: Alignment.centerRight,
                              padding: const EdgeInsets.only(right: 20),
                              child: Icon(Icons.delete_outline,
                                  color: theme.colorScheme.onError),
                            ),
                            child: ListTile(
                              leading: dragHandle,
                              title: const Text('Unknown activity'),
                              trailing: const Icon(Icons.help_outline),
                            ),
                          );
                        }
                        final type = a['type'] as String?;
                        final name = a['name'] as String? ?? 'Activity';
                        final distM = (a['distance'] as num? ?? 0).toDouble();
                        final movingSec = a['moving_time'];
                        final activityId = item['activity_id'];
                        return Dismissible(
                          key: ValueKey('act_$activityId'),
                          direction: DismissDirection.endToStart,
                          onDismissed: (_) => _dismissWithUndo(
                            context: context,
                            notifier: notifier,
                            label: 'Removed "$name"',
                            onConfirm: () => notifier.removeItem(i),
                          ),
                          background: Container(
                            color: theme.colorScheme.error,
                            alignment: Alignment.centerRight,
                            padding: const EdgeInsets.only(right: 20),
                            child: Icon(Icons.delete_outline,
                                color: theme.colorScheme.onError),
                          ),
                          child: Selector<ProjectNotifier, bool>(
                            selector: (_, n) =>
                                activityId?.toString() ==
                                n.selectedActivityId?.toString(),
                            builder: (_, isSelected, __) => ListTile(
                              tileColor: isSelected
                                  ? theme.colorScheme.primaryContainer
                                      .withValues(alpha: 0.45)
                                  : null,
                              leading: dragHandle,
                              title: Row(children: [
                                Icon(
                                  _iconForActivityType(type),
                                  size: 16,
                                  color: isSelected
                                      ? theme.colorScheme.primary
                                      : theme.colorScheme.primary
                                          .withValues(alpha: 0.7),
                                ),
                                const SizedBox(width: 8),
                                Flexible(
                                  child: Text(name,
                                      style: theme.textTheme.bodyMedium),
                                ),
                              ]),
                              subtitle: Text(
                                '${(distM / 1000).toStringAsFixed(1)} km  •  ${_formatDuration(movingSec)}',
                                style: theme.textTheme.bodySmall,
                              ),
                              trailing: IconButton(
                                icon: const Icon(Icons.add_road, size: 18),
                                tooltip: 'Add connecting segment after',
                                onPressed: () => _showSegmentDialog(
                                  context,
                                  notifier,
                                  insertAfterIndex: i,
                                ),
                              ),
                              onTap: _multiSelect ? null : () => _flyToActivity(a),
                            ),
                          ),
                        );
                      } else if (item['item_type'] == 'memory') {
                        // Memory item
                        final mem =
                            item['memory'] as Map<String, dynamic>? ?? {};
                        final memId = mem['id']?.toString() ?? '';
                        final memName = mem['name'] as String?;
                        final memDate = mem['date'] as String?;
                        final memTime = mem['time'] as String?;
                        final memDesc = mem['description'] as String?;
                        final label = memName ??
                            (memDate != null
                                ? _fmtMemDate(memDate, memTime)
                                : 'Memory');
                        return Selector<ProjectNotifier, bool>(
                          key: ValueKey('mem_$memId'),
                          selector: (_, n) =>
                              n.selectedMemoryId?.toString() == memId,
                          builder: (_, isSelected, __) => ListTile(
                            dense: true,
                            tileColor: isSelected
                                ? theme.colorScheme.tertiaryContainer
                                    .withValues(alpha: 0.45)
                                : null,
                            leading: dragHandle,
                            title: Row(children: [
                              Icon(Icons.photo_camera_outlined,
                                  size: 16,
                                  color: isSelected
                                      ? theme.colorScheme.primary
                                      : theme.colorScheme.primary
                                          .withValues(alpha: 0.7)),
                              const SizedBox(width: 8),
                              Flexible(
                                  child: Text(label,
                                      style: theme.textTheme.bodyMedium)),
                            ]),
                            subtitle: memDesc != null && memDesc.isNotEmpty
                                ? Text(memDesc,
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: theme.textTheme.bodySmall)
                                : null,
                            trailing: IconButton(
                              icon: const Icon(Icons.edit_outlined, size: 18),
                              tooltip: 'Edit memory',
                              onPressed: () => showDialog(
                                context: context,
                                useRootNavigator: true,
                                builder: (_) => MemoryDialog(
                                    notifier: notifier, editMemory: mem),
                              ),
                            ),
                            onTap: _multiSelect ? null : () => _flyToMemory(mem),
                          ),
                        );
                      } else {
                        // Segment item
                        final seg =
                            item['segment'] as Map<String, dynamic>? ?? {};
                        final segId = seg['id'] as String? ?? '';
                        final segType = seg['segment_type'] as String?;
                        final label =
                            seg['label'] as String? ?? segType ?? 'Segment';
                        return Dismissible(
                          key: ValueKey('seg_$segId'),
                          direction: DismissDirection.endToStart,
                          onDismissed: (_) => _dismissWithUndo(
                            context: context,
                            notifier: notifier,
                            label: 'Removed "$label"',
                            onConfirm: () => notifier.deleteSegment(segId),
                          ),
                          background: Container(
                            color: theme.colorScheme.error,
                            alignment: Alignment.centerRight,
                            padding: const EdgeInsets.only(right: 20),
                            child: Icon(Icons.delete_outline,
                                color: theme.colorScheme.onError),
                          ),
                          child: Selector<ProjectNotifier, bool>(
                            selector: (_, n) =>
                                n.selectedSegmentId?.toString() == segId,
                            builder: (_, isSelected, __) => ListTile(
                              tileColor: isSelected
                                  ? theme.colorScheme.secondaryContainer
                                      .withValues(alpha: 0.45)
                                  : null,
                              leading: dragHandle,
                              title: Row(children: [
                                Icon(
                                  _iconForSegmentType(segType),
                                  size: 16,
                                  color: isSelected
                                      ? theme.colorScheme.secondary
                                      : theme.colorScheme.secondary
                                          .withValues(alpha: 0.7),
                                ),
                                const SizedBox(width: 8),
                                Flexible(
                                  child: Text(label,
                                      style: _segmentTitleStyle),
                                ),
                              ]),
                              subtitle: Text(segType ?? '',
                                  style: theme.textTheme.bodySmall),
                              trailing: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  IconButton(
                                    icon: const Icon(Icons.edit_outlined,
                                        size: 18),
                                    tooltip: 'Edit segment',
                                    onPressed: () => _showSegmentDialog(
                                      context,
                                      notifier,
                                      editSegment: seg,
                                      insertAfterIndex: null,
                                    ),
                                  ),
                                  IconButton(
                                    icon: const Icon(Icons.add_road, size: 18),
                                    tooltip: 'Add connecting segment after',
                                    onPressed: () => _showSegmentDialog(
                                      context,
                                      notifier,
                                      insertAfterIndex: i,
                                    ),
                                  ),
                                ],
                              ),
                              onTap: _multiSelect ? null : () => _flyToSegment(seg),
                            ),
                          ),
                        );
                      }
                    },
                  );
                }),
        ),

        // ── Footer buttons ────────────────────────────────────────────────────
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 4),
          child: Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  icon: const Icon(Icons.add, size: 16),
                  label: const Text('Add segment'),
                  onPressed: () => _showSegmentDialog(
                    context,
                    notifier,
                    insertAfterIndex: items.isNotEmpty ? items.length - 1 : null,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: OutlinedButton.icon(
                  icon: const Icon(Icons.add_photo_alternate_outlined, size: 16),
                  label: const Text('Add memory'),
                  onPressed: () => showDialog(
                    context: context,
                    useRootNavigator: true,
                    builder: (_) => MemoryDialog(notifier: notifier),
                  ),
                ),
              ),
            ],
          ),
        ),

      ],
    );
  }
}

Future<void> _showSegmentDialog(
  BuildContext context,
  ProjectNotifier notifier, {
  Map<String, dynamic>? editSegment,
  int? insertAfterIndex,
}) async {
  await showDialog<void>(
    context: context,
    builder: (ctx) => SegmentDialog(
      notifier: notifier,
      editSegment: editSegment,
      insertAfterIndex: insertAfterIndex,
    ),
  );
}

// ── _Stage1MapPanel — bare TileLayer, no controller, no polylines ─────────────

class _Stage1MapPanel extends StatefulWidget {
  final ProjectNotifier notifier;
  final MapController mapController;
  final bool autoZoom;
  final String basemapUrl;
  final List<String> basemapSubdomains;
  final ValueNotifier<bool> fittedNotifier;

  const _Stage1MapPanel({
    super.key,
    required this.notifier,
    required this.mapController,
    required this.basemapUrl,
    required this.fittedNotifier,
    this.autoZoom = false,
    this.basemapSubdomains = const [],
  });

  @override
  State<_Stage1MapPanel> createState() => _Stage1MapPanelState();
}

class _Stage1MapPanelState extends State<_Stage1MapPanel> {
  late final NetworkTileProvider _tileProvider;

  // Polyline + marker cache — only rebuilt when geo or selection changes.
  Map<String, dynamic>? _lastGeo;
  dynamic _lastSelectedId = _sentinel;
  dynamic _lastSelectedSegId = _sentinel;
  String? _lastSelectedDay = '';   // '' = sentinel (distinct from null)
  Set<String> _lastSelectedDays = const {};
  dynamic _lastSelectedMemId = _sentinel;
  List<Map<String, dynamic>>? _lastItems;
  List<Polyline> _cachedPolylines = [];
  List<Marker> _cachedSegmentMarkers = [];
  List<Marker> _cachedMemoryMarkers = [];

  static const _sentinel = Object();

  static bool _setEquals(Set<String> a, Set<String> b) =>
      a.length == b.length && a.containsAll(b);

  static IconData _iconForSegmentType(String? type) {
    switch (type?.toLowerCase()) {
      case 'flight': return Icons.flight;
      case 'train':  return Icons.train;
      case 'bus':    return Icons.directions_bus;
      case 'boat':   return Icons.directions_boat;
      default:       return Icons.route;
    }
  }

  List<Marker> _buildSegmentMarkers(
    Map<String, dynamic> geo,
    dynamic selectedSegmentId,
    bool hasSelection,
  ) {
    final features = geo['features'];
    if (features is! List) return [];
    final markers = <Marker>[];
    for (final feature in features) {
      if (feature is! Map) continue;
      final props = feature['properties'] as Map? ?? {};
      if (props['type'] != 'segment') continue;
      final coords = (feature['geometry'] as Map? ?? {})['coordinates'];
      if (coords is! List || coords.isEmpty) continue;

      final mid = coords[coords.length ~/ 2];
      if (mid is! List || mid.length < 2) continue;
      final point = LatLng((mid[1] as num).toDouble(), (mid[0] as num).toDouble());

      final segId = props['segment_id']?.toString();
      final isSelected = selectedSegmentId != null &&
          segId == selectedSegmentId.toString();

      final bgColor = isSelected
          ? const Color(0xFF44AAFF)
          : hasSelection
              ? const Color(0x60888888)
              : const Color(0xFF888888);

      markers.add(Marker(
        point: point,
        width: 22,
        height: 22,
        child: Container(
          decoration: BoxDecoration(color: bgColor, shape: BoxShape.circle),
          child: Icon(
            _iconForSegmentType(props['segment_type'] as String?),
            color: Colors.white,
            size: 13,
          ),
        ),
      ));
    }
    return markers;
  }

  List<Marker> _buildMemoryMarkers(
    List<Map<String, dynamic>> items,
    dynamic selectedMemoryId,
    bool hasSelection,
    BuildContext context,
  ) {
    final markers = <Marker>[];
    final authHeaders = api.tokenForUpload != null
        ? {'Authorization': 'Bearer ${api.tokenForUpload}'}
        : <String, String>{};
    for (final item in items) {
      if (item['item_type'] != 'memory') continue;
      final mem = item['memory'] as Map<String, dynamic>?;
      if (mem == null) continue;
      final lat = (mem['lat'] as num?)?.toDouble();
      final lon = (mem['lon'] as num?)?.toDouble();
      if (lat == null || lon == null) continue;
      final memId = mem['id']?.toString() ?? '';
      final photos = (mem['photos'] as List?)?.cast<String>() ?? [];
      final isSelected = selectedMemoryId?.toString() == memId;
      final size = isSelected ? 34.0 : 28.0;
      final bgColor = isSelected
          ? const Color(0xFFEA580C)
          : hasSelection
              ? const Color(0xA0F97316)
              : const Color(0xFFF97316);

      Widget inner;
      if (photos.isNotEmpty) {
        final thumbUrl =
            '${api.baseUrl}/api/memories/$memId/photos/${photos.first}/thumb';
        inner = ClipOval(
          child: Image.network(
            thumbUrl,
            width: size,
            height: size,
            fit: BoxFit.cover,
            headers: authHeaders,
            errorBuilder: (_, __, ___) => Icon(Icons.photo_camera,
                size: size * 0.45, color: Colors.white),
          ),
        );
      } else {
        inner = Icon(Icons.photo_camera, size: size * 0.45, color: Colors.white);
      }

      markers.add(Marker(
        point: LatLng(lat, lon),
        width: size,
        height: size,
        child: GestureDetector(
          onTap: () {
            widget.notifier.selectMemory(mem['id']);
            showMemoryDetail(context, widget.notifier, mem);
          },
          child: Container(
            decoration: BoxDecoration(
              color: bgColor,
              shape: BoxShape.circle,
              border: isSelected
                  ? Border.all(color: Colors.white, width: 2)
                  : null,
            ),
            child: Center(child: inner),
          ),
        ),
      ));
    }
    return markers;
  }

  @override
  void initState() {
    super.initState();
    _tileProvider = NetworkTileProvider();
    // Initialise "last" selection state from the current notifier values so that
    // a spurious selectionChanged2=true (which resets the fit flag) is never
    // triggered when this state is (re)created while a fit has already happened.
    _lastSelectedId = widget.notifier.selectedActivityId;
    _lastSelectedSegId = widget.notifier.selectedSegmentId;
    _lastSelectedDay = widget.notifier.selectedDay;
    _lastSelectedDays = Set.from(widget.notifier.selectedDays);
    _lastSelectedMemId = widget.notifier.selectedMemoryId;
  }

  @override
  void dispose() {
    super.dispose();
  }

  void _fitBoundsOnce(List<LatLng> points) {
    if (widget.fittedNotifier.value || points.isEmpty) return;
    widget.fittedNotifier.value = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      double minLat = points.first.latitude, maxLat = points.first.latitude;
      double minLon = points.first.longitude, maxLon = points.first.longitude;
      for (final p in points) {
        if (p.latitude < minLat) minLat = p.latitude;
        if (p.latitude > maxLat) maxLat = p.latitude;
        if (p.longitude < minLon) minLon = p.longitude;
        if (p.longitude > maxLon) maxLon = p.longitude;
      }
      widget.mapController.fitCamera(
        CameraFit.bounds(
          bounds: LatLngBounds(LatLng(minLat, minLon), LatLng(maxLat, maxLon)),
          padding: const EdgeInsets.fromLTRB(32, 32, 32, 32 + 160),
        ),
      );
    });
  }

  void _onMapTap(LatLng latlng) {
    final track = widget.notifier.fullTrack;
    if (track.isEmpty) return;
    int nearest = 0;
    double minDist = double.infinity;
    for (int i = 0; i < track.length; i++) {
      final dLat = track[i].$2.latitude  - latlng.latitude;
      final dLon = track[i].$2.longitude - latlng.longitude;
      final d = dLat * dLat + dLon * dLon;
      if (d < minDist) { minDist = d; nearest = i; }
    }
    widget.notifier.elevationCursorNotifier.value = track[nearest].$2;
    widget.notifier.mapCursorDistNotifier.value   = track[nearest].$1;
  }

  /// Compute the set of activity_ids and segment_ids that belong to [dateKey].
  static ({Set<String> actIds, Set<String> segIds}) _dayItemIds(
    List<Map<String, dynamic>> items,
    Map<dynamic, Map<String, dynamic>> activityById,
    String dateKey,
  ) {
    final actIds = <String>{};
    final segIds = <String>{};
    String? lastDate;
    for (final item in items) {
      if (item['item_type'] == 'activity') {
        final a = activityById[item['activity_id']];
        final ds = (a?['start_date_local'] as String?)?.split('T').first;
        if (ds != null) lastDate = ds;
        if ((ds ?? lastDate) == dateKey) {
          final id = item['activity_id']?.toString();
          if (id != null) actIds.add(id);
        }
      } else {
        final ds = item['segment']?['date'] as String? ?? lastDate;
        if (ds == dateKey) {
          final id = item['segment']?['id']?.toString();
          if (id != null) segIds.add(id);
        }
      }
    }
    return (actIds: actIds, segIds: segIds);
  }

  List<LatLng> _extractSelectedPoints(
    Map<String, dynamic> geo,
    dynamic selActId,
    dynamic selSegId,
    Set<String>? dayActIds,
    Set<String>? daySegIds,
  ) {
    final points = <LatLng>[];
    final features = geo['features'];
    if (features is! List) return points;
    for (final feature in features) {
      if (feature is! Map) continue;
      final props = feature['properties'] as Map? ?? {};
      final isSegment = props['type'] == 'segment';
      final featureId = isSegment
          ? props['segment_id']?.toString()
          : props['activity_id']?.toString();
      final bool match;
      if (dayActIds != null || daySegIds != null) {
        match = isSegment
            ? (daySegIds?.contains(featureId) ?? false)
            : (dayActIds?.contains(featureId) ?? false);
      } else if (isSegment) {
        match = selSegId != null && featureId == selSegId.toString();
      } else {
        match = selActId != null && featureId == selActId.toString();
      }
      if (!match) continue;
      final coords = (feature['geometry'] as Map? ?? {})['coordinates'];
      if (coords is! List) continue;
      for (final c in coords) {
        if (c is List && c.length >= 2) {
          points.add(LatLng((c[1] as num).toDouble(), (c[0] as num).toDouble()));
        }
      }
    }
    return points;
  }

  List<Polyline> _buildPolylines(
    Map<String, dynamic> geo,
    dynamic selectedActivityId,
    dynamic selectedSegmentId,
    Set<String> effectiveDays,
    Map<dynamic, Map<String, dynamic>> activityById,
    List<Map<String, dynamic>> items,
  ) {
    final features = geo['features'];
    if (features is! List) return [];

    // For day selection, union ids across all selected days.
    Set<String>? dayActIds;
    Set<String>? daySegIds;
    if (effectiveDays.isNotEmpty) {
      dayActIds = {};
      daySegIds = {};
      for (final dk in effectiveDays) {
        final r = _dayItemIds(items, activityById, dk);
        dayActIds.addAll(r.actIds);
        daySegIds.addAll(r.segIds);
      }
    }

    final polylines = <Polyline>[];
    final hasSelection = selectedActivityId != null ||
        selectedSegmentId != null ||
        effectiveDays.isNotEmpty;
    for (final feature in features) {
      if (feature is! Map) continue;
      final props = feature['properties'] as Map? ?? {};
      final geometry = feature['geometry'] as Map? ?? {};
      final coords = geometry['coordinates'];
      if (coords is! List) continue;
      final points = <LatLng>[];
      for (final c in coords) {
        if (c is List && c.length >= 2) {
          points.add(LatLng((c[1] as num).toDouble(), (c[0] as num).toDouble()));
        }
      }
      if (points.isEmpty) continue;
      final isSegment = props['type'] == 'segment';
      final featureId = isSegment
          ? props['segment_id']?.toString()
          : props['activity_id']?.toString();

      final bool isHighlighted;
      if (effectiveDays.isNotEmpty) {
        isHighlighted = isSegment
            ? (daySegIds?.contains(featureId) ?? false)
            : (dayActIds?.contains(featureId) ?? false);
      } else if (isSegment) {
        isHighlighted = selectedSegmentId != null &&
            featureId == selectedSegmentId.toString();
      } else {
        isHighlighted = selectedActivityId != null &&
            featureId == selectedActivityId.toString();
      }

      final Color color;
      final double strokeWidth;
      if (isSegment) {
        if (isHighlighted) {
          color = const Color(0xFF44AAFF);
          strokeWidth = 4.0;
        } else if (hasSelection) {
          color = const Color(0x60888888);
          strokeWidth = 2.0;
        } else {
          color = const Color(0xFF888888);
          strokeWidth = 2.0;
        }
      } else {
        if (isHighlighted) {
          color = const Color(0xFFEF4444);
          strokeWidth = 5.0;
        } else if (hasSelection) {
          color = const Color(0x60F97316);
          strokeWidth = 2.5;
        } else {
          color = const Color(0xFFF97316);
          strokeWidth = 2.5;
        }
      }
      polylines.add(Polyline(points: points, color: color, strokeWidth: strokeWidth));
    }
    return polylines;
  }

  @override
  Widget build(BuildContext context) {
    final notifier = widget.notifier;
    final geo = notifier.geo;
    final selActId = notifier.selectedActivityId;
    final selSegId = notifier.selectedSegmentId;
    final selDay = notifier.selectedDay;
    final selDays = notifier.selectedDays;
    final selMemId = notifier.selectedMemoryId;
    final items = notifier.items;
    final selectionChanged2 = selActId != _lastSelectedId ||
        selSegId?.toString() != _lastSelectedSegId?.toString() ||
        selDay != _lastSelectedDay ||
        !_setEquals(selDays, _lastSelectedDays) ||
        selMemId?.toString() != (_lastSelectedMemId as dynamic)?.toString();
    if (!identical(geo, _lastGeo) || selectionChanged2 || !identical(items, _lastItems)) {
      if (selectionChanged2) widget.fittedNotifier.value = false;
      _lastGeo = geo;
      _lastSelectedId = selActId;
      _lastSelectedSegId = selSegId;
      _lastSelectedDay = selDay;
      _lastSelectedDays = Set.from(selDays);
      _lastSelectedMemId = selMemId;
      _lastItems = items;
      // Multi-select takes priority over single-day selection.
      final effectiveDays = selDays.isNotEmpty
          ? selDays
          : (selDay != null ? {selDay} : <String>{});
      // Build activityById for day-selection polyline colouring.
      final actById = <dynamic, Map<String, dynamic>>{
        for (final a in notifier.activities) a['id']: a
      };
      _cachedPolylines = geo != null
          ? _buildPolylines(geo, selActId, selSegId, effectiveDays, actById, items)
          : [];
      final hasSelection = selActId != null || selSegId != null ||
          effectiveDays.isNotEmpty || selMemId != null;
      _cachedSegmentMarkers = geo != null
          ? _buildSegmentMarkers(geo, selSegId, hasSelection)
          : [];
      _cachedMemoryMarkers =
          _buildMemoryMarkers(items, selMemId, hasSelection, context);

      // Auto-zoom to selection
      if (widget.autoZoom && geo != null &&
          (effectiveDays.isNotEmpty || selActId != null || selSegId != null)) {
        Set<String>? dayActIds;
        Set<String>? daySegIds;
        if (effectiveDays.isNotEmpty) {
          dayActIds = {};
          daySegIds = {};
          for (final dk in effectiveDays) {
            final r = _dayItemIds(items, actById, dk);
            dayActIds.addAll(r.actIds);
            daySegIds.addAll(r.segIds);
          }
        }
        final pts = _extractSelectedPoints(
            geo, selActId, selSegId, dayActIds, daySegIds);
        if (pts.isNotEmpty) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (!mounted) return;
            double minLat = pts.first.latitude, maxLat = pts.first.latitude;
            double minLon = pts.first.longitude, maxLon = pts.first.longitude;
            for (final p in pts) {
              if (p.latitude < minLat) minLat = p.latitude;
              if (p.latitude > maxLat) maxLat = p.latitude;
              if (p.longitude < minLon) minLon = p.longitude;
              if (p.longitude > maxLon) maxLon = p.longitude;
            }
            widget.mapController.fitCamera(
              CameraFit.bounds(
                bounds: LatLngBounds(
                    LatLng(minLat, minLon), LatLng(maxLat, maxLon)),
                padding: const EdgeInsets.fromLTRB(48, 48, 48, 48 + 160),
              ),
            );
          });
        }
      }
    }

    if (!notifier.isLoading) {
      _fitBoundsOnce(_cachedPolylines.expand((p) => p.points).toList());
    }

    return Stack(
      children: [
        FlutterMap(
          mapController: widget.mapController,
          options: MapOptions(
            initialCenter: const LatLng(48.0, 10.0),
            initialZoom: 4,
            interactionOptions: const InteractionOptions(
              flags: InteractiveFlag.all & ~InteractiveFlag.rotate,
            ),
            onTap: (_, latlng) => _onMapTap(latlng),
          ),
          children: [
            TileLayer(
              urlTemplate: widget.basemapUrl,
              subdomains: widget.basemapSubdomains,
              userAgentPackageName: 'com.viewtrip.client',
              tileProvider: _tileProvider,
              maxNativeZoom: 22,
            ),
            if (_cachedPolylines.isNotEmpty)
              PolylineLayer(
                polylines: _cachedPolylines,
                simplificationTolerance: 0.5,
              ),
            if (_cachedSegmentMarkers.isNotEmpty)
              MarkerLayer(markers: _cachedSegmentMarkers),
            if (_cachedMemoryMarkers.isNotEmpty)
              MarkerLayer(markers: _cachedMemoryMarkers),
            ValueListenableBuilder<List<LatLng>?>(
              valueListenable: notifier.previewArcNotifier,
              builder: (_, arc, __) {
                if (arc == null) return const SizedBox.shrink();
                return PolylineLayer(
                  polylines: [
                    Polyline(
                      points: arc,
                      color: const Color(0xCC6366F1),
                      strokeWidth: 2.5,
                    ),
                  ],
                );
              },
            ),
            ValueListenableBuilder<LatLng?>(
              valueListenable: notifier.elevationCursorNotifier,
              builder: (_, cursor, __) {
                if (cursor == null) return const SizedBox.shrink();
                return MarkerLayer(
                  markers: [
                    Marker(
                      point: cursor,
                      width: 16,
                      height: 16,
                      child: Container(
                        decoration: BoxDecoration(
                          color: const Color(0xFFF97316),
                          shape: BoxShape.circle,
                          border: Border.all(color: Colors.white, width: 2),
                        ),
                      ),
                    ),
                  ],
                );
              },
            ),
          ],
        ),
        if (notifier.isLoading)
          const Center(child: CircularProgressIndicator()),
      ],
    );
  }
}

// ── ElevationChart ────────────────────────────────────────────────────────────

class ElevationChart extends StatefulWidget {
  final List<Map<String, dynamic>> activities;
  final dynamic selectedActivityId;

  /// Called with the map position under the chart cursor, or null when the
  /// user lifts / exits. Drives the elevation cursor marker on the map.
  final void Function(LatLng?)? onCursorChanged;

  /// Driven by map taps — shows a vertical line at this distance (km).
  final ValueNotifier<double?>? mapCursorNotifier;

  /// Pre-built distance-indexed track (cumulative km → LatLng).
  /// Built by ProjectNotifier from GeoJSON so Flutter never needs to decode
  /// the polyline.  Pass fullTrack when no activity is selected, or the
  /// per-activity track (0-based distances) when one is selected.
  final List<(double, LatLng)> track;

  const ElevationChart({
    super.key,
    required this.activities,
    required this.track,
    this.selectedActivityId,
    this.onCursorChanged,
    this.mapCursorNotifier,
  });

  @override
  State<ElevationChart> createState() => _ElevationChartState();
}

class _ElevationChartState extends State<ElevationChart> {
  List<FlSpot> _spots = const [];
  double _minY = 0;
  double _maxY = 0;


  @override
  void initState() {
    super.initState();
    _compute(widget.activities, widget.selectedActivityId);
    widget.mapCursorNotifier?.addListener(_onMapCursor);
  }

  @override
  void didUpdateWidget(ElevationChart oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.mapCursorNotifier != widget.mapCursorNotifier) {
      oldWidget.mapCursorNotifier?.removeListener(_onMapCursor);
      widget.mapCursorNotifier?.addListener(_onMapCursor);
    }
    if (!identical(oldWidget.activities, widget.activities) ||
        oldWidget.selectedActivityId?.toString() !=
            widget.selectedActivityId?.toString()) {
      _compute(widget.activities, widget.selectedActivityId);
    }
  }

  @override
  void dispose() {
    widget.mapCursorNotifier?.removeListener(_onMapCursor);
    super.dispose();
  }

  void _onMapCursor() => setState(() {});

  static Widget _elevLeftTitle(double value, TitleMeta meta) =>
      Text('${value.toInt()} m', style: const TextStyle(fontSize: 9));

  static Widget _elevBottomTitle(double value, TitleMeta meta) =>
      Text('${value.toStringAsFixed(0)} km',
          style: const TextStyle(fontSize: 9));

  void _compute(List<Map<String, dynamic>> activities, dynamic selectedId) {
    final source = selectedId == null
        ? activities
        : activities
            .where((a) => a['id']?.toString() == selectedId.toString())
            .toList();

    final spots = <FlSpot>[];
    double offsetKm = 0;
    for (final a in source) {
      final profile = a['elevation_profile'];
      if (profile is! List || profile.isEmpty) continue;
      final lastPt = profile.last;
      final elevTotalKm = (lastPt is List && lastPt.isNotEmpty)
          ? (lastPt[0] as num).toDouble()
          : 0.0;
      for (int i = 0; i < profile.length; i++) {
        final point = profile[i];
        if (point is! List || point.length < 2) continue;
        spots.add(FlSpot(
            (point[0] as num).toDouble() + offsetKm,
            (point[1] as num).toDouble()));
      }
      if (elevTotalKm > 0) offsetKm += elevTotalKm;
    }
    if (spots.isNotEmpty) {
      // Compute min/max over full data before downsampling — LTTB may not
      // select the global peak or valley, but the y-axis must contain them.
      double minY = spots.first.y, maxY = spots.first.y;
      for (final s in spots) {
        if (s.y < minY) minY = s.y;
        if (s.y > maxY) maxY = s.y;
      }
      _minY = minY;
      _maxY = maxY;
    }
    _spots = spots.length > _kMaxChartPoints ? _lttb(spots, _kMaxChartPoints) : spots;
  }

  /// Maximum number of FlSpot points rendered by fl_chart.
  /// LTTB downsampling preserves visual shape; cursor uses the full-resolution
  /// [widget.track] so accuracy is unaffected.
  static const _kMaxChartPoints = 300;

  /// Largest-Triangle-Three-Buckets downsampling.  O(n) — selects [threshold]
  /// points from [data] that best preserve the visual shape of the series.
  static List<FlSpot> _lttb(List<FlSpot> data, int threshold) {
    final n = data.length;
    assert(n > threshold);
    final out = <FlSpot>[data.first];
    int a = 0;
    final every = (n - 2) / (threshold - 2);
    for (int i = 0; i < threshold - 2; i++) {
      // Centroid of the next bucket — used as the "future" anchor.
      final nS = ((i + 1) * every + 1).floor();
      final nE = ((i + 2) * every + 1).floor().clamp(0, n);
      double avgX = 0, avgY = 0;
      for (int j = nS; j < nE; j++) { avgX += data[j].x; avgY += data[j].y; }
      final cnt = nE - nS;
      avgX /= cnt; avgY /= cnt;
      // Current bucket — pick the point that forms the largest triangle
      // with the previously selected point (a) and the next-bucket centroid.
      final cS = (i * every + 1).floor();
      final cE = ((i + 1) * every + 1).floor().clamp(0, n);
      final ax = data[a].x, ay = data[a].y;
      double maxArea = -1; int best = cS;
      for (int j = cS; j < cE; j++) {
        final area = ((ax - avgX) * (data[j].y - ay)
                    - (ax - data[j].x) * (avgY - ay)).abs();
        if (area > maxArea) { maxArea = area; best = j; }
      }
      out.add(data[best]);
      a = best;
    }
    out.add(data.last);
    return out;
  }

  void _onTouch(FlTouchEvent event, LineTouchResponse? response) {
    // Do NOT clear on FlPointerExitEvent — the cursor should persist at the
    // last hovered/clicked position so the user can inspect it after moving
    // the mouse off the chart.
    final spots = response?.lineBarSpots;
    if (spots == null || spots.isEmpty) return;
    final pos = latLonAtDistance(widget.track, spots.first.x);
    if (pos != null) widget.onCursorChanged?.call(pos);
  }

  @override
  Widget build(BuildContext context) {
    if (_spots.isEmpty) {
      return const SizedBox(
        height: 160,
        child: Center(child: Text('No elevation data')),
      );
    }

    final yPad = ((_maxY - _minY) * 0.1).clamp(10.0, double.infinity);

    return SizedBox(
      height: 160,
      child: LineChart(
        LineChartData(
          minY: _minY - yPad,
          maxY: _maxY + yPad,
          gridData: FlGridData(
            show: true,
            drawHorizontalLine: true,
            horizontalInterval: 100,
            drawVerticalLine: false,
            getDrawingHorizontalLine: (value) {
              return FlLine(
                color: Colors.grey.withOpacity(0.3),
                strokeWidth: 1,
                dashArray: [2, 2],
              );
            },
          ),
          borderData: FlBorderData(show: false),
          titlesData: FlTitlesData(
            leftTitles: AxisTitles(
              axisNameWidget: RotatedBox(
                quarterTurns: 0,
                child: Text(
                  'Elevation (m)',
                  style: Theme.of(context).textTheme.labelSmall,
                ),
              ),
              axisNameSize: 14,
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 40,
                getTitlesWidget: _elevLeftTitle,
              ),
            ),
            bottomTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 22,
                getTitlesWidget: _elevBottomTitle,
              ),
            ),
            topTitles: const AxisTitles(
                sideTitles: SideTitles(showTitles: false)),
            rightTitles: const AxisTitles(
                sideTitles: SideTitles(showTitles: false)),
          ),
          extraLinesData: () {
            final d = widget.mapCursorNotifier?.value;
            if (d == null) return null;
            return ExtraLinesData(verticalLines: [
              VerticalLine(
                x: d,
                color: const Color(0xFFF97316),
                strokeWidth: 1.5,
                dashArray: [4, 4],
              ),
            ]);
          }(),
          lineTouchData: LineTouchData(
            touchCallback: _onTouch,
            handleBuiltInTouches: true,
          ),
          lineBarsData: [
            LineChartBarData(
              spots: _spots,
              isCurved: true,
              color: const Color(0xFFF97316),
              barWidth: 2,
              dotData: const FlDotData(show: false),
              belowBarData: BarAreaData(
                show: true,
                color: const Color(0xFFF97316).withValues(alpha: 0.2),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ── _StatChip ─────────────────────────────────────────────────────────────────

// ── _MobileActivityPanelOverlay ───────────────────────────────────────────────
// Slide-in activity panel for narrow (mobile) layout. Rendered as a Material
// surface with elevation so it casts a shadow over the map behind it.

class _MobileActivityPanelOverlay extends StatelessWidget {
  final ProjectNotifier notifier;
  final MapController mapController;
  final double height;

  const _MobileActivityPanelOverlay({
    required this.notifier,
    required this.mapController,
    required this.height,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      elevation: 4,
      color: Theme.of(context).colorScheme.surface,
      child: SizedBox(
        width: 280,
        height: height,
        child: ActivityPanel(
          notifier: notifier,
          mapController: mapController,
        ),
      ),
    );
  }
}

// ── Bulk tag dialog ───────────────────────────────────────────────────────────

class _BulkTagDialog extends StatefulWidget {
  final ProjectNotifier notifier;
  final Set<String> selectedDays;
  const _BulkTagDialog({required this.notifier, required this.selectedDays});

  @override
  State<_BulkTagDialog> createState() => _BulkTagDialogState();
}

class _BulkTagDialogState extends State<_BulkTagDialog> {
  late Set<String> _chosenTags;
  final TextEditingController _inputCtrl = TextEditingController();

  @override
  void initState() {
    super.initState();
    _chosenTags = {};
  }

  @override
  void dispose() {
    _inputCtrl.dispose();
    super.dispose();
  }

  void _addNew(String tag) {
    final t = tag.trim();
    if (t.isEmpty) return;
    setState(() {
      _chosenTags.add(t);
      _inputCtrl.clear();
    });
  }

  void _apply() {
    if (_chosenTags.isEmpty) {
      Navigator.of(context).pop();
      return;
    }
    final updated = Map<String, Map<String, dynamic>>.from(widget.notifier.dayMeta);
    for (final dateKey in widget.selectedDays) {
      final existing = Map<String, dynamic>.from(updated[dateKey] ?? {});
      final existingTags = (existing['tags'] as List?)?.cast<String>().toSet() ?? <String>{};
      existing['tags'] = (existingTags..addAll(_chosenTags)).toList()..sort();
      updated[dateKey] = existing;
    }
    widget.notifier.saveDayMeta(newDayMeta: updated);
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    final allTags = {
      ...widget.notifier.availableTags,
      ..._chosenTags,
    }.toList()..sort();

    return AlertDialog(
      title: Text('Tag ${widget.selectedDays.length} day${widget.selectedDays.length == 1 ? '' : 's'}'),
      content: SizedBox(
        width: 400,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (allTags.isNotEmpty) ...[
                Text('Select tags to add:',
                    style: Theme.of(context).textTheme.labelMedium),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  runSpacing: 4,
                  children: [
                    for (final tag in allTags)
                      FilterChip(
                        label: Text(tag),
                        selected: _chosenTags.contains(tag),
                        onSelected: (on) => setState(() {
                          if (on) { _chosenTags.add(tag); } else { _chosenTags.remove(tag); }
                        }),
                      ),
                  ],
                ),
                const SizedBox(height: 12),
              ],
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _inputCtrl,
                      decoration: const InputDecoration(
                        isDense: true,
                        hintText: 'New tag…',
                        border: OutlineInputBorder(),
                        contentPadding:
                            EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                      ),
                      onSubmitted: _addNew,
                      textInputAction: TextInputAction.done,
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton.outlined(
                    icon: const Icon(Icons.add),
                    tooltip: 'Add tag',
                    onPressed: () => _addNew(_inputCtrl.text),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: _chosenTags.isEmpty ? null : _apply,
          child: const Text('Apply'),
        ),
      ],
    );
  }
}

// ── Tag filter sheet ─────────────────────────────────────────────────────────

class TagFilterSheet extends StatelessWidget {
  final ProjectNotifier notifier;
  final bool readOnly;

  const TagFilterSheet({super.key, required this.notifier, required this.readOnly});

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: notifier,
      builder: (context, _) {
        final theme = Theme.of(context);
        final tags = notifier.availableTags;
        final active = notifier.tagFilter;

        return Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Text('Filter by tag', style: theme.textTheme.titleMedium),
                  const Spacer(),
                  if (active.isNotEmpty)
                    TextButton(
                      onPressed: () {
                        notifier.setTagFilter({});
                        Navigator.of(context).pop();
                      },
                      child: const Text('Clear'),
                    ),
                ],
              ),
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  FilterChip(
                    label: const Text('All days'),
                    selected: active.isEmpty,
                    onSelected: (_) {
                      notifier.setTagFilter({});
                      Navigator.of(context).pop();
                    },
                  ),
                  for (final tag in tags)
                    FilterChip(
                      label: Text(tag),
                      selected: active.contains(tag),
                      onSelected: (on) {
                        final next = Set<String>.of(active);
                        if (on) { next.add(tag); } else { next.remove(tag); }
                        notifier.setTagFilter(next);
                      },
                    ),
                ],
              ),
            ],
          ),
        );
      },
    );
  }
}

// ── Image export ──────────────────────────────────────────────────────────────

class _ImageExportOptions {
  final bool includeChart;
  final bool includeTitle;
  const _ImageExportOptions({
    required this.includeChart,
    required this.includeTitle,
  });
}

class _ImageExportDialog extends StatefulWidget {
  final String projectName;
  final void Function(_ImageExportOptions) onExport;
  const _ImageExportDialog({required this.projectName, required this.onExport});
  @override
  State<_ImageExportDialog> createState() => _ImageExportDialogState();
}

class _ImageExportDialogState extends State<_ImageExportDialog> {
  bool _includeChart = true;
  bool _includeTitle = false;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Export image'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Canvas: 2400 × 1600 px',
              style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 12),
          CheckboxListTile(
            title: const Text('Include elevation chart'),
            value: _includeChart,
            onChanged: (v) => setState(() => _includeChart = v!),
            contentPadding: EdgeInsets.zero,
            dense: true,
          ),
          CheckboxListTile(
            title: const Text('Include project title'),
            value: _includeTitle,
            onChanged: (v) => setState(() => _includeTitle = v!),
            contentPadding: EdgeInsets.zero,
            dense: true,
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: () {
            final opts = _ImageExportOptions(
              includeChart: _includeChart,
              includeTitle: _includeTitle,
            );
            Navigator.of(context).pop();
            widget.onExport(opts);
          },
          child: const Text('Export PNG'),
        ),
      ],
    );
  }
}

