library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_map_animations/flutter_map_animations.dart';
import 'package:latlong2/latlong.dart';
import 'package:provider/provider.dart';

import '../core/design_tokens.dart';
import 'day_meta_editor.dart';
import 'journal_detail_modal.dart';
import 'journal_dialog.dart';
import 'memory_detail_modal.dart';
import 'memory_dialog.dart';
import 'project_notifier.dart';
import 'segment_dialog.dart';
// ── ActivityPanel ─────────────────────────────────────────────────────────────

class ActivityPanel extends StatefulWidget {
  final ProjectNotifier notifier;
  final AnimatedMapController? mapController;
  final ScrollController? scrollController;
  const ActivityPanel({
    super.key,
    required this.notifier,
    this.mapController,
    this.scrollController,
  });

  @override
  State<ActivityPanel> createState() => _ActivityPanelState();

  /// Effective day-bucket date for the segment [segIdStr], mirroring the forward
  /// date-propagation in `_buildDisplayList`: a dateless segment inherits the
  /// date of the most recent preceding *activity* (only activities advance the
  /// running date there). Returns null if the segment isn't found or nothing
  /// dated precedes it.
  ///
  /// Bucketing keys a dateless segment under this *inherited* date, while its
  /// raw `segment['date']` is null — so matching on the raw date (as the old
  /// reveal code did) never located the collapsed day it actually renders under,
  /// and a just-created segment stayed hidden.
  @visibleForTesting
  static String? effectiveSegmentDate(
    List<Map<String, dynamic>> items,
    Map<dynamic, Map<String, dynamic>> activityById,
    String segIdStr,
  ) {
    String? lastDate;
    for (final item in items) {
      final type = item['item_type'];
      if (type == 'activity') {
        final a = activityById[item['activity_id']];
        final d = (a?['start_date_local'] as String?)?.split('T').first;
        if (d != null) lastDate = d;
      } else if (type == 'segment' &&
          item['segment']?['id']?.toString() == segIdStr) {
        return item['segment']?['date'] as String? ?? lastDate;
      }
    }
    return null;
  }
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

class _ActivityIconBox extends StatelessWidget {
  final String? type;
  const _ActivityIconBox({this.type});

  static Color _color(String? t) => switch (t?.toLowerCase()) {
        'ride' || 'virtualride' || 'ebikeride' => kColorRide,
        'run' || 'virtualrun'                  => kColorRun,
        'hike' || 'walk'                       => kColorHike,
        _                                      => kColorAlt,
      };

  static IconData _icon(String? t) => switch (t?.toLowerCase()) {
        'run' || 'virtualrun'  => Icons.directions_run,
        'ride' || 'virtualride' || 'ebikeride' => Icons.directions_bike,
        'hike' || 'walk'       => Icons.hiking,
        _                      => Icons.map,
      };

