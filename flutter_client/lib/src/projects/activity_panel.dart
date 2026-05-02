library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:provider/provider.dart';

import '../core/design_tokens.dart';
import 'day_meta_editor.dart';
import 'memory_detail_modal.dart';
import 'memory_dialog.dart';
import 'project_notifier.dart';
import 'segment_dialog.dart';
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

  // Filtered display list cache — rebuilt only when base list, filter state,
  // or memories-only toggle actually changes.
  List<Object>? _cachedBaseList;
  List<Object>? _cachedFilteredList;
  Set<String>?  _lastSelectedDays;
  bool?         _lastHasFilter;
  bool?         _lastMemoriesOnly;

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
                  _rebuildDisplayList(items, notifier.tripStart);
                  final hasFilter    = notifier.hasActiveFilter;
                  final selectedDays = notifier.selectedDays;
                  // Recompute filtered list only when inputs actually change.
                  if (!identical(_displayList, _cachedBaseList) ||
                      _lastHasFilter != hasFilter ||
                      !identical(_lastSelectedDays, selectedDays) ||
                      _lastMemoriesOnly != _memoriesOnly) {
                    var dl = _displayList;
                    if (hasFilter) dl = _applyDayFilter(dl, selectedDays);
                    if (_memoriesOnly) dl = _applyMemoriesFilter(dl);
                    _cachedBaseList     = _displayList;
                    _cachedFilteredList = dl;
                    _lastHasFilter      = hasFilter;
                    _lastSelectedDays   = selectedDays;
                    _lastMemoriesOnly   = _memoriesOnly;
                  }
                  final displayList = _cachedFilteredList!;
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
                              Expanded(
                                child: Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    Flexible(
                                      child: Text(
                                        'Day ${h.dayNumber} · ${_fmtGroupDate(h.date)}',
                                        overflow: TextOverflow.ellipsis,
                                        style: theme.textTheme.labelMedium?.copyWith(
                                          color: isHighlighted
                                              ? theme.colorScheme.primary
                                              : theme.colorScheme.onSurfaceVariant,
                                          fontWeight: FontWeight.w600,
                                        ),
                                      ),
                                    ),
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
                                  ],
                                ),
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
                                icon: const Icon(
                                    Icons.add_photo_alternate_outlined,
                                    size: 16),
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
                                          showDayMetaSheet(context, notifier, h.dateKey,
                                              orderedDateKeys: _orderedDayKeys());
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
                                _ActivityIconBox(type: type),
                                const SizedBox(width: 8),
                                Flexible(
                                  child: Text(name,
                                      style: theme.textTheme.labelMedium),
                                ),
                              ]),
                              subtitle: Text(
                                '${(distM / 1000).toStringAsFixed(1)} km  •  ${_formatDuration(movingSec)}',
                                style: theme.textTheme.bodySmall,
                              ),
                              trailing: IconButton(
                                icon: const Icon(Icons.add_road, size: 18),
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
                                Container(
                                  width: 32,
                                  height: 32,
                                  decoration: BoxDecoration(
                                    color: const Color(0xFF94A3B8)
                                        .withValues(alpha: 0.15),
                                    borderRadius: BorderRadius.circular(8),
                                  ),
                                  child: Icon(
                                    _iconForSegmentType(segType),
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
                              subtitle: Text(segType ?? '',
                                  style: theme.textTheme.bodySmall),
                              trailing: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  IconButton(
                                    icon: const Icon(Icons.edit_outlined,
                                        size: 18),
                                    onPressed: () => _showSegmentDialog(
                                      context,
                                      notifier,
                                      editSegment: seg,
                                      insertAfterIndex: null,
                                    ),
                                  ),
                                  IconButton(
                                    icon: const Icon(Icons.add_road, size: 18),
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
                  icon: const Icon(Icons.add, size: 10),
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
                  icon: const Icon(Icons.add_photo_alternate_outlined, size: 10),
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
  // Defer to a post-frame callback so the dialog is added to the overlay
  // after the current frame's layout pass completes. Without this, the
  // Overlay rebuild that showDialog triggers can cause the ReorderableListView's
  // LayoutBuilder to process dirty elements (including OverlayPortal tooltips)
  // during its layout callback, violating Flutter's render-mutation invariant.
  WidgetsBinding.instance.addPostFrameCallback((_) {
    if (!context.mounted) return;
    showDialog<void>(
      context: context,
      builder: (ctx) => SegmentDialog(
        notifier: notifier,
        editSegment: editSegment,
        insertAfterIndex: insertAfterIndex,
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
