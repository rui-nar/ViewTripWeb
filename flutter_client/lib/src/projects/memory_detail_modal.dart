// ignore_for_file: deprecated_member_use
import 'package:flutter/material.dart';

import 'memory_dialog.dart';
import 'project_notifier.dart';

/// Shows a detail view for a memory — name, date/time, description, thumbnail
/// strip with navigation arrows, and edit/delete controls.
///
/// Opens as a dialog via [showMemoryDetail].
void showMemoryDetail(
  BuildContext context,
  ProjectNotifier notifier,
  Map<String, dynamic> memory,
) {
  showDialog(
    context: context,
    useRootNavigator: true,
    builder: (_) => _MemoryDetailModal(notifier: notifier, memory: memory),
  );
}

class _MemoryDetailModal extends StatefulWidget {
  final ProjectNotifier notifier;
  final Map<String, dynamic> memory;

  const _MemoryDetailModal({required this.notifier, required this.memory});

  @override
  State<_MemoryDetailModal> createState() => _MemoryDetailModalState();
}

class _MemoryDetailModalState extends State<_MemoryDetailModal> {
  late Map<String, dynamic> _current;
  int _photoViewerIndex = -1; // -1 = closed

  static const _months = ['Jan','Feb','Mar','Apr','May','Jun',
                           'Jul','Aug','Sep','Oct','Nov','Dec'];

  static String _fmtDate(String? ds) {
    if (ds == null) return '';
    final d = DateTime.tryParse(ds);
    if (d == null) return ds;
    return '${_months[d.month - 1]} ${d.day}, ${d.year}';
  }

  @override
  void initState() {
    super.initState();
    _current = widget.memory;
  }

  List<Map<String, dynamic>> get _allMemories => widget.notifier.items
      .where((i) => i['item_type'] == 'memory')
      .map((i) => i['memory'] as Map<String, dynamic>?)
      .whereType<Map<String, dynamic>>()
      .toList();

  int get _currentIndex {
    final id = _current['id']?.toString();
    return _allMemories.indexWhere((m) => m['id']?.toString() == id);
  }

  void _navigate(int delta) {
    final mems = _allMemories;
    if (mems.isEmpty) return;
    final next = (_currentIndex + delta).clamp(0, mems.length - 1);
    setState(() => _current = mems[next]);
  }

  Future<void> _edit() async {
    Navigator.of(context, rootNavigator: true).pop();
    await showDialog(
      context: context,
      useRootNavigator: true,
      builder: (_) => MemoryDialog(
        notifier: widget.notifier,
        editMemory: _current,
      ),
    );
  }

