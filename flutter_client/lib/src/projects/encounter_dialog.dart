/// Dialog to create or edit an encounter (issue #40): pick/create a person, a
/// day, an optional place (defaults to the day's location) and a note.
library;

import 'package:flutter/material.dart';

import '../core/design_tokens.dart';
import 'location_picker_dialog.dart';
import 'people_search.dart';
import 'person_form_dialog.dart';
import 'project_notifier.dart';

class EncounterDialog extends StatefulWidget {
  final ProjectNotifier notifier;
  final Map<String, dynamic>? editEntry; // the encounter map from items
  final String? initialDate;
  final int? initialPersonId;
  final int? insertAfterIndex;

  const EncounterDialog({
    super.key,
    required this.notifier,
    this.editEntry,
    this.initialDate,
    this.initialPersonId,
    this.insertAfterIndex,
  });

  @override
  State<EncounterDialog> createState() => _EncounterDialogState();
}

class _EncounterDialogState extends State<EncounterDialog> {
  late TextEditingController _descCtrl;
  int? _personId;
  DateTime? _date;
  TimeOfDay? _time;
  String _geoMode = 'start_of_day';
  double? _customLat;
  double? _customLon;
  bool _saving = false;

  static const _months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  static String _fmtDate(DateTime d) => '${_months[d.month - 1]} ${d.day}, ${d.year}';
  static String _toIso(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
  static String _fmtTime(TimeOfDay t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

  @override
  void initState() {
    super.initState();
    final e = widget.editEntry;
    _descCtrl = TextEditingController(text: e?['description'] as String? ?? '');
    _personId = (e?['person_id'] as num?)?.toInt() ?? widget.initialPersonId;

    final ds = (e?['date'] as String?) ?? widget.initialDate;
    if (ds != null) _date = DateTime.tryParse(ds);

    if (e != null) {
      final ts = e['time'] as String?;
      if (ts != null) {
        final parts = ts.split(':');
        if (parts.length == 2) {
          _time = TimeOfDay(
            hour: int.tryParse(parts[0]) ?? 0,
            minute: int.tryParse(parts[1]) ?? 0,
          );
        }
      }
      _geoMode = e['geo_mode'] as String? ?? 'start_of_day';
      _customLat = (e['lat'] as num?)?.toDouble();
      _customLon = (e['lon'] as num?)?.toDouble();
    }
  }

  @override
  void dispose() {
    _descCtrl.dispose();
    super.dispose();
  }

  Future<void> _createPersonInline() async {
    final newId = await showPersonFormDialog(context, widget.notifier);
    if (newId != null && mounted) setState(() => _personId = newId);
  }

  Future<void> _pickCustomLocation() async {
    final result = await showDialog<LatLonResult>(
      context: context,
      useRootNavigator: true,
      builder: (_) => LocationPickerDialog(
        title: 'Pick encounter location',
        initialLat: _customLat,
        initialLon: _customLon,
        geo: widget.notifier.geo,
      ),
    );
    if (result != null && mounted) {
      setState(() {
        _customLat = result.lat;
        _customLon = result.lon;
      });
    }
  }

  Future<void> _save() async {
    if (_personId == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Pick a person')),
      );
      return;
    }
    if (_date == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('A date is required')),
      );
      return;
    }
    setState(() => _saving = true);
    final navigator = Navigator.of(context);
    final dateStr = _toIso(_date!);
    final timeStr = _time != null ? _fmtTime(_time!) : null;
    final desc = _descCtrl.text.trim().isEmpty ? null : _descCtrl.text.trim();
    final lat = _geoMode == 'custom' ? _customLat : null;
    final lon = _geoMode == 'custom' ? _customLon : null;

    final e = widget.editEntry;
    if (e != null) {
      await widget.notifier.updateEncounter(
        e['id'].toString(),
        personId: _personId!,
        date: dateStr,
        geoMode: _geoMode,
        time: timeStr,
        description: desc,
        lat: lat,
        lon: lon,
      );
    } else {
      await widget.notifier.createEncounter(
        personId: _personId!,
        date: dateStr,
        geoMode: _geoMode,
        time: timeStr,
        description: desc,
        lat: lat,
        lon: lon,
        insertAfterIndex: widget.insertAfterIndex,
      );
    }
    if (mounted) navigator.pop();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isEdit = widget.editEntry != null;
    final people = widget.notifier.people;

