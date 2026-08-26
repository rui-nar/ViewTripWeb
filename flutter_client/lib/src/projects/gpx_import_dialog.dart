/// Dialog to import activities from a single GPX file (issue: GPX import).
///
/// Unlike the Strava/Polarsteps imports there is no OAuth round-trip, so this
/// is a self-contained `showDialog` modal rather than a routed screen.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../api/client.dart';
import '../core/design_tokens.dart';
import '../core/project_ref.dart';

/// (value, label) pairs for the activity-type selector — concrete lowercase
/// type strings this app already recognises (see activity_panel.dart's
/// `_ActivityIconBox._icon()`), one representative per icon/colour bucket.
const _kActivityTypes = [
  ('run', 'Run'),
  ('ride', 'Ride'),
  ('hike', 'Hike'),
  ('walk', 'Walk'),
];

IconData _typeIcon(String type) => switch (type) {
      'run' => Icons.directions_run,
      'ride' => Icons.directions_bike,
      'walk' => Icons.directions_walk,
      _ => Icons.hiking,
    };

class GpxImportDialog extends StatefulWidget {
  final ProjectRef projectRef;

  /// Injectable so tests can supply one backed by a MockClient — mirrors
  /// ApiClient's own constructor-injection pattern. `http.MultipartRequest`'s
  /// own `.send()` always spins up a fresh, un-mockable client, so this
  /// dialog routes through [httpClient] explicitly instead.
  final http.Client? httpClient;

  const GpxImportDialog({super.key, required this.projectRef, this.httpClient});

  @override
  State<GpxImportDialog> createState() => _GpxImportDialogState();
}

class _GpxImportDialogState extends State<GpxImportDialog> {
  late final http.Client _client = widget.httpClient ?? http.Client();
  Uint8List? _fileBytes;
  String? _fileName;
  DateTime? _date;
  TimeOfDay? _startTime;
  TimeOfDay? _endTime;
  String _activityType = _kActivityTypes.first.$1;
  bool _submitting = false;
  List<String>? _serverErrors;
  String? _genericError;

