/// Review/confirm UI for the Polarsteps photo-upgrade feature (issue #33).
///
/// Memories only — that's what Polarsteps imports produce, and what issue
/// #33 is about. Phase 1's replace endpoint also exists for journal entries,
/// but wiring a UI entry point for those is out of scope here.
library;

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../core/design_tokens.dart';
import '../projects/project_notifier.dart';
import 'photo_match.dart';
import 'photo_source.dart';

/// Opens the photo-upgrade review dialog for [memory].
///
/// [pickPhotosOverride] and [fetchThumbnailHashOverride] exist only so
/// widget tests can feed in known candidates/hashes without touching the
/// platform file picker or making real network calls — production callers
/// should never pass them.
void showPhotoUpgradeDialog(
  BuildContext context,
  ProjectNotifier notifier,
  Map<String, dynamic> memory, {
  @visibleForTesting Future<List<PickedPhoto>> Function()? pickPhotosOverride,
  @visibleForTesting Future<int?> Function(String uuid)? fetchThumbnailHashOverride,
}) {
  showDialog(
    context: context,
    useRootNavigator: true,
    builder: (_) => _PhotoUpgradeDialog(
      notifier: notifier,
      memory: memory,
      pickPhotos: pickPhotosOverride ?? pickPhotosForUpgrade,
      fetchThumbnailHash: fetchThumbnailHashOverride,
    ),
  );
}

enum _SwapStatus { pending, applying, applied, failed, skipped }

class _SwapRow {
  final String oldUuid;
  final PickedPhoto photo;
  final MatchConfidence confidence;
  _SwapStatus status = _SwapStatus.pending;

  _SwapRow({
    required this.oldUuid,
    required this.photo,
    required this.confidence,
  });
}

class _PhotoUpgradeDialog extends StatefulWidget {
  final ProjectNotifier notifier;
  final Map<String, dynamic> memory;
  final Future<List<PickedPhoto>> Function() pickPhotos;
  final Future<int?> Function(String uuid)? fetchThumbnailHash;

  const _PhotoUpgradeDialog({
    required this.notifier,
    required this.memory,
    required this.pickPhotos,
    this.fetchThumbnailHash,
  });

  @override
  State<_PhotoUpgradeDialog> createState() => _PhotoUpgradeDialogState();
}

class _PhotoUpgradeDialogState extends State<_PhotoUpgradeDialog> {
  bool _loading = false;
  bool _searched = false;
  String? _error;
  List<_SwapRow> _rows = [];
  int _noExifCount = 0;
  int _noDayMatchCount = 0;

  String get _memoryId => widget.memory['id']?.toString() ?? '';

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

  Future<void> _pickAndMatch() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final picked = await widget.pickPhotos();
      if (picked.isEmpty) {
        setState(() {
          _loading = false;
          _searched = true;
        });
        return;
      }

      final matchable = picked.where((p) => p.candidate != null).toList();
      final noExifCount = picked.length - matchable.length;
      final candidateToPhoto = <PhotoCandidate, PickedPhoto>{
        for (final p in matchable) p.candidate!: p,
      };

      final date = widget.memory['date'] as String?;
      final dayFiltered = date == null
          ? <PhotoCandidate>[]
          : selectCandidatesForDay(
              date: date,
              localOffset: Duration.zero,
              candidates: candidateToPhoto.keys.toList(),
              memoryLat: (widget.memory['lat'] as num?)?.toDouble(),
              memoryLon: (widget.memory['lon'] as num?)?.toDouble(),
            );
      final noDayMatchCount = matchable.length - dayFiltered.length;

      final existingUuids = (widget.memory['photos'] as List?)?.cast<String>() ?? [];
      final thumbUuids = <String>[];
      final thumbHashes = <int>[];
      for (final uuid in existingUuids) {
        final hash = await _fetchThumbnailHash(uuid);
        if (hash != null) {
          thumbUuids.add(uuid);
          thumbHashes.add(hash);
        }
      }

      final result = pairCandidatesWithThumbnails(
        candidates: dayFiltered,
        thumbnailPHashes: thumbHashes,
      );