    return AlertDialog(
      title: Text(isEdit ? 'Edit encounter' : 'Add encounter'),
      content: SizedBox(
        width: 460,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Person picker + inline create
              Text('Person *', style: theme.textTheme.labelMedium),
              const SizedBox(height: 4),
              Row(
                children: [
                  Expanded(
                    child: DropdownButtonFormField<int>(
                      initialValue: people.any((p) => p['id'] == _personId)
                          ? _personId
                          : null,
                      isExpanded: true,
                      decoration: const InputDecoration(
                        isDense: true,
                        border: OutlineInputBorder(),
                        hintText: 'Select a person',
                      ),
                      items: [
                        for (final p in people)
                          DropdownMenuItem<int>(
                            value: (p['id'] as num).toInt(),
                            child: Text(personDisplayName(p),
                                overflow: TextOverflow.ellipsis),
                          ),
                      ],
                      onChanged: (v) => setState(() => _personId = v),
                    ),
                  ),
                  IconButton(
                    tooltip: 'New person',
                    icon: const Icon(Icons.person_add_alt_1),
                    color: kAccent,
                    onPressed: _createPersonInline,
                  ),
                ],
              ),
              const SizedBox(height: 12),
              // Date
              Text('Date *', style: theme.textTheme.labelMedium),
              InkWell(
                borderRadius: BorderRadius.circular(8),
                onTap: () async {
                  final picked = await showDatePicker(
                    context: context,
                    useRootNavigator: true,
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
                      Text(_date == null ? 'Select date…' : _fmtDate(_date!),
                          style: theme.textTheme.bodyMedium?.copyWith(
                            color: _date == null ? theme.colorScheme.error : null,
                          )),
                    ],
                  ),
                ),
              ),
              // Time
              InkWell(
                borderRadius: BorderRadius.circular(8),
                onTap: () async {
                  final picked = await showTimePicker(
                    context: context,
                    useRootNavigator: true,
                    initialTime: _time ?? TimeOfDay.now(),
                  );
                  if (picked != null) setState(() => _time = picked);
                },
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Row(
                    children: [
                      Icon(Icons.access_time, size: 18,
                          color: theme.colorScheme.onSurfaceVariant),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(_time == null ? 'Time (optional)' : _fmtTime(_time!),
                            style: theme.textTheme.bodyMedium?.copyWith(
                              color: _time == null
                                  ? theme.colorScheme.onSurfaceVariant
                                  : null,
                            )),
                      ),
                      if (_time != null)
                        IconButton(
                          icon: const Icon(Icons.close, size: 16),
                          visualDensity: VisualDensity.compact,
                          onPressed: () => setState(() => _time = null),
                        ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _descCtrl,
                decoration: const InputDecoration(
                  labelText: 'Note',
                  hintText: 'How you met, what you talked about…',
                ),
                minLines: 2,
                maxLines: 6,
              ),
              const SizedBox(height: 16),
              Text('Location', style: theme.textTheme.labelMedium),
              const SizedBox(height: 6),
              SizedBox(
                width: double.infinity,
                child: SegmentedButton<String>(
                  segments: const [
                    ButtonSegment(value: 'start_of_day', label: Text('Start of day')),
                    ButtonSegment(value: 'end_of_day',   label: Text('End of day')),
                    ButtonSegment(value: 'custom',        label: Text('Custom')),
                  ],
                  selected: {_geoMode},
                  onSelectionChanged: (s) => setState(() => _geoMode = s.first),
                  multiSelectionEnabled: false,
                ),
              ),
              if (_geoMode == 'custom') ...[
                const SizedBox(height: 8),
                OutlinedButton.icon(
                  icon: const Icon(Icons.location_on_outlined, size: 16),
                  label: Text(_customLat == null
                      ? 'Pick on map'
                      : '${_customLat!.toStringAsFixed(5)}, ${_customLon!.toStringAsFixed(5)}'),
                  onPressed: _pickCustomLocation,
                ),
              ],
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
          style: ElevatedButton.styleFrom(minimumSize: const Size(80, 44)),
          onPressed: _saving ? null : _save,
          child: _saving
              ? const SizedBox(
                  width: 18, height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2))
              : const Text('Save'),
        ),
      ],
    );
  }
}
