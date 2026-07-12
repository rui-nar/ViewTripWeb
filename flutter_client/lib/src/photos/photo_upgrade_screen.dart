/// Review/confirm UI for the Polarsteps photo-upgrade feature (issue #33).
///
/// Memories only — that's what Polarsteps imports produce, and what issue
/// #33 is about. Phase 1's replace endpoint also exists for journal entries,
/// but wiring a UI entry point for those is out of scope here.
///
/// Photos are picked one at a time against a specific existing thumbnail
/// (rather than a bulk multi-select auto-matched in a batch): the system
/// picker has no way to pre-filter the device's photo library down to "this
/// day", so showing the exact thumbnail being replaced while the user picks
/// is what tells them which photo to look for — the day/geo/pHash checks
/// below are then just a confirmation signal, not a filter.
library;

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../core/design_tokens.dart';
import '../projects/project_notifier.dart';
import 'photo_match.dart';
import 'photo_source.dart';

/// Opens the photo-upgrade review dialog for [memory].
///
/// [pickSinglePhotoOverride] and [fetchThumbnailHashOverride] exist only so
/// widget tests can feed in known candidates/hashes without touching the
/// platform file picker or making real network calls — production callers
/// should never pass them.
void showPhotoUpgradeDialog(
  BuildContext context,
  ProjectNotifier notifier,
  Map<String, dynamic> memory, {
  @visibleForTesting Future<PickedPhoto?> Function()? pickSinglePhotoOverride,
  @visibleForTesting Future<int?> Function(String uuid)? fetchThumbnailHashOverride,
}) {
  showDialog(
    context: context,
    useRootNavigator: true,
    builder: (_) => _PhotoUpgradeDialog(
      notifier: notifier,
      memory: memory,
      pickSinglePhoto: pickSinglePhotoOverride ?? pickSinglePhotoForUpgrade,
      fetchThumbnailHash: fetchThumbnailHashOverride,
    ),
  );
}

enum _RowStatus { empty, picked, applying, applied, failed }

class _UpgradeRow {
  final String oldUuid;
  PickedPhoto? picked;
  int? thumbHash;
  bool thumbHashChecked = false;
  bool? looksSame;
  bool dateMismatch = false;
  bool comparing = false;
  _RowStatus status = _RowStatus.empty;

  _UpgradeRow(this.oldUuid);
}

class _PhotoUpgradeDialog extends StatefulWidget {
  final ProjectNotifier notifier;
  final Map<String, dynamic> memory;
  final Future<PickedPhoto?> Function() pickSinglePhoto;
  final Future<int?> Function(String uuid)? fetchThumbnailHash;

  const _PhotoUpgradeDialog({
    required this.notifier,
    required this.memory,
    required this.pickSinglePhoto,
    this.fetchThumbnailHash,
  });

  @override
  State<_PhotoUpgradeDialog> createState() => _PhotoUpgradeDialogState();
}

class _PhotoUpgradeDialogState extends State<_PhotoUpgradeDialog> {
  late final List<_UpgradeRow> _rows;
  String? _error;

  String get _memoryId => widget.memory['id']?.toString() ?? '';

  @override
  void initState() {
    super.initState();
    final existingUuids = (widget.memory['photos'] as List?)?.cast<String>() ?? [];
    _rows = [for (final uuid in existingUuids) _UpgradeRow(uuid)];
  }

  Future<int?> _fetchThumbnailHash(String uuid) async {
    if (widget.fetchThumbnailHash != null) {
      return widget.fetchThumbnailHash!(uuid);
    }
    try {
      final url = widget.notifier.photoThumbUrl(_memoryId, uuid);
      final res = await http.get(Uri.parse(url), headers: widget.notifier.photoAuthHeaders);
      if (res.statusCode < 200 || res.statusCode >= 300) return null;
      return computeAverageHash(res.bodyBytes);
    } catch (_) {
      return null;
    }
  }

  Future<void> _pickForRow(_UpgradeRow row) async {
    setState(() {
      row.comparing = true;
      _error = null;
    });
    try {
      final picked = await widget.pickSinglePhoto();
      if (picked == null) {
        setState(() => row.comparing = false);
        return;
      }

      if (!row.thumbHashChecked) {
        row.thumbHash = await _fetchThumbnailHash(row.oldUuid);
        row.thumbHashChecked = true;
      }

      final date = widget.memory['date'] as String?;
      final candidate = picked.candidate;
      final dateMismatch = date != null &&
          candidate != null &&
          selectCandidatesForDay(
            date: date,
            localOffset: Duration.zero,
            candidates: [candidate],
            memoryLat: (widget.memory['lat'] as num?)?.toDouble(),
            memoryLon: (widget.memory['lon'] as num?)?.toDouble(),
          ).isEmpty;

      setState(() {
        row.picked = picked;
        row.dateMismatch = dateMismatch;
        row.looksSame = looksLikeSamePhoto(candidate?.pHash, row.thumbHash);
        row.status = _RowStatus.picked;
        row.comparing = false;
      });
    } catch (e) {
      setState(() {
        row.comparing = false;
        _error = 'Could not process the selected photo.';
      });
    }
  }

