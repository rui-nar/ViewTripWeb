import 'dart:async';

import 'package:flutter/material.dart';

import '../map/great_circle.dart';
import 'location_picker_dialog.dart';
import 'project_notifier.dart';

class SegmentDialog extends StatefulWidget {
  final ProjectNotifier notifier;
  final Map<String, dynamic>? editSegment; // non-null = edit mode
  final int? insertAfterIndex;             // create mode: where to insert

  const SegmentDialog({
    super.key,
    required this.notifier,
    this.editSegment,
    this.insertAfterIndex,
  });

  @override
  State<SegmentDialog> createState() => _SegmentDialogState();
}

class _SegmentDialogState extends State<SegmentDialog> {
  final _formKey = GlobalKey<FormState>();
  late String _segmentType;
  late TextEditingController _labelCtrl;
  late TextEditingController _startLatCtrl;
  late TextEditingController _startLonCtrl;
  late TextEditingController _endLatCtrl;
  late TextEditingController _endLonCtrl;
  DateTime? _date;
  bool _saving = false;
  Timer? _previewDebounce;

  // Rail-track fields (train segments only)
  String _routeMode = 'great_circle';
  String _hafasProvider = 'db';
  late TextEditingController _trainNumberCtrl;

  static const _operators = [
    ('db',   'DB (Deutsche Bahn)'),
    ('obb',  'ÖBB (Austria)'),
    ('sncf', 'SNCF (France)'),
    ('sj',   'SJ (Sweden)'),
    ('dsb',  'DSB (Denmark)'),
    ('vr',   'VR (Finland)'),
    ('nsb',  'NSB / Vy (Norway)'),
  ];