  @override
  Widget build(BuildContext context) {
    final c = _color(type);
    final dark = Theme.of(context).brightness == Brightness.dark;
    return Container(
      width: 32,
      height: 32,
      decoration: BoxDecoration(
        color: iconBoxBg(c),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Icon(_icon(type), size: 17, color: iconBoxFg(c, dark: dark)),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────

class _ActivityPanelState extends State<ActivityPanel> {
  // activityById cache — rebuilt only when the activities list reference changes.
  List<Map<String, dynamic>>? _lastActivities;
  Map<dynamic, Map<String, dynamic>> _activityById = {};

  // Tracks the last selectedActivityId / selectedSegmentId we reacted to,
  // so we only auto-expand and scroll when a new selection arrives.
  String? _prevSelectedActivityIdStr;
  String? _prevSelectedSegmentIdStr;

  // Day grouping state
  Set<int> _collapsedDays = {};
  bool _sortDescending = true;
  String? _selectedDay; // "YYYY-MM-DD"

  // Multi-select state
  bool _multiSelect = false;
  final Set<String> _selectedDays = {};
  String? _anchorDayKey; // last day tapped without Shift — range-select anchor

  // Narrow-layout: day keys whose edit strip is revealed by swipe-right

  // Memories-only filter toggle
  bool _memoriesOnly = false;

  // Display list cache — rebuilt when items or activities change.
  List<Map<String, dynamic>>? _lastItems;
  List<Object> _displayList = [];
  bool _initialCollapseApplied = false;

  // Filtered display list cache — rebuilt only when base list, filter state,
  // or memories-only toggle actually changes.
  List<Object>? _cachedBaseList;
  List<Object>? _cachedFilteredList;
  Set<String>?  _lastSelectedDays;
  bool?         _lastHasFilter;
  bool?         _lastMemoriesOnly;
  bool?         _lastShowJournals;

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
    Map<String, Map<String, dynamic>> dayMeta,
  ) {
    if (identical(items, _lastItems) &&
        tripStartOverride == _lastTripStart &&
        identical(dayMeta, _lastDayMeta)) { return; }
    _lastItems = items;
    _lastTripStart = tripStartOverride;
    _lastDayMeta = dayMeta;
    _displayList = _buildDisplayList(items, _activityById, tripStartOverride, dayMeta);
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
      _displayList = _buildDisplayList(items, _activityById, tripStartOverride, dayMeta);
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
  Map<String, Map<String, dynamic>>? _lastDayMeta;

  List<Object> _buildDisplayList(
    List<Map<String, dynamic>> items,
    Map<dynamic, Map<String, dynamic>> activityById,
    String? tripStartOverride,
    Map<String, Map<String, dynamic>> dayMeta,
  ) {
    if (items.isEmpty && dayMeta.isEmpty) return [];

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
      } else if (item['item_type'] == 'journal') {
        d = item['journal']?['date'] as String? ?? lastDate;
      } else {
        d = item['segment']?['date'] as String? ?? lastDate;
      }
      itemDates.add(d);
    }

    // Determine trip start: use override if set, else earliest date in items/dayMeta.
    final allDates = {
      ...itemDates.whereType<String>(),
      ...dayMeta.keys,
    }.toList()..sort();
    if (allDates.isEmpty) {
      return [for (int i = 0; i < items.length; i++) _PanelItem(i, items[i], null)];
    }
    final tripStartStr = tripStartOverride ?? allDates.first;
    final ts = DateTime.parse(tripStartStr);
    // Use UTC dates for the day-number difference so DST transitions don't
    // shorten a "day" to 23 hours and cause an off-by-one.
    final tripStartDate = DateTime.utc(ts.year, ts.month, ts.day);

    final sortedDates = _sortDescending
        ? (allDates.toList()..sort((a, b) => b.compareTo(a)))
        : allDates.toList(); // ascending — already sorted

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
    _prevSelectedActivityIdStr = widget.notifier.selectedActivityId?.toString();
    _prevSelectedSegmentIdStr = widget.notifier.selectedSegmentId?.toString();
    widget.notifier.addListener(_onNotifierChanged);
    _refreshActivityById(widget.notifier.activities);
    _rebuildDisplayList(widget.notifier.items, widget.notifier.tripStart, widget.notifier.dayMeta);
  }

  @override
  void dispose() {
    widget.notifier.removeListener(_onNotifierChanged);
    super.dispose();
  }

  @override
  void didUpdateWidget(ActivityPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.notifier != widget.notifier) {
      oldWidget.notifier.removeListener(_onNotifierChanged);
      widget.notifier.addListener(_onNotifierChanged);
      _prevSelectedActivityIdStr = widget.notifier.selectedActivityId?.toString();
      _prevSelectedSegmentIdStr = widget.notifier.selectedSegmentId?.toString();
    }
    _refreshActivityById(widget.notifier.activities);
    _rebuildDisplayList(widget.notifier.items, widget.notifier.tripStart, widget.notifier.dayMeta);
  }

  void _onNotifierChanged() {
    final actId = widget.notifier.selectedActivityId?.toString();
    if (actId != _prevSelectedActivityIdStr) {
      _prevSelectedActivityIdStr = actId;
      if (actId != null) _expandAndScrollToActivity(actId);
    }
    final segId = widget.notifier.selectedSegmentId?.toString();
    if (segId != _prevSelectedSegmentIdStr) {
      _prevSelectedSegmentIdStr = segId;
      if (segId != null) _expandAndScrollToSegment(segId);
    }
  }

  void _expandAndScrollToActivity(String activityIdStr) {
    // Find which dateKey this activity belongs to.
    String? targetDateKey;
    if (_lastItems != null) {
      for (final item in _lastItems!) {
        if (item['item_type'] != 'activity') continue;
        if (item['activity_id']?.toString() != activityIdStr) continue;
        final a = _activityById[item['activity_id']];
        final ds = a?['start_date_local'] as String?;
        targetDateKey = ds?.split('T').first;
        break;
      }
    }

    // Find which dayNumber this dateKey maps to.
    int? targetDayNumber;
    if (targetDateKey != null) {
      for (final e in _displayList) {
        if (e is _DayHeader && e.dateKey == targetDateKey) {
          targetDayNumber = e.dayNumber;
          break;
        }
      }
    }

    // Expand the day if it's collapsed.
    if (targetDayNumber != null && _collapsedDays.contains(targetDayNumber)) {
      setState(() {
        _collapsedDays.remove(targetDayNumber);
        _lastItems = null; // force display list rebuild next frame
      });
    }

    // Scroll after the frame renders so the list is fully laid out.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _scrollToActivity(activityIdStr);
    });
  }

  void _scrollToActivity(String activityIdStr) {
    final sc = widget.scrollController;
    if (sc == null || !sc.hasClients) return;

    const double headerHeight = 40.0;
    const double itemHeight = 64.0;
    double offset = 0;
    final list = _cachedFilteredList ?? _displayList;
    for (final e in list) {
      if (e is _DayHeader) {
        offset += headerHeight;
      } else if (e is _PanelItem) {
        if (e.item['item_type'] == 'activity' &&
            e.item['activity_id']?.toString() == activityIdStr) {
          final center = offset + itemHeight / 2 - sc.position.viewportDimension / 2;
          sc.animateTo(
            center.clamp(0.0, sc.position.maxScrollExtent),
            duration: const Duration(milliseconds: 350),
            curve: Curves.easeOut,
          );
          return;
        }
        offset += itemHeight;
      }
    }
  }