  Future<void> _confirm(_UpgradeRow row) async {
    setState(() => row.status = _RowStatus.applying);
    final newUuid = await widget.notifier.replaceMemoryPhoto(
      _memoryId,
      row.oldUuid,
      row.picked!.bytes,
      row.picked!.filename,
    );
    if (!mounted) return;
    setState(() => row.status = newUuid != null ? _RowStatus.applied : _RowStatus.failed);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return AlertDialog(
      title: const Text('Upgrade photos'),
      content: SizedBox(
        width: 520,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                "Pick a higher-quality original from your device for each of this "
                "day's photos below.",
                style: theme.textTheme.bodyMedium,
              ),
              const SizedBox(height: 16),
              if (_error != null) ...[
                Text(_error!, style: TextStyle(color: theme.colorScheme.error)),
                const SizedBox(height: 8),
              ],
              if (_rows.isEmpty)
                Text('This memory has no photos to upgrade.', style: theme.textTheme.bodyMedium)
              else
                for (final row in _rows) _rowTile(theme, row),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Close'),
        ),
      ],
    );
  }

  Widget _rowTile(ThemeData theme, _UpgradeRow row) {
    final hasPick = row.picked != null;
    final applied = row.status == _RowStatus.applied;
    final failed = row.status == _RowStatus.failed;
    final busy = row.status == _RowStatus.applying || row.comparing;

    final warnings = [
      if (hasPick && row.picked!.candidate == null) 'No date info found in this photo.',
      if (hasPick && row.dateMismatch) "Doesn't look like this day.",
      if (hasPick && row.looksSame == false) 'Looks different from the current photo.',
    ];
    final flagged = warnings.isNotEmpty;

    return Container(
      key: ValueKey('upgrade-row-${row.oldUuid}'),
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        border: Border.all(color: flagged ? kWarning : theme.dividerColor),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(6),
                child: Image.network(
                  widget.notifier.photoThumbUrl(_memoryId, row.oldUuid),
                  width: 56,
                  height: 56,
                  fit: BoxFit.cover,
                  headers: widget.notifier.photoAuthHeaders,
                  errorBuilder: (_, __, ___) => Container(
                    width: 56,
                    height: 56,
                    color: theme.colorScheme.surfaceContainerHighest,
                    child: const Icon(Icons.photo_outlined, size: 20),
                  ),
                ),
              ),
              if (hasPick) ...[
                const SizedBox(width: 6),
                Icon(Icons.arrow_forward, size: 16, color: theme.colorScheme.onSurfaceVariant),
                const SizedBox(width: 6),
                ClipRRect(
                  borderRadius: BorderRadius.circular(6),
                  child: Image.memory(
                    row.picked!.bytes,
                    width: 56,
                    height: 56,
                    fit: BoxFit.cover,
                    errorBuilder: (_, __, ___) => Container(
                      width: 56,
                      height: 56,
                      color: theme.colorScheme.surfaceContainerHighest,
                      child: const Icon(Icons.photo_outlined, size: 20),
                    ),
                  ),
                ),
              ],
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (hasPick)
                      Text(
                        row.picked!.filename,
                        style: theme.textTheme.bodySmall,
                        overflow: TextOverflow.ellipsis,
                      ),
                    if (failed)
                      Text('Upload failed', style: TextStyle(fontSize: 11, color: theme.colorScheme.error)),
                  ],
                ),
              ),
              if (applied)
                const Icon(Icons.check_circle, color: kSuccess)
              else if (!hasPick)
                OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(minimumSize: const Size(0, 36)),
                  icon: const Icon(Icons.add_photo_alternate_outlined, size: 18),
                  label: const Text('Select picture'),
                  onPressed: busy ? null : () => _pickForRow(row),
                ),
            ],
          ),
          if (hasPick && !applied)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    onPressed: busy ? null : () => _pickForRow(row),
                    child: const Text('Change picture'),
                  ),
                  const SizedBox(width: 6),
                  ElevatedButton(
                    style: ElevatedButton.styleFrom(minimumSize: const Size(0, 36)),
                    onPressed: busy ? null : () => _confirm(row),
                    child: busy
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Text('Confirm'),
                  ),
                ],
              ),
            ),
          if (warnings.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                warnings.join(' '),
                style: theme.textTheme.bodySmall?.copyWith(color: kWarning),
              ),
            ),
        ],
      ),
    );
  }
}