  static const _months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  static String _fmtDate(DateTime d) => '${_months[d.month - 1]} ${d.day}, ${d.year}';
  static String _toIso(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  @override
  void initState() {
    super.initState();
    final seg = widget.editSegment;
    _segmentType = (seg?['segment_type'] as String?) ?? 'flight';
    _labelCtrl = TextEditingController(text: seg?['label'] as String? ?? '');
    _startLatCtrl = TextEditingController(
        text: _fmt(seg?['start']?['lat']));
    _startLonCtrl = TextEditingController(
        text: _fmt(seg?['start']?['lon']));
    _endLatCtrl = TextEditingController(
        text: _fmt(seg?['end']?['lat']));
    _endLonCtrl = TextEditingController(
        text: _fmt(seg?['end']?['lon']));

    // Date: edit mode reads from segment, create mode auto-infers
    final dateStr = seg?['date'] as String?;
    if (dateStr != null) {
      _date = DateTime.tryParse(dateStr);
    }

    // Rail-track fields
    _routeMode     = (seg?['route_mode'] as String?) ?? 'great_circle';
    _hafasProvider = (seg?['hafas_provider'] as String?) ?? 'db';
    _trainNumberCtrl = TextEditingController(
        text: seg?['train_number'] as String? ?? '');
    // Auto-populate from adjacent activities if creating new segment
    if (seg == null) _autoPopulate();

    // Update arc preview whenever any coordinate field changes.
    // Debounced so greatCirclePoints() is not called on every keystroke.
    _startLatCtrl.addListener(_schedulePreviewUpdate);
    _startLonCtrl.addListener(_schedulePreviewUpdate);
    _endLatCtrl.addListener(_schedulePreviewUpdate);
    _endLonCtrl.addListener(_schedulePreviewUpdate);
    // Defer so the ValueNotifier change doesn't fire during the first build.
    WidgetsBinding.instance.addPostFrameCallback((_) => _updatePreview());
  }

  void _schedulePreviewUpdate() {
    _previewDebounce?.cancel();
    _previewDebounce = Timer(
      const Duration(milliseconds: 250),
      _updatePreview,
    );
  }

  void _updatePreview() {
    final lat1 = double.tryParse(_startLatCtrl.text.trim());
    final lon1 = double.tryParse(_startLonCtrl.text.trim());
    final lat2 = double.tryParse(_endLatCtrl.text.trim());
    final lon2 = double.tryParse(_endLonCtrl.text.trim());
    if (lat1 != null && lon1 != null && lat2 != null && lon2 != null) {
      widget.notifier.previewArcNotifier.value = greatCirclePoints(lat1, lon1, lat2, lon2);
    } else {
      widget.notifier.previewArcNotifier.value = null;
    }
  }

  String _fmt(dynamic v) {
    if (v == null) return '';
    final d = (v as num).toDouble();
    return d == 0.0 ? '' : d.toStringAsFixed(6);
  }

  void _autoPopulate() {
    final items = widget.notifier.items;
    final activities = widget.notifier.activities;
    final insertAfter = widget.insertAfterIndex;
    if (insertAfter == null || items.isEmpty) return;

    Map<String, dynamic>? actById(dynamic id) {
      if (id == null) return null;
      try {
        return activities.firstWhere((a) => a['id'] == id);
      } catch (_) {
        return null;
      }
    }

    // Predecessor: item at insertAfter
    if (insertAfter >= 0 && insertAfter < items.length) {
      final prev = items[insertAfter];
      if (prev['item_type'] == 'activity') {
        final a = actById(prev['activity_id']);
        final endLl = a?['end_latlng'];
        if (endLl is List && endLl.length >= 2) {
          _startLatCtrl.text = (endLl[0] as num).toStringAsFixed(6);
          _startLonCtrl.text = (endLl[1] as num).toStringAsFixed(6);
        }
      } else if (prev['item_type'] == 'segment') {
        final end = prev['segment']?['end'] as Map?;
        if (end != null) {
          _startLatCtrl.text = (end['lat'] as num).toStringAsFixed(6);
          _startLonCtrl.text = (end['lon'] as num).toStringAsFixed(6);
        }
      }
    }

    // Successor: item after insertAfter
    final nextIdx = insertAfter + 1;
    if (nextIdx < items.length) {
      final next = items[nextIdx];
      if (next['item_type'] == 'activity') {
        final a = actById(next['activity_id']);
        final startLl = a?['start_latlng'];
        if (startLl is List && startLl.length >= 2) {
          _endLatCtrl.text = (startLl[0] as num).toStringAsFixed(6);
          _endLonCtrl.text = (startLl[1] as num).toStringAsFixed(6);
        }
      } else if (next['item_type'] == 'segment') {
        final start = next['segment']?['start'] as Map?;
        if (start != null) {
          _endLatCtrl.text = (start['lat'] as num).toStringAsFixed(6);
          _endLonCtrl.text = (start['lon'] as num).toStringAsFixed(6);
        }
      }
    }

    // Infer date: walk backwards from insertAfter to find nearest dated item
    for (int i = insertAfter; i >= 0; i--) {
      final it = items[i];
      if (it['item_type'] == 'activity') {
        final a = actById(it['activity_id']);
        final ds = a?['start_date_local'] as String?;
        if (ds != null) { _date = DateTime.tryParse(ds); break; }
      } else if (it['item_type'] == 'segment') {
        final ds = it['segment']?['date'] as String?;
        if (ds != null) { _date = DateTime.tryParse(ds); break; }
      }
    }
  }

  @override
  void dispose() {
    _previewDebounce?.cancel();
    // Defer so we don't fire the ValueNotifier while the framework tree is
    // locked during unmount (finalizeTree / lockState).
    final notifier = widget.notifier;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      notifier.previewArcNotifier.value = null;
    });
    _labelCtrl.dispose();
    _startLatCtrl.dispose();
    _startLonCtrl.dispose();
    _endLatCtrl.dispose();
    _endLonCtrl.dispose();
    _trainNumberCtrl.dispose();
    super.dispose();
  }

  Future<void> _pickLocation({
    required String title,
    required TextEditingController latCtrl,
    required TextEditingController lonCtrl,
    required bool isStart,
  }) async {
    // Determine the "other" endpoint so the picker can show a live arc preview
    final otherLatCtrl = isStart ? _endLatCtrl   : _startLatCtrl;
    final otherLonCtrl = isStart ? _endLonCtrl   : _startLonCtrl;
    final result = await showDialog<LatLonResult>(
      context: context,
      useRootNavigator: true,
      builder: (_) => LocationPickerDialog(
        title: title,
        initialLat: double.tryParse(latCtrl.text.trim()),
        initialLon: double.tryParse(lonCtrl.text.trim()),
        geo: widget.notifier.geo,
        previewArcNotifier: widget.notifier.previewArcNotifier,
        otherLat: double.tryParse(otherLatCtrl.text.trim()),
        otherLon: double.tryParse(otherLonCtrl.text.trim()),
        isStart: isStart,
      ),
    );
    if (result != null && mounted) {
      setState(() {
        latCtrl.text = result.lat.toStringAsFixed(6);
        lonCtrl.text = result.lon.toStringAsFixed(6);
      });
    }
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _saving = true);

    final startLat = double.parse(_startLatCtrl.text.trim());
    final startLon = double.parse(_startLonCtrl.text.trim());
    final endLat = double.parse(_endLatCtrl.text.trim());
    final endLon = double.parse(_endLonCtrl.text.trim());
    final dateStr = _date != null ? _toIso(_date!) : null;
    final trainNum = _trainNumberCtrl.text.trim().isEmpty
        ? null
        : _trainNumberCtrl.text.trim();
    final needsResolve =
        (_segmentType == 'train' && _routeMode == 'rail')  ||
        (_segmentType == 'boat'  && _routeMode == 'ferry') ||
        (_segmentType == 'bus'   && _routeMode == 'bus');

    String resolveSegId = '';
    if (widget.editSegment != null) {
      await widget.notifier.updateSegment(
        widget.editSegment!['id'] as String,
        segmentType: _segmentType,
        label: _labelCtrl.text.trim(),
        startLat: startLat,
        startLon: startLon,
        endLat: endLat,
        endLon: endLon,
        date: dateStr,
        trainNumber: trainNum,
        hafasProvider: needsResolve ? _hafasProvider : null,
        routeMode: {'train', 'boat', 'bus'}.contains(_segmentType) ? _routeMode : null,
      );
      resolveSegId = widget.editSegment!['id'] as String;
    } else {
      resolveSegId = await widget.notifier.addSegment(
        segmentType: _segmentType,
        label: _labelCtrl.text.trim(),
        startLat: startLat,
        startLon: startLon,
        endLat: endLat,
        endLon: endLon,
        insertAfterIndex: widget.insertAfterIndex,
        date: dateStr,
        trainNumber: trainNum,
        hafasProvider: needsResolve ? _hafasProvider : null,
      );
    }

    if (!mounted) return;

    if (needsResolve && resolveSegId.isNotEmpty) {
      final messenger = ScaffoldMessenger.of(context);
      final notifier  = widget.notifier;
      final provider  = _hafasProvider;
      final segId     = resolveSegId;
      final routeMode = const {'train': 'rail', 'boat': 'ferry', 'bus': 'bus'}[_segmentType]!;
      final resolveMsg = routeMode == 'ferry'
          ? 'Calculating ferry route — this may take up to a minute…'
          : routeMode == 'bus'
              ? 'Calculating bus route — this may take up to a minute…'
              : 'Calculating rail route — this may take up to a minute…';
      messenger.showSnackBar(SnackBar(
        content: Text(resolveMsg),
        duration: const Duration(seconds: 10),
      ));
      Navigator.of(context).pop();
      unawaited(_resolveAsync(notifier, segId, routeMode, provider, trainNum, dateStr, messenger));
    } else {
      Navigator.of(context).pop();
    }
  }

  static Future<void> _resolveAsync(
    ProjectNotifier notifier,
    String segId,
    String routeMode,
    String hafasProvider,
    String? trainNumber,
    String? date,
    ScaffoldMessengerState messenger,
  ) async {
    try {
      final result = await notifier.resolveTrainRoute(
        segId,
        routeMode: routeMode,
        hafasProvider: routeMode == 'rail' ? hafasProvider : null,
        trainNumber:   routeMode == 'rail' ? trainNumber   : null,
        date: date,
      );
      final stopCount = result['stop_count'] as int? ?? 0;
      final msg = switch (routeMode) {
        'ferry' => 'Ferry route resolved',
        'bus'   => 'Bus route resolved',
        _       => 'Rail route resolved · $stopCount stops',
      };
      messenger.showSnackBar(SnackBar(
        content: Text(msg),
        duration: const Duration(seconds: 5),
      ));
    } catch (e) {
      final msg = e.toString().replaceFirst('Exception: ', '');
      messenger.showSnackBar(SnackBar(
        content: Text('Route unavailable: $msg'),
        duration: const Duration(seconds: 6),
      ));
    }
  }

  String? _validateCoord(String? v) {
    if (v == null || v.trim().isEmpty) return 'Required';
    if (double.tryParse(v.trim()) == null) return 'Invalid number';
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isEdit = widget.editSegment != null;
    return AlertDialog(
      title: Text(isEdit ? 'Edit Segment' : 'Add Segment'),
      content: SizedBox(
        width: 420,
        child: SingleChildScrollView(
          child: Form(
          key: _formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Segment type
              const Text('Type'),
              const SizedBox(height: 6),
              SizedBox(
                width: double.infinity,
                child: SegmentedButton<String>(
                  segments: const [
                    ButtonSegment(value: 'flight', icon: Icon(Icons.flight), label: Text('Flight')),
                    ButtonSegment(value: 'train',  icon: Icon(Icons.train),  label: Text('Train')),
                    ButtonSegment(value: 'bus',    icon: Icon(Icons.directions_bus), label: Text('Bus')),
                    ButtonSegment(value: 'boat',   icon: Icon(Icons.directions_boat), label: Text('Boat')),
                  ],
                  selected: {_segmentType},
                  onSelectionChanged: (s) => setState(() {
                    final prev = _segmentType;
                    _segmentType = s.first;
                    const modeForType = {'train': 'rail', 'boat': 'ferry', 'bus': 'bus'};
                    if (modeForType[prev] != null &&
                        _routeMode == modeForType[prev] &&
                        s.first != prev) {
                      _routeMode = 'great_circle';
                    }
                  }),
                  multiSelectionEnabled: false,
                ),
              ),
              const SizedBox(height: 16),
              // Label
              TextFormField(
                controller: _labelCtrl,
                decoration: const InputDecoration(
                  labelText: 'Label (optional)',
                  hintText: 'e.g. Basel → Paris',
                ),
              ),
              const SizedBox(height: 12),
              // Date
              InkWell(
                borderRadius: BorderRadius.circular(8),
                onTap: () async {
                  final picked = await showDatePicker(
                    context: context,
                    initialDate: _date ?? DateTime.now(),
                    firstDate: DateTime(2000),
                    lastDate: DateTime(2100),
                  );
                  if (picked != null) setState(() => _date = picked);
                },
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  child: Row(
                    children: [
                      Icon(Icons.calendar_today, size: 18,
                          color: theme.colorScheme.onSurfaceVariant),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          _date == null ? 'No date set' : _fmtDate(_date!),
                          style: theme.textTheme.bodyMedium?.copyWith(
                            color: _date == null
                                ? theme.colorScheme.onSurfaceVariant
                                : null,
                          ),
                        ),
                      ),
                      if (_date != null)
                        IconButton(
                          icon: const Icon(Icons.close, size: 16),
                          visualDensity: VisualDensity.compact,
                          onPressed: () => setState(() => _date = null),
                        ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 4),
              // Start
              Row(
                children: [
                  const Text('Start'),
                  const Spacer(),
                  TextButton.icon(
                    icon: const Icon(Icons.location_on_outlined, size: 16),
                    label: const Text('Pick on map'),
                    style: TextButton.styleFrom(
                        visualDensity: VisualDensity.compact),
                    onPressed: () => _pickLocation(
                      title: 'Pick start location',
                      latCtrl: _startLatCtrl,
                      lonCtrl: _startLonCtrl,
                      isStart: true,
                    ),
                  ),
                ],
              ),
              Row(
                children: [
                  Expanded(
                    child: TextFormField(
                      controller: _startLatCtrl,
                      decoration:
                          const InputDecoration(labelText: 'Lat'),
                      keyboardType: const TextInputType.numberWithOptions(
                          decimal: true, signed: true),
                      validator: _validateCoord,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: TextFormField(
                      controller: _startLonCtrl,
                      decoration:
                          const InputDecoration(labelText: 'Lon'),
                      keyboardType: const TextInputType.numberWithOptions(
                          decimal: true, signed: true),
                      validator: _validateCoord,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              // End
              Row(
                children: [
                  const Text('End'),
                  const Spacer(),
                  TextButton.icon(
                    icon: const Icon(Icons.location_on_outlined, size: 16),
                    label: const Text('Pick on map'),
                    style: TextButton.styleFrom(
                        visualDensity: VisualDensity.compact),
                    onPressed: () => _pickLocation(
                      title: 'Pick end location',
                      latCtrl: _endLatCtrl,
                      lonCtrl: _endLonCtrl,
                      isStart: false,
                    ),
                  ),
                ],
              ),
              Row(
                children: [
                  Expanded(
                    child: TextFormField(
                      controller: _endLatCtrl,
                      decoration:
                          const InputDecoration(labelText: 'Lat'),
                      keyboardType: const TextInputType.numberWithOptions(
                          decimal: true, signed: true),
                      validator: _validateCoord,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: TextFormField(
                      controller: _endLonCtrl,
                      decoration:
                          const InputDecoration(labelText: 'Lon'),
                      keyboardType: const TextInputType.numberWithOptions(
                          decimal: true, signed: true),
                      validator: _validateCoord,
                    ),
                  ),
                ],
              ),

              // ── Rail track section (train only) ──────────────────────
              if (_segmentType == 'train') ...[
                const SizedBox(height: 16),
                const Divider(),
                const SizedBox(height: 8),
                Text('Rail track', style: Theme.of(context).textTheme.labelMedium),
                const SizedBox(height: 10),
                SizedBox(
                  width: double.infinity,
                  child: SegmentedButton<String>(
                    segments: const [
                      ButtonSegment(
                        value: 'great_circle',
                        icon: Icon(Icons.show_chart, size: 16),
                        label: Text('Great circle'),
                      ),
                      ButtonSegment(
                        value: 'rail',
                        icon: Icon(Icons.train, size: 16),
                        label: Text('Follow rail lines'),
                      ),
                    ],
                    selected: {_routeMode},
                    onSelectionChanged: (s) =>
                        setState(() => _routeMode = s.first),
                    multiSelectionEnabled: false,
                  ),
                ),
                if (_routeMode == 'rail') ...[
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String>(
                    initialValue: _hafasProvider,
                    decoration: const InputDecoration(
                      labelText: 'Operator',
                      isDense: true,
                    ),
                    items: _operators
                        .map((o) => DropdownMenuItem(value: o.$1, child: Text(o.$2)))
                        .toList(),
                    onChanged: (v) {
                      if (v != null) setState(() => _hafasProvider = v);
                    },
                  ),
                  const SizedBox(height: 8),
                  TextFormField(
                    controller: _trainNumberCtrl,
                    decoration: const InputDecoration(
                      labelText: 'Train number (optional)',
                      hintText: 'e.g. ICE 596',
                      isDense: true,
                    ),
                  ),
                ],
              ],

              // ── Ferry route section (boat only) ───────────────────────
              if (_segmentType == 'boat') ...[
                const SizedBox(height: 16),
                const Divider(),
                const SizedBox(height: 8),
                Text('Ferry route', style: Theme.of(context).textTheme.labelMedium),
                const SizedBox(height: 10),
                SizedBox(
                  width: double.infinity,
                  child: SegmentedButton<String>(
                    segments: const [
                      ButtonSegment(
                        value: 'great_circle',
                        icon: Icon(Icons.show_chart, size: 16),
                        label: Text('Great circle'),
                      ),
                      ButtonSegment(
                        value: 'ferry',
                        icon: Icon(Icons.directions_boat, size: 16),
                        label: Text('Follow ferry route'),
                      ),
                    ],
                    selected: {_routeMode == 'ferry' ? 'ferry' : 'great_circle'},
                    onSelectionChanged: (s) => setState(() => _routeMode = s.first),
                    multiSelectionEnabled: false,
                  ),
                ),
              ],

              // ── Bus route section (bus only) ──────────────────────────
              if (_segmentType == 'bus') ...[
                const SizedBox(height: 16),
                const Divider(),
                const SizedBox(height: 8),
                Text('Bus route', style: Theme.of(context).textTheme.labelMedium),
                const SizedBox(height: 10),
                SizedBox(
                  width: double.infinity,
                  child: SegmentedButton<String>(
                    segments: const [
                      ButtonSegment(
                        value: 'great_circle',
                        icon: Icon(Icons.show_chart, size: 16),
                        label: Text('Great circle'),
                      ),
                      ButtonSegment(
                        value: 'bus',
                        icon: Icon(Icons.directions_bus, size: 16),
                        label: Text('Follow bus route'),
                      ),
                    ],
                    selected: {_routeMode == 'bus' ? 'bus' : 'great_circle'},
                    onSelectionChanged: (s) => setState(() => _routeMode = s.first),
                    multiSelectionEnabled: false,
                  ),
                ),
              ],
            ],
          ),
        ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: _saving ? null : () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        ElevatedButton(
          onPressed: _saving ? null : _save,
          child: _saving
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Save'),
        ),
      ],
    );
  }
}