  Future<void> _delete() async {
    final confirmed = await showDialog<bool>(
      context: context,
      useRootNavigator: true,
      builder: (_) => AlertDialog(
        title: const Text('Delete memory?'),
        content: const Text('This will also delete all attached photos.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.of(context).pop(true),
            style: ElevatedButton.styleFrom(
              backgroundColor: Theme.of(context).colorScheme.error,
              foregroundColor: Theme.of(context).colorScheme.onError,
            ),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      await widget.notifier.deleteMemory(_current['id']?.toString() ?? '');
      if (mounted) Navigator.of(context, rootNavigator: true).pop();
    }
  }

  String _photoThumbUrl(String uuid) {
    final id = _current['id']?.toString() ?? '';
    return '${widget.notifier.apiBaseUrl}/api/memories/$id/photos/$uuid/thumb';
  }

  String _photoFullUrl(String uuid) {
    final id = _current['id']?.toString() ?? '';
    return '${widget.notifier.apiBaseUrl}/api/memories/$id/photos/$uuid';
  }

  Map<String, String> get _authHeaders {
    final token = widget.notifier.apiToken;
    return token != null ? {'Authorization': 'Bearer $token'} : {};
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final photos = (_current['photos'] as List?)?.cast<String>() ?? [];
    final mems = _allMemories;
    final idx = _currentIndex;
    final hasPrev = idx > 0;
    final hasNext = idx < mems.length - 1;

    if (_photoViewerIndex >= 0) {
      return _PhotoViewer(
        photos: photos,
        initialIndex: _photoViewerIndex,
        fullUrlOf: _photoFullUrl,
        authHeaders: _authHeaders,
        onClose: () => setState(() => _photoViewerIndex = -1),
      );
    }

    return Dialog(
      insetPadding: const EdgeInsets.all(24),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 500),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // ── Header ─────────────────────────────────────────────────
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 16, 8, 0),
              child: Row(
                children: [
                  const Icon(Icons.photo_camera_outlined, size: 20),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      _current['name'] as String? ??
                          _fmtDate(_current['date'] as String?),
                      style: theme.textTheme.titleMedium,
                    ),
                  ),
                  IconButton(
                    icon: const Icon(Icons.close),
                    onPressed: () =>
                        Navigator.of(context, rootNavigator: true).pop(),
                  ),
                ],
              ),
            ),
            // Date + time
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 4, 20, 0),
              child: Text(
                [
                  _fmtDate(_current['date'] as String?),
                  if (_current['time'] != null) _current['time'] as String,
                ].join(' · '),
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ),

            // ── Description ────────────────────────────────────────────
            if ((_current['description'] as String?)?.isNotEmpty == true) ...[
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 12, 20, 0),
                child: Text(_current['description'] as String),
              ),
            ],

            // ── Thumbnail strip ────────────────────────────────────────
            if (photos.isNotEmpty) ...[
              const SizedBox(height: 12),
              SizedBox(
                height: 90,
                child: ListView.separated(
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  scrollDirection: Axis.horizontal,
                  itemCount: photos.length,
                  separatorBuilder: (_, __) => const SizedBox(width: 8),
                  itemBuilder: (_, i) => GestureDetector(
                    onTap: () => setState(() => _photoViewerIndex = i),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(8),
                      child: Image.network(
                        _photoThumbUrl(photos[i]),
                        width: 90,
                        height: 90,
                        fit: BoxFit.cover,
                        headers: _authHeaders,
                      ),
                    ),
                  ),
                ),
              ),
            ],

            // ── Navigation + actions ───────────────────────────────────
            Padding(
              padding: const EdgeInsets.fromLTRB(8, 12, 8, 8),
              child: Row(
                children: [
                  IconButton(
                    icon: const Icon(Icons.chevron_left),
                    tooltip: 'Previous memory',
                    onPressed: hasPrev ? () => _navigate(-1) : null,
                  ),
                  IconButton(
                    icon: const Icon(Icons.chevron_right),
                    tooltip: 'Next memory',
                    onPressed: hasNext ? () => _navigate(1) : null,
                  ),
                  if (mems.isNotEmpty)
                    Text(
                      '${idx + 1} / ${mems.length}',
                      style: theme.textTheme.bodySmall,
                    ),
                  const Spacer(),
                  TextButton.icon(
                    icon: const Icon(Icons.edit_outlined, size: 16),
                    label: const Text('Edit'),
                    onPressed: _edit,
                  ),
                  const SizedBox(width: 4),
                  TextButton.icon(
                    icon: Icon(Icons.delete_outline, size: 16,
                        color: theme.colorScheme.error),
                    label: Text('Delete',
                        style: TextStyle(color: theme.colorScheme.error)),
                    onPressed: _delete,
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ── Full-screen photo viewer ──────────────────────────────────────────────────

class _PhotoViewer extends StatefulWidget {
  final List<String> photos;
  final int initialIndex;
  final String Function(String uuid) fullUrlOf;
  final Map<String, String> authHeaders;
  final VoidCallback onClose;

  const _PhotoViewer({
    required this.photos,
    required this.initialIndex,
    required this.fullUrlOf,
    required this.authHeaders,
    required this.onClose,
  });

  @override
  State<_PhotoViewer> createState() => _PhotoViewerState();
}

class _PhotoViewerState extends State<_PhotoViewer> {
  late final PageController _page;

  @override
  void initState() {
    super.initState();
    _page = PageController(initialPage: widget.initialIndex);
  }

  @override
  void dispose() {
    _page.dispose();
    super.dispose();
  }

  int get _current => _page.hasClients
      ? (_page.page?.round() ?? widget.initialIndex)
      : widget.initialIndex;

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: Colors.black,
      insetPadding: EdgeInsets.zero,
      child: SizedBox.expand(
        child: Stack(
          children: [
            // Photo pages
            PageView.builder(
              controller: _page,
              itemCount: widget.photos.length,
              onPageChanged: (_) => setState(() {}),
              itemBuilder: (_, i) => Image.network(
                widget.fullUrlOf(widget.photos[i]),
                fit: BoxFit.contain,
                headers: widget.authHeaders,
              ),
            ),
            // Close button
            Positioned(
              top: 16, right: 16,
              child: IconButton(
                icon: const Icon(Icons.close, color: Colors.white),
                onPressed: widget.onClose,
              ),
            ),
            // Prev arrow
            if (widget.photos.length > 1)
              Positioned(
                left: 8,
                top: 0, bottom: 0,
                child: Center(
                  child: IconButton(
                    icon: const Icon(Icons.chevron_left,
                        color: Colors.white, size: 40),
                    onPressed: _current > 0
                        ? () => _page.previousPage(
                              duration: const Duration(milliseconds: 200),
                              curve: Curves.easeInOut,
                            )
                        : null,
                  ),
                ),
              ),
            // Next arrow
            if (widget.photos.length > 1)
              Positioned(
                right: 8,
                top: 0, bottom: 0,
                child: Center(
                  child: IconButton(
                    icon: const Icon(Icons.chevron_right,
                        color: Colors.white, size: 40),
                    onPressed: _current < widget.photos.length - 1
                        ? () => _page.nextPage(
                              duration: const Duration(milliseconds: 200),
                              curve: Curves.easeInOut,
                            )
                        : null,
                  ),
                ),
              ),
            // Index indicator
            Positioned(
              bottom: 16,
              left: 0, right: 0,
              child: Center(
                child: Text(
                  '${_current + 1} / ${widget.photos.length}',
                  style: const TextStyle(color: Colors.white70),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