  static const _months = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ];
  static String _fmtDate(DateTime d) => '${_months[d.month - 1]} ${d.day}, ${d.year}';
  static String _toIso(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
  static String _fmtTime(TimeOfDay t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

  Future<void> _pickFile() async {
    final result = await FilePicker.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['gpx'],
      withData: true,
    );
    if (result == null || result.files.isEmpty) return;
    final picked = result.files.first;
    if (picked.bytes == null) return;
    setState(() {
      _fileBytes = picked.bytes;
      _fileName = picked.name;
    });
  }

  bool get _timeValid {
    if (_startTime == null || _endTime == null) return true;
    final start = _startTime!.hour * 60 + _startTime!.minute;
    final end = _endTime!.hour * 60 + _endTime!.minute;
    return end > start;
  }

  bool get _canSubmit =>
      _fileBytes != null &&
      _date != null &&
      _startTime != null &&
      _endTime != null &&
      _timeValid &&
      !_submitting;

  Future<void> _submit() async {
    if (!_canSubmit) return;
    setState(() {
      _submitting = true;
      _serverErrors = null;
      _genericError = null;
    });
    try {
      final token = api.tokenForUpload;
      final uri = Uri.parse(
          '${api.baseUrl}${widget.projectRef.path('/activities/import-gpx')}');
      final request = http.MultipartRequest('POST', uri)
        ..fields['date'] = _toIso(_date!)
        ..fields['start_time'] = _fmtTime(_startTime!)
        ..fields['end_time'] = _fmtTime(_endTime!)
        ..fields['activity_type'] = _activityType
        ..files.add(http.MultipartFile.fromBytes(
            'file', _fileBytes!, filename: _fileName ?? 'track.gpx'));
      if (token != null) request.headers['Authorization'] = 'Bearer $token';

      final streamed = await _client.send(request);
      final res = await http.Response.fromStream(streamed);

      if (res.statusCode == 200) {
        if (mounted) Navigator.of(context).pop(true);
        return;
      }
      if (res.statusCode == 422) {
        final body = jsonDecode(res.body) as Map<String, dynamic>;
        final errors =
            (body['detail'] as Map?)?['errors'] as List?;
        setState(() => _serverErrors =
            errors?.cast<String>() ?? ['The GPX file was rejected.']);
        return;
      }
      if (res.statusCode == 403) {
        setState(() => _genericError =
            "You don't have permission to add activities to this trip.");
        return;
      }
      setState(() => _genericError = 'Import failed (${res.statusCode}).');
    } catch (e) {
      setState(() => _genericError =
          'Import failed: ${e.toString().replaceFirst('Exception: ', '')}');
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  Future<void> _pickDate() async {
    final picked = await showDatePicker(
      context: context,
      useRootNavigator: true,
      initialDate: _date ?? DateTime.now(),
      firstDate: DateTime(2000),
      lastDate: DateTime(2100),
    );
    if (picked != null) setState(() => _date = picked);
  }

  Future<void> _pickTime({required bool isStart}) async {
    final current = isStart ? _startTime : _endTime;
    final picked = await showTimePicker(
      context: context,
      useRootNavigator: true,
      initialTime: current ?? TimeOfDay.now(),
    );
    if (picked == null) return;
    setState(() {
      if (isStart) {
        _startTime = picked;
      } else {
        _endTime = picked;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final dark = theme.brightness == Brightness.dark;

    return AlertDialog(
      title: const Text('Import GPX file'),
      content: SizedBox(
        width: 420,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              OutlinedButton.icon(
                icon: const Icon(Icons.attach_file, size: 18),
                label: Text(
                  _fileName ?? 'Choose .gpx file…',
                  overflow: TextOverflow.ellipsis,
                ),
                onPressed: _submitting ? null : _pickFile,
              ),
              const SizedBox(height: 16),
              Text('Date *', style: theme.textTheme.labelMedium),
              const SizedBox(height: 4),
              InkWell(
                borderRadius: BorderRadius.circular(8),
                onTap: _submitting ? null : _pickDate,
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Row(
                    children: [
                      Icon(Icons.calendar_today,
                          size: 18, color: theme.colorScheme.onSurfaceVariant),
                      const SizedBox(width: 12),
                      Text(
                        _date == null ? 'Select date…' : _fmtDate(_date!),
                        style: theme.textTheme.bodyMedium?.copyWith(
                          color: _date == null ? theme.colorScheme.error : null,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  Expanded(
                    child: _TimeField(
                      label: 'Start time *',
                      value: _startTime,
                      enabled: !_submitting,
                      onTap: () => _pickTime(isStart: true),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: _TimeField(
                      label: 'End time *',
                      value: _endTime,
                      enabled: !_submitting,
                      onTap: () => _pickTime(isStart: false),
                    ),
                  ),
                ],
              ),
              if (!_timeValid) ...[
                const SizedBox(height: 6),
                Text(
                  'End time must be after start time.',
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.error),
                ),
              ],
              const SizedBox(height: 16),
              Text('Activity type', style: theme.textTheme.labelMedium),
              const SizedBox(height: 6),
              DropdownButtonFormField<String>(
                initialValue: _activityType,
                items: [
                  for (final (value, label) in _kActivityTypes)
                    DropdownMenuItem(
                      value: value,
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            _typeIcon(value),
                            size: 16,
                            color: iconBoxFg(
                              resolveTypeStyle(activityTypeBucket(value),
                                      isSegment: false)
                                  .color,
                              dark: dark,
                            ),
                          ),
                          const SizedBox(width: 8),
                          Text(label),
                        ],
                      ),
                    ),
                ],
                onChanged: _submitting
                    ? null
                    : (v) {
                        if (v != null) setState(() => _activityType = v);
                      },
              ),
              if (_serverErrors != null) ...[
                const SizedBox(height: 12),
                Container(
                  width: double.infinity,
                  padding:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                  decoration: BoxDecoration(
                    color: theme.colorScheme.errorContainer,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      for (final e in _serverErrors!)
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 2),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Icon(Icons.error_outline,
                                  size: 16,
                                  color: theme.colorScheme.onErrorContainer),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(
                                  e,
                                  style: theme.textTheme.bodySmall?.copyWith(
                                      color: theme.colorScheme.onErrorContainer),
                                ),
                              ),
                            ],
                          ),
                        ),
                    ],
                  ),
                ),
              ],
              if (_genericError != null) ...[
                const SizedBox(height: 12),
                Text(_genericError!,
                    style: TextStyle(color: theme.colorScheme.error)),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: _submitting ? null : () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        ElevatedButton(
          style: ElevatedButton.styleFrom(minimumSize: const Size(80, 44)),
          onPressed: _canSubmit ? _submit : null,
          child: _submitting
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2))
              : const Text('Import'),
        ),
      ],
    );
  }
}

class _TimeField extends StatelessWidget {
  final String label;
  final TimeOfDay? value;
  final bool enabled;
  final VoidCallback onTap;

  const _TimeField({
    required this.label,
    required this.value,
    required this.enabled,
    required this.onTap,
  });

  static String _fmt(TimeOfDay t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return InkWell(
      borderRadius: BorderRadius.circular(8),
      onTap: enabled ? onTap : null,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(
          children: [
            Icon(Icons.access_time,
                size: 18, color: theme.colorScheme.onSurfaceVariant),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                value == null ? label : _fmt(value!),
                overflow: TextOverflow.ellipsis,
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: value == null ? theme.colorScheme.error : null,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