      final rows = [
        for (final m in result.matches)
          _SwapRow(
            oldUuid: thumbUuids[m.thumbnailIndex],
            photo: candidateToPhoto[dayFiltered[m.candidateIndex]]!,
            confidence: m.confidence,
          ),
      ];

      setState(() {
        _rows = rows;
        _noExifCount = noExifCount;
        _noDayMatchCount = noDayMatchCount;
        _loading = false;
        _searched = true;
      });
    } catch (e) {
      setState(() {
        _error = 'Could not process the selected photos.';
        _loading = false;
        _searched = true;
      });
    }
  }

  Future<void> _confirmSwap(_SwapRow row) async {
    setState(() => row.status = _SwapStatus.applying);
    final newUuid = await widget.notifier.replaceMemoryPhoto(
      _memoryId,
      row.oldUuid,
      row.photo.bytes,
      row.photo.filename,
    );
    if (!mounted) return;
    setState(() => row.status = newUuid != null ? _SwapStatus.applied : _SwapStatus.failed);
  }

  void _skipSwap(_SwapRow row) {
    setState(() => row.status = _SwapStatus.skipped);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return AlertDialog(
      title: const Text('Upgrade photos'),
      content: SizedBox(
        width: 520,
        child: _loading
            ? const SizedBox(
                height: 140,
                child: Center(child: CircularProgressIndicator()),
              )
            : SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (!_searched) _intro(theme),
                    if (_error != null) ...[
                      const SizedBox(height: 8),
                      Text(_error!, style: TextStyle(color: theme.colorScheme.error)),
                    ],
                    if (_searched) ..._results(theme),
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

  Widget _intro(ThemeData theme) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          'Pick higher-quality originals from your device. They\'ll be matched '
          "to this day's photos automatically by date, location and image "
          'similarity, for you to confirm one by one.',
          style: theme.textTheme.bodyMedium,
        ),
        const SizedBox(height: 16),
        OutlinedButton.icon(
          icon: const Icon(Icons.add_photo_alternate_outlined, size: 18),
          label: const Text('Pick photos'),
          onPressed: _pickAndMatch,
        ),
      ],
    );
  }

  List<Widget> _results(ThemeData theme) {
    final visibleRows = _rows.where((r) => r.status != _SwapStatus.skipped).toList();
    final notes = [
      if (_noExifCount > 0) '$_noExifCount photo(s) had no date info and were skipped.',
      if (_noDayMatchCount > 0) "$_noDayMatchCount photo(s) didn't match this day.",
    ];

    return [
      if (notes.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Text(
            notes.join(' '),
            style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
          ),
        ),
      if (visibleRows.isEmpty)
        Text('No matching photos found.', style: theme.textTheme.bodyMedium)
      else
        for (final row in visibleRows) _swapTile(theme, row),
      const SizedBox(height: 12),
      OutlinedButton.icon(
        icon: const Icon(Icons.add_photo_alternate_outlined, size: 18),
        label: const Text('Pick more photos'),
        onPressed: _pickAndMatch,
      ),
    ];
  }

  Widget _swapTile(ThemeData theme, _SwapRow row) {
    final isLow = row.confidence == MatchConfidence.low;
    final badgeColor = isLow ? kWarning : kSuccess;
    final applied = row.status == _SwapStatus.applied;
    final failed = row.status == _SwapStatus.failed;
    final busy = row.status == _SwapStatus.applying;

    return Container(
      key: ValueKey('swap-tile-${row.oldUuid}'),
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        border: Border.all(color: isLow ? kWarning : theme.dividerColor),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
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
          const SizedBox(width: 6),
          Icon(Icons.arrow_forward, size: 16, color: theme.colorScheme.onSurfaceVariant),
          const SizedBox(width: 6),
          ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: Image.memory(
              row.photo.bytes,
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
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: iconBoxBg(badgeColor),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    isLow ? 'Low confidence' : 'High confidence',
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                      color: iconBoxFg(badgeColor),
                    ),
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  row.photo.filename,
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
          else ...[
            TextButton(
              onPressed: busy ? null : () => _skipSwap(row),
              child: const Text('Skip'),
            ),
            ElevatedButton(
              onPressed: busy ? null : () => _confirmSwap(row),
              child: busy
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Text('Confirm'),
            ),
          ],
        ],
      ),
    );
  }
}
