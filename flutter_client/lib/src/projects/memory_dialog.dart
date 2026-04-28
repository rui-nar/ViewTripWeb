import 'package:file_picker/file_picker.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../api/client.dart';
import 'location_picker_dialog.dart';
import 'project_notifier.dart';

/// Dialog to create or edit a memory.
///
/// Pass [editMemory] (the existing memory map from `items`) to open in edit mode.
/// Pass [initialDate] to pre-fill the date picker (e.g. from the day header button).
class MemoryDialog extends StatefulWidget {
  final ProjectNotifier notifier;
  final Map<String, dynamic>? editMemory;
  final String? initialDate;
  final int? insertAfterIndex;

  const MemoryDialog({
    super.key,
    required this.notifier,
    this.editMemory,
    this.initialDate,
    this.insertAfterIndex,
  });

  @override
  State<MemoryDialog> createState() => _MemoryDialogState();
}

class _MemoryDialogState extends State<MemoryDialog> {
  late TextEditingController _nameCtrl;
  late TextEditingController _descCtrl;
  DateTime? _date;
  TimeOfDay? _time;
  String _geoMode = 'start_of_day';
  double? _customLat;
  double? _customLon;
  bool _saving = false;

  // Existing photos (UUIDs from the server, for edit mode)
  List<String> _existingPhotos = [];
  // Pending new photos to upload after save
  final List<({Uint8List bytes, String filename})> _pendingPhotos = [];
  // Photos to delete on save (edit mode)
  final Set<String> _photosToDelete = {};

