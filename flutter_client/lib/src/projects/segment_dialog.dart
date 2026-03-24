import 'package:flutter/material.dart';

import '../map/great_circle.dart';
import '../map/location_picker_dialog.dart';
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
  bool _saving = false;

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

    // Auto-populate from adjacent activities if creating new segment
    if (seg == null) _autoPopulate();

    // Update arc preview whenever any coordinate field changes
    _startLatCtrl.addListener(_updatePreview);
    _startLonCtrl.addListener(_updatePreview);
    _endLatCtrl.addListener(_updatePreview);
    _endLonCtrl.addListener(_updatePreview);
    _updatePreview();
  }

  void _updatePreview() {
    final lat1 = double.tryParse(_startLatCtrl.text.trim());
    final lon1 = double.tryParse(_startLonCtrl.text.trim());
    final lat2 = double.tryParse(_endLatCtrl.text.trim());
    final lon2 = double.tryParse(_endLonCtrl.text.trim());
    if (lat1 != null && lon1 != null && lat2 != null && lon2 != null) {
      widget.notifier.setPreviewArc(greatCirclePoints(lat1, lon1, lat2, lon2));
    } else {
      widget.notifier.setPreviewArc(null);
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
      }
    }
  }

  @override
  void dispose() {
    widget.notifier.setPreviewArc(null);
    _labelCtrl.dispose();
    _startLatCtrl.dispose();
    _startLonCtrl.dispose();
    _endLatCtrl.dispose();
    _endLonCtrl.dispose();
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
      builder: (_) => LocationPickerDialog(
        title: title,
        initialLat: double.tryParse(latCtrl.text.trim()),
        initialLon: double.tryParse(lonCtrl.text.trim()),
        geo: widget.notifier.geo,
        notifier: widget.notifier,
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

    if (widget.editSegment != null) {
      await widget.notifier.updateSegment(
        widget.editSegment!['id'] as String,
        segmentType: _segmentType,
        label: _labelCtrl.text.trim(),
        startLat: startLat,
        startLon: startLon,
        endLat: endLat,
        endLon: endLon,
      );
    } else {
      await widget.notifier.addSegment(
        segmentType: _segmentType,
        label: _labelCtrl.text.trim(),
        startLat: startLat,
        startLon: startLon,
        endLat: endLat,
        endLon: endLon,
        insertAfterIndex: widget.insertAfterIndex,
      );
    }

    if (mounted) Navigator.of(context).pop();
  }

  String? _validateCoord(String? v) {
    if (v == null || v.trim().isEmpty) return 'Required';
    if (double.tryParse(v.trim()) == null) return 'Invalid number';
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final isEdit = widget.editSegment != null;
    return AlertDialog(
      title: Text(isEdit ? 'Edit Segment' : 'Add Segment'),
      content: SingleChildScrollView(
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
                  onSelectionChanged: (s) =>
                      setState(() => _segmentType = s.first),
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
              const SizedBox(height: 16),
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
            ],
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