  void _expandAndScrollToSegment(String segIdStr) {
    // This runs synchronously from the notifier listener — i.e. *before* the
    // panel rebuilds — so for a just-created segment _lastItems/_displayList are
    // still stale and don't contain it yet. Defer past the next frame so the
    // reveal sees the new item and the (collapsed) day it was bucketed into.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final items = _lastItems;
      final targetDateKey = items == null
          ? null
          : ActivityPanel.effectiveSegmentDate(items, _activityById, segIdStr);

      // DayHeaders are always in _displayList (even for collapsed days).
      if (targetDateKey != null) {
        int? targetDayNumber;
        for (final e in _displayList) {
          if (e is _DayHeader && e.dateKey == targetDateKey) {
            targetDayNumber = e.dayNumber;
            break;
          }
        }
        if (targetDayNumber != null && _collapsedDays.contains(targetDayNumber)) {
          setState(() {
            _collapsedDays.remove(targetDayNumber);
            _lastItems = null; // force display list rebuild so segment is visible
          });
        }
      }

      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _scrollToSegment(segIdStr);
      });
    });
  }

  void _scrollToSegment(String segIdStr) {
    final sc = widget.scrollController;
    if (sc == null || !sc.hasClients) return;

    const double headerHeight = 40.0;
    const double itemHeight = 64.0;
    double offset = 0;
    final list = _cachedFilteredList ?? _displayList;
    for (final e in list) {
      if (e is _DayHeader) {
        offset += headerHeight;
      } else if (e is _PanelItem) {
        if (e.item['item_type'] == 'segment' &&
            e.item['segment']?['id']?.toString() == segIdStr) {
          final center = offset + itemHeight / 2 - sc.position.viewportDimension / 2;
          sc.animateTo(
            center.clamp(0.0, sc.position.maxScrollExtent),
            duration: const Duration(milliseconds: 350),
            curve: Curves.easeOut,
          );
          return;
        }
        offset += itemHeight;
      }
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final theme = Theme.of(context);
    _segmentTitleStyle =
        theme.textTheme.labelSmall?.copyWith(fontStyle: FontStyle.italic);
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

  static const _segmentRouteModeForType = {
    'train': 'rail', 'boat': 'ferry', 'bus': 'bus',
  };

  /// Status line shown under a segment tile while its route resolves
  /// asynchronously, or a tap-to-retry affordance if it failed.
  /// Returns null when there is nothing to show (idle/resolved).
  Widget? _segmentStatusLine(
    BuildContext context,
    ProjectNotifier notifier,
    Map<String, dynamic> seg,
    String segId,
    String? segType,
    ThemeData theme,
  ) {
    final status = seg['route_status'] as String?;
    if (status == 'pending') {
      return Row(mainAxisSize: MainAxisSize.min, children: [
        const SizedBox(
          width: 11, height: 11,
          child: CircularProgressIndicator(strokeWidth: 1.6),
        ),
        const SizedBox(width: 6),
        Text('Resolving route…',
            style: theme.textTheme.labelSmall
                ?.copyWith(color: theme.colorScheme.primary)),
      ]);
    }
    if (status == 'failed') {
      final err = seg['route_error'] as String?;
      return InkWell(
        onTap: () => _retrySegmentResolve(context, notifier, seg, segId, segType),
        child: Tooltip(
          message: err == null || err.isEmpty ? 'Tap to retry' : err,
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.error_outline,
                size: 12, color: theme.colorScheme.error),
            const SizedBox(width: 4),
            Text('Route failed — tap to retry',
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: theme.colorScheme.error)),
          ]),
        ),
      );
    }
    return null;
  }

  void _retrySegmentResolve(
    BuildContext context,
    ProjectNotifier notifier,
    Map<String, dynamic> seg,
    String segId,
    String? segType,
  ) {
    final routeMode = _segmentRouteModeForType[segType] ??
        (seg['route_mode'] as String? ?? 'rail');
    final messenger = ScaffoldMessenger.of(context);
    messenger.showSnackBar(const SnackBar(
      content: Text('Retrying route resolution…'),
      duration: Duration(seconds: 3),
    ));
    () async {
      try {
        await notifier.resolveTrainRoute(
          segId,
          routeMode: routeMode,
          hafasProvider:
              routeMode == 'rail' ? seg['hafas_provider'] as String? : null,
          trainNumber:
              routeMode == 'rail' ? seg['train_number'] as String? : null,
          date: seg['date'] as String?,
        );
      } catch (_) {
        // Failure is reflected on the tile via route_status; no extra toast.
      }
    }();
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
    VoidCallback? onOptimistic,
  }) {
    onOptimistic?.call();
    final messenger = ScaffoldMessenger.of(context);
    messenger.clearSnackBars();

    // Track whether the user pressed Undo so the delayed confirm can skip.
    var undone = false;

    messenger.showSnackBar(SnackBar(
      content: Text(label),
      duration: const Duration(seconds: 5),
      action: SnackBarAction(
        label: 'Undo',
        onPressed: () {
          undone = true;
          final name = notifier.projectName;
          if (name != null) notifier.load(name);
        },
      ),
    ));

    // Use Future.delayed instead of controller.closed.then() — the closed
    // future can get orphaned after widget rebuilds triggered by
    // reloadDetailsOnly(), leaving the SnackBar stuck on screen indefinitely.
    // The extra 500 ms lets the natural auto-dismiss animation finish first;
    // clearSnackBars() is a no-op when the bar is already gone.
    Future.delayed(const Duration(milliseconds: 5500), () {
      if (undone) return;
      try {
        messenger.clearSnackBars();
      } catch (_) {}
      onConfirm();
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
    if (!mc.mapController.camera.visibleBounds.contains(target)) {
      mc.animateTo(
        dest: target,
        zoom: mc.mapController.camera.zoom.clamp(10.0, 15.0),
        duration: const Duration(milliseconds: 350),
        curve: Curves.easeOut,
      );
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
    if (!mc.mapController.camera.visibleBounds.contains(target)) {
      mc.animateTo(
        dest: target,
        zoom: mc.mapController.camera.zoom.clamp(4.0, 10.0),
        duration: const Duration(milliseconds: 350),
        curve: Curves.easeOut,
      );
    }
  }

  void _flyToMemory(Map<String, dynamic> mem) {
    widget.notifier.selectMemory(mem['id']);
    final lat = (mem['lat'] as num?)?.toDouble();
    final lon = (mem['lon'] as num?)?.toDouble();
    if (lat != null && lon != null) {
      final target = LatLng(lat, lon);
      final mc = widget.mapController;
      if (mc != null && !mc.mapController.camera.visibleBounds.contains(target)) {
        mc.animateTo(
          dest: target,
          zoom: mc.mapController.camera.zoom.clamp(8.0, 15.0),
          duration: const Duration(milliseconds: 350),
          curve: Curves.easeOut,
        );
      }
    }
    showMemoryDetail(context, widget.notifier, mem);
  }

  void _showAddItemSheet(
    BuildContext context,
    ProjectNotifier notifier, {
    String? initialDate,
    int? insertAfterIndex,
  }) {
    showModalBottomSheet<void>(
      context: context,
      useRootNavigator: true,
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.photo_camera_outlined),
              title: const Text('Memory'),
              onTap: () {
                Navigator.of(context).pop();
                showDialog<void>(
                  context: context,
                  useRootNavigator: true,
                  builder: (_) => MemoryDialog(
                    notifier: notifier,
                    initialDate: initialDate,
                    insertAfterIndex: insertAfterIndex,
                  ),
                );
              },
            ),
            ListTile(
              leading: const Icon(Icons.book_outlined),
              title: const Text('Journal entry'),
              onTap: () {
                Navigator.of(context).pop();
                showDialog<void>(
                  context: context,
                  useRootNavigator: true,
                  builder: (_) => JournalDialog(
                    notifier: notifier,
                    initialDate: initialDate,
                    insertAfterIndex: insertAfterIndex,
                  ),
                );
              },
            ),
            ListTile(
              leading: const Icon(Icons.route_outlined),
              title: const Text('Transportation'),
              onTap: () {
                Navigator.of(context).pop();
                _showSegmentDialog(
                  context,
                  notifier,
                  insertAfterIndex: insertAfterIndex,
                  preselectedStartActivityId: notifier.selectedActivityId,
                );
              },
            ),
          ],
        ),
      ),
    );
  }

  void _flyToJournal(Map<String, dynamic> jMap) {
    widget.notifier.selectJournal(jMap['id']);
    final lat = (jMap['lat'] as num?)?.toDouble();
    final lon = (jMap['lon'] as num?)?.toDouble();
    if (lat != null && lon != null) {
      final target = LatLng(lat, lon);
      final mc = widget.mapController;
      if (mc != null && !mc.mapController.camera.visibleBounds.contains(target)) {
        mc.animateTo(
          dest: target,
          zoom: mc.mapController.camera.zoom.clamp(8.0, 15.0),
          duration: const Duration(milliseconds: 350),
          curve: Curves.easeOut,
        );
      }
    }
  }

  List<Object> _removeJournals(List<Object> list) => [
    for (final e in list)
      if (e is _DayHeader || (e is _PanelItem && e.item['item_type'] != 'journal'))
        e,
  ];

  int? _lastOriginalIndexForDay(String dateKey) {
    int? last;
    for (final e in _displayList) {
      if (e is _PanelItem && e.dateKey == dateKey) last = e.originalIndex;
    }
    return last;
  }

  List<Object> _applyDayFilter(List<Object> list, Set<String> allowed) {
    final result = <Object>[];
    bool include = false;
    for (final entry in list) {
      if (entry is _DayHeader) {
        include = allowed.contains(entry.dateKey);
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
          } else if (item['item_type'] == 'journal') {
            d = item['journal']?['date'] as String?;
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
                IconButton(
                  icon: Icon(
                    _sortDescending
                        ? Icons.arrow_downward
                        : Icons.arrow_upward,
                    size: 20,
                  ),
                  tooltip: _sortDescending ? 'Oldest first' : 'Newest first',
                  visualDensity: VisualDensity.compact,
                  onPressed: () => setState(() {
                    _sortDescending = !_sortDescending;
                    _lastItems = null;
                  }),
                ),
              ],
              const Spacer(),
              IconButton(
                icon: const Icon(Icons.sort, size: 20),
                tooltip: 'Sort by date',
                visualDensity: VisualDensity.compact,
                onPressed: () => notifier.sortItemsByDate(),
              ),
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
              IconButton(
                icon: Icon(
                  notifier.showJournals ? Icons.book : Icons.book_outlined,
                  size: 20,
                  color: notifier.showJournals ? theme.colorScheme.primary : null,
                ),
                tooltip: notifier.showJournals ? 'Hide journals' : 'Show journals',
                visualDensity: VisualDensity.compact,
                onPressed: () => notifier.toggleJournals(),
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
                  _rebuildDisplayList(items, notifier.tripStart, notifier.dayMeta);
                  final hasFilter    = notifier.hasActiveFilter;
                  final selectedDays = notifier.selectedDays;
                  // Recompute filtered list only when inputs actually change.
                  if (!identical(_displayList, _cachedBaseList) ||
                      _lastHasFilter != hasFilter ||
                      !identical(_lastSelectedDays, selectedDays) ||
                      _lastMemoriesOnly != _memoriesOnly ||
                      _lastShowJournals != notifier.showJournals) {
                    var dl = _displayList;
                    if (hasFilter) dl = _applyDayFilter(dl, selectedDays);
                    if (_memoriesOnly) dl = _applyMemoriesFilter(dl);
                    if (!notifier.showJournals) dl = _removeJournals(dl);
                    _cachedBaseList     = _displayList;
                    _cachedFilteredList = dl;
                    _lastHasFilter      = hasFilter;
                    _lastSelectedDays   = selectedDays;
                    _lastMemoriesOnly   = _memoriesOnly;
                    _lastShowJournals   = notifier.showJournals;
                  }
                  final displayList = _cachedFilteredList!;
                  return ListView.builder(
                    controller: widget.scrollController,
                    itemCount: displayList.length,
                    itemBuilder: (context, vi) {
                      final entry = displayList[vi];

                      final isWide = MediaQuery.of(context).size.width >= 720;

                      // ── Day header ──────────────────────────────────────────
                      if (entry is _DayHeader) {
                        final h = entry;
                        final isCollapsed = _collapsedDays.contains(h.dayNumber);
                        final isMultiChecked = _selectedDays.contains(h.dateKey);
                        final isSingleSelected = !_multiSelect && _selectedDay == h.dateKey;
                        final isHighlighted = _multiSelect ? isMultiChecked : isSingleSelected;
                        Widget headerRow = InkWell(
                          key: isWide ? ValueKey('header_${h.dayNumber}') : null,
                          onTap: () {
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
                              Expanded(
                                child: () {
                                  final rawTags = notifier.dayMeta[h.dateKey]?['tags'];
                                  final tags = rawTags is List
                                      ? rawTags.cast<String>()
                                      : <String>[];
                                  return Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Text(
                                        'Day ${h.dayNumber} · ${_fmtGroupDate(h.date)}',
                                        overflow: TextOverflow.ellipsis,
                                        style: theme.textTheme.labelMedium?.copyWith(
                                          color: isHighlighted
                                              ? theme.colorScheme.primary
                                              : theme.colorScheme.onSurfaceVariant,
                                          fontWeight: FontWeight.w600,
                                        ),
                                      ),
                                      if (tags.isNotEmpty)
                                        Padding(
                                          padding: const EdgeInsets.only(top: 2),
                                          child: Wrap(
                                            spacing: 3,
                                            children: [
                                              for (final tag in tags)
                                                Container(
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
                                                      fontSize: 8,
                                                      height: 1.1,
                                                      color: theme.colorScheme
                                                          .onSecondaryContainer,
                                                    ),
                                                  ),
                                                ),
                                            ],
                                          ),
                                        ),
                                    ],
                                  );
                                }(),
                              ),
                              if (isWide)
                                IconButton(
                                  icon: const Icon(Icons.edit_outlined, size: 16),
                                  visualDensity: VisualDensity.compact,
                                  onPressed: () => showDayMetaDialog(
                                    context, notifier, h.dateKey,
                                    orderedDateKeys: _orderedDayKeys(),
                                  ),
                                ),
                              IconButton(
                                icon: const Icon(Icons.add, size: 16),
                                visualDensity: VisualDensity.compact,
                                onPressed: () => _showAddItemSheet(
                                  context, notifier,
                                  initialDate: h.dateKey,
                                  insertAfterIndex:
                                      _lastOriginalIndexForDay(h.dateKey),
                                ),
                              ),
                            ]),
                          ),
                        );

                        if (!isWide) {
                          headerRow = Dismissible(
                            key: ValueKey('header_swipe_${h.dayNumber}'),
                            direction: DismissDirection.startToEnd,
                            background: Container(
                              color: const Color(0xFF1D4ED8),
                              alignment: Alignment.centerLeft,
                              padding: const EdgeInsets.only(left: 20),
                              child: const Icon(Icons.edit_outlined,
                                  color: Colors.white),
                            ),
                            confirmDismiss: (_) async {
                              showDayMetaSheet(context, notifier, h.dateKey,
                                  orderedDateKeys: _orderedDayKeys());
                              return false;
                            },
                            child: headerRow,
                          );
                        }

                        return headerRow;
                      }

                      // ── Activity or segment item ─────────────────────────────
                      final panelItem = entry as _PanelItem;
                      final i = panelItem.originalIndex;
                      final item = panelItem.item;
                      final isActivity = item['item_type'] == 'activity';
                      if (isActivity) {
                        final a = activityById[item['activity_id']];
                        if (a == null) {
                          return Dismissible(
                            key: ValueKey('act_${item['activity_id']}'),
                            direction: DismissDirection.endToStart,
                            confirmDismiss: (_) async {
                              _dismissWithUndo(
                                context: context,
                                notifier: notifier,
                                label: 'Activity removed',
                                onOptimistic: () => notifier.removeItemLocally(i),
                                onConfirm: () => notifier.confirmRemoveItem(i),
                              );
                              return true;
                            },
                            background: Container(
                              color: theme.colorScheme.error,
                              alignment: Alignment.centerRight,
                              padding: const EdgeInsets.only(right: 20),
                              child: Icon(Icons.delete_outline,
                                  color: theme.colorScheme.onError),
                            ),
                            child: ListTile(
                              dense: true,
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
                          confirmDismiss: (_) async {
                            _dismissWithUndo(
                              context: context,
                              notifier: notifier,
                              label: 'Removed "$name"',
                              onOptimistic: () => notifier.removeItemLocally(i),
                              onConfirm: () => notifier.confirmRemoveItem(i),
                            );
                            return true;
                          },
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
                              dense: true,
                              tileColor: isSelected
                                  ? theme.colorScheme.primaryContainer
                                      .withValues(alpha: 0.45)
                                  : null,
                              leading: _ActivityIconBox(type: type),
                              title: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Text(name,
                                      style: theme.textTheme.labelSmall,
                                      overflow: TextOverflow.ellipsis),
                                  Text(
                                    '${(distM / 1000).toStringAsFixed(1)} km  •  ${_formatDuration(movingSec)}',
                                    style: theme.textTheme.bodySmall,
                                  ),
                                ],
                              ),
                              trailing: IconButton(
                                icon: const Icon(Icons.delete_outline, size: 15),
                                visualDensity: VisualDensity.compact,
                                padding: EdgeInsets.zero,
                                constraints: const BoxConstraints(),
                                color: theme.colorScheme.error.withValues(alpha: 0.6),
                                onPressed: () => _dismissWithUndo(
                                  context: context,
                                  notifier: notifier,
                                  label: 'Removed "$name"',
                                  onOptimistic: () => notifier.removeItemLocally(i),
                                  onConfirm: () => notifier.confirmRemoveItem(i),
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
                        return Dismissible(
                          key: ValueKey('mem_$memId'),
                          direction: DismissDirection.horizontal,
                          background: Container(
                            color: const Color(0xFF1D4ED8),
                            alignment: Alignment.centerLeft,
                            padding: const EdgeInsets.only(left: 20),
                            child: const Icon(Icons.edit_outlined,
                                color: Colors.white),
                          ),
                          secondaryBackground: Container(
                            color: theme.colorScheme.error,
                            alignment: Alignment.centerRight,
                            padding: const EdgeInsets.only(right: 20),
                            child: Icon(Icons.delete_outline,
                                color: theme.colorScheme.onError),
                          ),
                          confirmDismiss: (direction) async {
                            if (direction == DismissDirection.startToEnd) {
                              showMemoryDetail(context, notifier, mem);
                              return false;
                            }
                            _dismissWithUndo(
                              context: context,
                              notifier: notifier,
                              label: 'Removed "$label"',
                              onOptimistic: () =>
                                  notifier.removeMemoryLocally(memId),
                              onConfirm: () => notifier.deleteMemory(memId),
                            );
                            return true;
                          },
                          child: Selector<ProjectNotifier, bool>(
                            selector: (_, n) =>
                                n.selectedMemoryId?.toString() == memId,
                            builder: (_, isSelected, __) {
                              final commentCount =
                                  (mem['comment_count'] as num?)?.toInt() ?? 0;
                              final likeCount =
                                  (mem['like_count'] as num?)?.toInt() ?? 0;
                              final iconColor = isSelected
                                  ? theme.colorScheme.primary
                                  : theme.colorScheme.primary
                                      .withValues(alpha: 0.7);
                              return ListTile(
                                dense: true,
                                tileColor: isSelected
                                    ? theme.colorScheme.tertiaryContainer
                                        .withValues(alpha: 0.45)
                                    : null,
                                leading: Container(
                                  width: 32,
                                  height: 32,
                                  decoration: BoxDecoration(
                                    color: theme.colorScheme.primary
                                        .withValues(alpha: 0.12),
                                    borderRadius: BorderRadius.circular(8),
                                  ),
                                  child: Icon(
                                    Icons.photo_camera_outlined,
                                    size: 17,
                                    color: iconColor,
                                  ),
                                ),
                                title: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    Text(label,
                                        style: theme.textTheme.labelSmall,
                                        overflow: TextOverflow.ellipsis),
                                    if (memDesc != null && memDesc.isNotEmpty)
                                      Text(memDesc,
                                          maxLines: 1,
                                          overflow: TextOverflow.ellipsis,
                                          style: theme.textTheme.bodySmall)
                                    else if (memDate != null &&
                                        memName != null)
                                      Text(_fmtMemDate(memDate, memTime),
                                          style: theme.textTheme.bodySmall),
                                  ],
                                ),
                                trailing: Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    if (commentCount > 0) ...[
                                      const Icon(Icons.chat_bubble_outline,
                                          size: 12, color: Color(0xFF64748B)),
                                      const SizedBox(width: 2),
                                      Text('$commentCount',
                                          style: const TextStyle(
                                              fontSize: 11,
                                              color: Color(0xFF64748B))),
                                      const SizedBox(width: 4),
                                    ],
                                    if (likeCount > 0) ...[
                                      const Icon(Icons.favorite,
                                          size: 12, color: Color(0xFFEF4444)),
                                      const SizedBox(width: 2),
                                      Text('$likeCount',
                                          style: const TextStyle(
                                              fontSize: 11,
                                              color: Color(0xFF64748B))),
                                      const SizedBox(width: 4),
                                    ],
                                    IconButton(
                                      icon: const Icon(Icons.edit_outlined, size: 15),
                                      visualDensity: VisualDensity.compact,
                                      padding: EdgeInsets.zero,
                                      constraints: const BoxConstraints(),
                                      onPressed: () => showMemoryDetail(context, notifier, mem),
                                    ),
                                    const SizedBox(width: 2),
                                    IconButton(
                                      icon: const Icon(Icons.delete_outline, size: 15),
                                      visualDensity: VisualDensity.compact,
                                      padding: EdgeInsets.zero,
                                      constraints: const BoxConstraints(),
                                      color: theme.colorScheme.error.withValues(alpha: 0.6),
                                      onPressed: () => _dismissWithUndo(
                                        context: context,
                                        notifier: notifier,
                                        label: 'Removed "$label"',
                                        onOptimistic: () => notifier.removeMemoryLocally(memId),
                                        onConfirm: () => notifier.deleteMemory(memId),
                                      ),
                                    ),
                                  ],
                                ),
                                onTap: _multiSelect
                                    ? null
                                    : () => _flyToMemory(mem),
                              );
                            },
                          ),
                        );
                      } else if (item['item_type'] == 'journal') {
                        final jMap = item['journal'] as Map<String, dynamic>? ?? {};
                        final jId = jMap['id']?.toString() ?? '';
                        final jDate = jMap['date'] as String?;
                        final jTime = jMap['time'] as String?;
                        final jDesc = jMap['description'] as String?;
                        final label = jDate != null ? _fmtMemDate(jDate, jTime) : 'Journal';
                        return Dismissible(
                          key: ValueKey('journal_$jId'),
                          direction: DismissDirection.horizontal,
                          background: Container(
                            color: const Color(0xFF1D4ED8),
                            alignment: Alignment.centerLeft,
                            padding: const EdgeInsets.only(left: 20),
                            child: const Icon(Icons.edit_outlined,
                                color: Colors.white),
                          ),
                          secondaryBackground: Container(
                            color: theme.colorScheme.error,
                            alignment: Alignment.centerRight,
                            padding: const EdgeInsets.only(right: 20),
                            child: Icon(Icons.delete_outline,
                                color: theme.colorScheme.onError),
                          ),
                          confirmDismiss: (direction) async {
                            if (direction == DismissDirection.startToEnd) {
                              showDialog<void>(
                                context: context,
                                useRootNavigator: true,
                                builder: (_) => JournalDialog(
                                    notifier: notifier, editEntry: jMap),
                              );
                              return false;
                            }
                            _dismissWithUndo(
                              context: context,
                              notifier: notifier,
                              label: 'Removed "$label"',
                              onOptimistic: () =>
                                  notifier.removeJournalLocally(jId),
                              onConfirm: () => notifier.deleteJournal(jId),
                            );
                            return true;
                          },
                          child: Selector<ProjectNotifier, bool>(
                            selector: (_, n) =>
                                n.selectedJournalId?.toString() == jId,
                            builder: (_, isSelected, __) => ListTile(
                              dense: true,
                              tileColor: isSelected
                                  ? const Color(0xFF64748B)
                                      .withValues(alpha: 0.15)
                                  : null,
                              leading: Container(
                                width: 32,
                                height: 32,
                                decoration: BoxDecoration(
                                  color: const Color(0xFF64748B)
                                      .withValues(alpha: 0.15),
                                  borderRadius: BorderRadius.circular(8),
                                ),
                                child: Icon(Icons.book_outlined,
                                    size: 17,
                                    color: isSelected
                                        ? const Color(0xFF44AAFF)
                                        : const Color(0xFF64748B)),
                              ),
                              title: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Text(label,
                                      style: theme.textTheme.labelSmall,
                                      overflow: TextOverflow.ellipsis),
                                  if (jDesc != null && jDesc.isNotEmpty)
                                    Text(jDesc,
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                        style: theme.textTheme.bodySmall),
                                ],
                              ),
                              trailing: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  IconButton(
                                    icon: const Icon(Icons.edit_outlined, size: 15),
                                    visualDensity: VisualDensity.compact,
                                    padding: EdgeInsets.zero,
                                    constraints: const BoxConstraints(),
                                    onPressed: () => showDialog<void>(
                                      context: context,
                                      useRootNavigator: true,
                                      builder: (_) => JournalDialog(
                                          notifier: notifier, editEntry: jMap),
                                    ),
                                  ),
                                  const SizedBox(width: 2),
                                  IconButton(
                                    icon: const Icon(Icons.delete_outline, size: 15),
                                    visualDensity: VisualDensity.compact,
                                    padding: EdgeInsets.zero,
                                    constraints: const BoxConstraints(),
                                    color: theme.colorScheme.error.withValues(alpha: 0.6),
                                    onPressed: () => _dismissWithUndo(
                                      context: context,
                                      notifier: notifier,
                                      label: 'Removed "$label"',
                                      onOptimistic: () => notifier.removeJournalLocally(jId),
                                      onConfirm: () => notifier.deleteJournal(jId),
                                    ),
                                  ),
                                ],
                              ),
                              onTap: _multiSelect
                                  ? null
                                  : () {
                                      _flyToJournal(jMap);
                                      showJournalDetail(
                                          context, widget.notifier, jMap);
                                    },
                            ),
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
                          direction: DismissDirection.horizontal,
                          background: Container(
                            color: const Color(0xFF1D4ED8),
                            alignment: Alignment.centerLeft,
                            padding: const EdgeInsets.only(left: 20),
                            child: const Icon(Icons.edit_outlined,
                                color: Colors.white),
                          ),
                          secondaryBackground: Container(
                            color: theme.colorScheme.error,
                            alignment: Alignment.centerRight,
                            padding: const EdgeInsets.only(right: 20),
                            child: Icon(Icons.delete_outline,
                                color: theme.colorScheme.onError),
                          ),
                          confirmDismiss: (direction) async {
                            if (direction == DismissDirection.startToEnd) {
                              _showSegmentDialog(context, notifier,
                                  editSegment: seg, insertAfterIndex: null);
                              return false;
                            }
                            _dismissWithUndo(
                              context: context,
                              notifier: notifier,
                              label: 'Removed "$label"',
                              onOptimistic: () =>
                                  notifier.removeSegmentLocally(segId),
                              onConfirm: () => notifier.deleteSegment(segId),
                            );
                            return true;
                          },
                          child: Selector<ProjectNotifier, bool>(
                            selector: (_, n) =>
                                n.selectedSegmentId?.toString() == segId,
                            builder: (_, isSelected, __) => ListTile(
                              dense: true,
                              tileColor: isSelected
                                  ? theme.colorScheme.secondaryContainer
                                      .withValues(alpha: 0.45)
                                  : null,
                              title: Row(children: [
                                Container(
                                  width: 32,
                                  height: 32,
                                  decoration: BoxDecoration(
                                    color: const Color(0xFF94A3B8)
                                        .withValues(alpha: 0.15),
                                    borderRadius: BorderRadius.circular(8),
                                  ),
                                  child: Icon(
                                    _iconForSegmentType(
                                      segType ?? (seg['route_mode'] == 'rail' ? 'train' : null),
                                    ),
                                    size: 17,
                                    color: const Color(0xFF64748B),
                                  ),
                                ),
                                const SizedBox(width: 8),
                                Flexible(
                                  child: Text(label,
                                      style: _segmentTitleStyle),
                                ),
                              ]),
                              subtitle: _segmentStatusLine(
                                  context, notifier, seg, segId, segType, theme),
                              trailing: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  IconButton(
                                    icon: const Icon(Icons.edit_outlined, size: 15),
                                    visualDensity: VisualDensity.compact,
                                    padding: EdgeInsets.zero,
                                    constraints: const BoxConstraints(),
                                    onPressed: () => _showSegmentDialog(
                                      context, notifier,
                                      editSegment: seg, insertAfterIndex: null,
                                    ),
                                  ),
                                  const SizedBox(width: 2),
                                  IconButton(
                                    icon: const Icon(Icons.delete_outline, size: 15),
                                    visualDensity: VisualDensity.compact,
                                    padding: EdgeInsets.zero,
                                    constraints: const BoxConstraints(),
                                    color: theme.colorScheme.error.withValues(alpha: 0.6),
                                    onPressed: () => _dismissWithUndo(
                                      context: context,
                                      notifier: notifier,
                                      label: 'Removed "$label"',
                                      onOptimistic: () => notifier.removeSegmentLocally(segId),
                                      onConfirm: () => notifier.deleteSegment(segId),
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
          child: SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              icon: const Icon(Icons.add, size: 10),
              label: const Text('Add…'),
              onPressed: () => _showAddItemSheet(
                context, notifier,
                insertAfterIndex:
                    items.isNotEmpty ? items.length - 1 : null,
              ),
            ),
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
  dynamic preselectedStartActivityId,
}) async {
  // Defer to a post-frame callback so the dialog is added to the overlay
  // after the current frame's layout pass completes. Without this, the
  // Overlay rebuild that showDialog triggers can process dirty elements
  // (including OverlayPortal tooltips) during a layout callback, violating
  // Flutter's render-mutation invariant.
  WidgetsBinding.instance.addPostFrameCallback((_) {
    if (!context.mounted) return;
    showDialog<void>(
      context: context,
      builder: (ctx) => SegmentDialog(
        notifier: notifier,
        editSegment: editSegment,
        insertAfterIndex: insertAfterIndex,
        preselectedStartActivityId: preselectedStartActivityId,
      ),
    );
  });
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

// ── Filter sheet ─────────────────────────────────────────────────────────────

const _transportLabels = {
  'flight': 'Flight',
  'train':  'Train',
  'bus':    'Bus',
  'boat':   'Boat',
};

String _capitalize(String s) => s.isEmpty ? s : s[0].toUpperCase() + s.substring(1);

class FilterSheet extends StatelessWidget {
  final ProjectNotifier notifier;
  final bool readOnly;

  const FilterSheet({super.key, required this.notifier, required this.readOnly});

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: notifier,
      builder: (context, _) {
        final theme = Theme.of(context);
        final tags       = notifier.availableTags;
        final sleeping   = notifier.availableSleepingModes;
        final actTypes   = notifier.availableActivityTypes;
        final transport  = notifier.availableTransportationMeans;
        final hasAny     = notifier.hasActiveFilter;

        return SingleChildScrollView(
          padding: EdgeInsets.fromLTRB(
              16, 16, 16, 32 + MediaQuery.of(context).viewInsets.bottom),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // ── Header ───────────────────────────────────────────────────
              Row(
                children: [
                  Text('Filter', style: theme.textTheme.titleMedium),
                  const Spacer(),
                  if (hasAny)
                    TextButton(
                      onPressed: () {
                        notifier.clearAllFilters();
                        Navigator.of(context).pop();
                      },
                      child: const Text('Clear all'),
                    ),
                ],
              ),

              // ── Tags ──────────────────────────────────────────────────────
              if (tags.isNotEmpty) ...[
                const SizedBox(height: 16),
                Text('Tags', style: theme.textTheme.labelMedium),
                const SizedBox(height: 8),
                _chips(
                  options:  tags,
                  selected: notifier.tagFilter,
                  label:    (t) => t,
                  onToggle: (next) => notifier.setFilters(tags: next),
                ),
              ],

              // ── Sleeping mode ─────────────────────────────────────────────
              if (sleeping.isNotEmpty) ...[
                const SizedBox(height: 16),
                Text('Sleeping mode', style: theme.textTheme.labelMedium),
                const SizedBox(height: 8),
                _chips(
                  options:  sleeping,
                  selected: notifier.sleepingFilter,
                  label:    (s) => s,
                  onToggle: (next) => notifier.setFilters(sleeping: next),
                ),
              ],

              // ── Activity type ─────────────────────────────────────────────
              if (actTypes.isNotEmpty) ...[
                const SizedBox(height: 16),
                Text('Activity type', style: theme.textTheme.labelMedium),
                const SizedBox(height: 8),
                _chips(
                  options:  actTypes,
                  selected: notifier.activityTypeFilter,
                  label:    _capitalize,
                  onToggle: (next) => notifier.setFilters(activityTypes: next),
                ),
              ],

              // ── Transportation ────────────────────────────────────────────
              if (transport.isNotEmpty) ...[
                const SizedBox(height: 16),
                Text('Transportation', style: theme.textTheme.labelMedium),
                const SizedBox(height: 8),
                _chips(
                  options:  transport,
                  selected: notifier.transportFilter,
                  label:    (t) => _transportLabels[t] ?? _capitalize(t),
                  onToggle: (next) => notifier.setFilters(transport: next),
                ),
              ],
            ],
          ),
        );
      },
    );
  }

  Widget _chips({
    required List<String> options,
    required Set<String> selected,
    required String Function(String) label,
    required void Function(Set<String>) onToggle,
  }) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: options.map((opt) => FilterChip(
        label: Text(label(opt)),
        selected: selected.contains(opt),
        onSelected: readOnly ? null : (on) {
          final next = Set<String>.of(selected);
          if (on) { next.add(opt); } else { next.remove(opt); }
          onToggle(next);
        },
      )).toList(),
    );
  }
}

// Keep old name as alias so shared_project_screen.dart doesn't break.
typedef TagFilterSheet = FilterSheet;