  static const _months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  static String _fmtDate(DateTime d) => '${_months[d.month - 1]} ${d.day}, ${d.year}';
  static String _toIso(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
  static String _fmtTime(TimeOfDay t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

  @override
  void initState() {
    super.initState();
    final mem = widget.editMemory;
    _nameCtrl = TextEditingController(text: mem?['name'] as String? ?? '');
    _descCtrl = TextEditingController(text: mem?['description'] as String? ?? '');

    // Date: edit → from memory; create → initialDate or null
    if (mem != null) {
      final ds = mem['date'] as String?;
      if (ds != null) _date = DateTime.tryParse(ds);
    } else if (widget.initialDate != null) {
      _date = DateTime.tryParse(widget.initialDate!);
    }

    // Time
    if (mem != null) {
      final ts = mem['time'] as String?;
      if (ts != null) {
        final parts = ts.split(':');
        if (parts.length == 2) {
          _time = TimeOfDay(
            hour: int.tryParse(parts[0]) ?? 0,
            minute: int.tryParse(parts[1]) ?? 0,
          );
        }
      }
    }

    // Geo mode
    if (mem != null) {
      _geoMode = mem['geo_mode'] as String? ?? 'start_of_day';
      _customLat = (mem['lat'] as num?)?.toDouble();
      _customLon = (mem['lon'] as num?)?.toDouble();
    }

    // Existing photos
    if (mem != null) {
      final rawPhotos = mem['photos'];
      if (rawPhotos is List) {
        _existingPhotos = rawPhotos.cast<String>();
      }
    }
  }

  @override
  void dispose() {
    _nameCtrl.dispose();
    _descCtrl.dispose();
    super.dispose();
  }

  Future<void> _pickPhotos() async {
    final result = await FilePicker.pickFiles(
      allowMultiple: true,
      type: FileType.image,
      withData: true,
    );
    if (result == null) return;
    for (final f in result.files) {
      if (f.bytes != null) {
        setState(() {
          _pendingPhotos.add((bytes: f.bytes!, filename: f.name));
        });
      }
    }
  }

  Future<void> _pickCustomLocation() async {
    final result = await showDialog<LatLonResult>(
      context: context,
      useRootNavigator: true,
      builder: (_) => LocationPickerDialog(
        title: 'Pick memory location',
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
    if (_date == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('A date is required')),
      );
      return;
    }
    setState(() => _saving = true);
    try {
      final dateStr = _toIso(_date!);
      final timeStr = _time != null ? _fmtTime(_time!) : null;
      final name = _nameCtrl.text.trim().isEmpty ? null : _nameCtrl.text.trim();
      final desc = _descCtrl.text.trim().isEmpty ? null : _descCtrl.text.trim();

      final mem = widget.editMemory;
      if (mem != null) {
        // Edit mode
        final memId = mem['id']?.toString() ?? '';

        // Delete removed photos first
        for (final uuid in _photosToDelete) {
          await widget.notifier.deleteMemoryPhoto(memId, uuid);
        }

        await widget.notifier.updateMemory(
          memId,
          date: dateStr,
          geoMode: _geoMode,
          name: name,
          time: timeStr,
          description: desc,
          lat: _geoMode == 'custom' ? _customLat : null,
          lon: _geoMode == 'custom' ? _customLon : null,
        );

        // Upload new photos
        for (final p in _pendingPhotos) {
          await widget.notifier.uploadMemoryPhoto(memId, p.bytes, p.filename);
        }

        // Final reload to pick up all changes
        if (widget.notifier.projectName != null) {
          // already done inside updateMemory → _silentReload
        }
      } else {
        // Create mode — we need the new memory's ID to upload photos.
        // Create first, then use _silentReload to get the ID, then upload.
        await widget.notifier.createMemory(
          date: dateStr,
          geoMode: _geoMode,
          name: name,
          time: timeStr,
          description: desc,
          lat: _geoMode == 'custom' ? _customLat : null,
          lon: _geoMode == 'custom' ? _customLon : null,
          insertAfterIndex: widget.insertAfterIndex,
        );

        // If there are pending photos, find the newly created memory ID
        if (_pendingPhotos.isNotEmpty) {
          final newMemory = widget.notifier.items
              .where((i) => i['item_type'] == 'memory')
              .map((i) => i['memory'] as Map<String, dynamic>?)
              .where((m) =>
                  m != null &&
                  m['date'] == dateStr &&
                  m['id']?.toString() != '__optimistic__')
              .lastOrNull;

          if (newMemory != null) {
            final memId = newMemory['id']?.toString() ?? '';
            for (final p in _pendingPhotos) {
              await widget.notifier.uploadMemoryPhoto(memId, p.bytes, p.filename);
            }
          }
        }
      }

      if (mounted) Navigator.of(context).pop();
    } on ApiException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed: ${e.body}')),
        );
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  String _photoThumbUrl(String memoryId, String uuid) =>
      '${api.baseUrl}/api/memories/$memoryId/photos/$uuid/thumb';

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isEdit = widget.editMemory != null;
    final memId = widget.editMemory?['id']?.toString();

    return AlertDialog(
      title: Text(isEdit ? 'Edit Memory' : 'Add Memory'),
      content: SizedBox(
        width: 480,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Name
              TextField(
                controller: _nameCtrl,
                decoration: const InputDecoration(
                  labelText: 'Title (optional)',
                  hintText: 'e.g. Sunrise at Col du Tourmalet',
                ),
              ),
              const SizedBox(height: 12),
              // Date
              Text('Date *', style: theme.textTheme.labelMedium),
              const SizedBox(height: 4),
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
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Row(
                    children: [
                      Icon(Icons.calendar_today, size: 18,
                          color: theme.colorScheme.onSurfaceVariant),
                      const SizedBox(width: 12),
                      Text(
                        _date == null ? 'Select date…' : _fmtDate(_date!),
                        style: theme.textTheme.bodyMedium?.copyWith(
                          color: _date == null
                              ? theme.colorScheme.error
                              : null,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              // Time (optional)
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
                        child: Text(
                          _time == null
                              ? 'Time (optional)'
                              : _fmtTime(_time!),
                          style: theme.textTheme.bodyMedium?.copyWith(
                            color: _time == null
                                ? theme.colorScheme.onSurfaceVariant
                                : null,
                          ),
                        ),
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
              // Description
              TextField(
                controller: _descCtrl,
                decoration: const InputDecoration(
                  labelText: 'Description (optional)',
                  hintText: 'What happened here…',
                ),
                minLines: 2,
                maxLines: 5,
              ),
              const SizedBox(height: 16),
              // Geo mode
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
                  onSelectionChanged: (s) =>
                      setState(() => _geoMode = s.first),
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
              const SizedBox(height: 16),
              // Photos
              Text('Photos', style: theme.textTheme.labelMedium),
              const SizedBox(height: 8),
              // Existing photos (edit mode)
              if (_existingPhotos.isNotEmpty && memId != null) ...[
                SizedBox(
                  height: 80,
                  child: ListView.separated(
                    scrollDirection: Axis.horizontal,
                    itemCount: _existingPhotos.length,
                    separatorBuilder: (_, __) => const SizedBox(width: 8),
                    itemBuilder: (_, i) {
                      final uuid = _existingPhotos[i];
                      final markedForDelete = _photosToDelete.contains(uuid);
                      return Stack(
                        children: [
                          Opacity(
                            opacity: markedForDelete ? 0.3 : 1.0,
                            child: ClipRRect(
                              borderRadius: BorderRadius.circular(6),
                              child: Image.network(
                                _photoThumbUrl(memId, uuid),
                                width: 80,
                                height: 80,
                                fit: BoxFit.cover,
                                headers: api.tokenForUpload != null
                                    ? {'Authorization': 'Bearer ${api.tokenForUpload}'}
                                    : {},
                              ),
                            ),
                          ),
                          Positioned(
                            top: 2, right: 2,
                            child: GestureDetector(
                              onTap: () => setState(() {
                                if (markedForDelete) {
                                  _photosToDelete.remove(uuid);
                                } else {
                                  _photosToDelete.add(uuid);
                                }
                              }),
                              child: Container(
                                decoration: BoxDecoration(
                                  color: markedForDelete
                                      ? Colors.green
                                      : Colors.red.withValues(alpha: 0.8),
                                  shape: BoxShape.circle,
                                ),
                                child: Icon(
                                  markedForDelete ? Icons.undo : Icons.close,
                                  size: 16,
                                  color: Colors.white,
                                ),
                              ),
                            ),
                          ),
                        ],
                      );
                    },
                  ),
                ),
                const SizedBox(height: 8),
              ],
              // Pending new photos
              if (_pendingPhotos.isNotEmpty) ...[
                SizedBox(
                  height: 80,
                  child: ListView.separated(
                    scrollDirection: Axis.horizontal,
                    itemCount: _pendingPhotos.length,
                    separatorBuilder: (_, __) => const SizedBox(width: 8),
                    itemBuilder: (_, i) {
                      final p = _pendingPhotos[i];
                      return Stack(
                        children: [
                          ClipRRect(
                            borderRadius: BorderRadius.circular(6),
                            child: Image.memory(
                              p.bytes,
                              width: 80,
                              height: 80,
                              fit: BoxFit.cover,
                            ),
                          ),
                          Positioned(
                            top: 2, right: 2,
                            child: GestureDetector(
                              onTap: () =>
                                  setState(() => _pendingPhotos.removeAt(i)),
                              child: Container(
                                decoration: BoxDecoration(
                                  color: Colors.red.withValues(alpha: 0.8),
                                  shape: BoxShape.circle,
                                ),
                                child: const Icon(Icons.close, size: 16,
                                    color: Colors.white),
                              ),
                            ),
                          ),
                        ],
                      );
                    },
                  ),
                ),
                const SizedBox(height: 8),
              ],
              OutlinedButton.icon(
                icon: const Icon(Icons.add_photo_alternate_outlined, size: 18),
                label: const Text('Add photos'),
                onPressed: _pickPhotos,
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
