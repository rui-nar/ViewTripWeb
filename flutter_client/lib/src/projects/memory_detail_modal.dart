// ignore_for_file: deprecated_member_use
import 'package:flutter/material.dart';

import 'memory_dialog.dart';
import 'project_notifier.dart';

/// Shows a detail view for a memory — photo mosaic, date, description,
/// prev/next navigation and edit/delete controls.
///
/// Desktop (≥640px): two-column split — photo mosaic left, content right.
/// Mobile (<640px): hero photo on top, scrollable content below.
void showMemoryDetail(
  BuildContext context,
  ProjectNotifier notifier,
  Map<String, dynamic> memory, {
  bool readOnly = false,
}) {
  showDialog(
    context: context,
    useRootNavigator: true,
    builder: (_) =>
        _MemoryDetailModal(notifier: notifier, memory: memory, readOnly: readOnly),
  );
}

// ── Design tokens ─────────────────────────────────────────────────────────────
const _kBg     = Color(0xFF0F1A26);
const _kBgDark = Color(0xFF0C1722);
const _kBorder = Color(0xFF1F2F42);
const _kText1  = Color(0xFFE2E8F0);
const _kText2  = Color(0xFFCBD5E1);
const _kDim    = Color(0xFF64748B);
const _kOrange = Color(0xFFFC4C02);
const _kBlue   = Color(0xFF1D4ED8);
const _kRed    = Color(0xFFEF4444);

class _MemoryDetailModal extends StatefulWidget {
  final ProjectNotifier notifier;
  final Map<String, dynamic> memory;
  final bool readOnly;

  const _MemoryDetailModal({
    required this.notifier,
    required this.memory,
    this.readOnly = false,
  });

  @override
  State<_MemoryDetailModal> createState() => _MemoryDetailModalState();
}

class _MemoryDetailModalState extends State<_MemoryDetailModal> {
  late Map<String, dynamic> _current;
  int _photoViewerIndex = -1;

  static const _months = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ];

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
      builder: (_) => MemoryDialog(notifier: widget.notifier, editMemory: _current),
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
    return widget.notifier.photoThumbUrl(id, uuid);
  }

  String _photoFullUrl(String uuid) {
    final id = _current['id']?.toString() ?? '';
    return widget.notifier.photoFullUrl(id, uuid);
  }

  Map<String, String> get _authHeaders => widget.notifier.photoAuthHeaders;

  @override
  Widget build(BuildContext context) {
    final photos = (_current['photos'] as List?)?.cast<String>() ?? [];
    final mems   = _allMemories;
    final idx    = _currentIndex;
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
      backgroundColor: _kBg,
      insetPadding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 880, maxHeight: 640),
        child: LayoutBuilder(
          builder: (context, constraints) {
            final wide = constraints.maxWidth >= 640;
            return wide
                ? _desktopLayout(photos, mems, idx, hasPrev, hasNext)
                : _mobileLayout(photos, mems, idx, hasPrev, hasNext);
          },
        ),
      ),
    );
  }

  // ── Desktop layout: left mosaic + right content ────────────────────────────

  Widget _desktopLayout(
    List<String> photos,
    List<Map<String, dynamic>> mems,
    int idx,
    bool hasPrev,
    bool hasNext,
  ) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(16),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Expanded(child: _photoMosaic(photos)),
          Expanded(child: _contentPane(photos, mems, idx, hasPrev, hasNext)),
        ],
      ),
    );
  }

  // ── Mobile layout: hero on top + scrollable content ────────────────────────

  Widget _mobileLayout(
    List<String> photos,
    List<Map<String, dynamic>> mems,
    int idx,
    bool hasPrev,
    bool hasNext,
  ) {
    final name        = _current['name'] as String?;
    final description = (_current['description'] as String?) ?? '';

    return ClipRRect(
      borderRadius: BorderRadius.circular(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Hero with overlaid title
          SizedBox(
            height: 260,
            child: Stack(
              fit: StackFit.expand,
              children: [
                if (photos.isNotEmpty)
                  Image.network(
                    _photoThumbUrl(photos[0]),
                    fit: BoxFit.cover,
                    headers: _authHeaders,
                  )
                else
                  Container(
                    color: _kBgDark,
                    child: const Center(
                      child: Icon(Icons.photo_camera_outlined,
                          size: 64, color: Color(0x44CBD5E1)),
                    ),
                  ),
                // Bottom gradient
                const Positioned.fill(
                  child: DecoratedBox(
                    decoration: BoxDecoration(
                      gradient: LinearGradient(
                        begin: Alignment.topCenter,
                        end: Alignment.bottomCenter,
                        colors: [Colors.transparent, _kBg],
                        stops: [0.4, 1.0],
                      ),
                    ),
                  ),
                ),
                // Day badge
                Positioned(
                  top: 8, left: 8,
                  child: _dayBadge(_current['date'] as String?),
                ),
                // Close
                Positioned(
                  top: 4, right: 4,
                  child: IconButton(
                    icon: const Icon(Icons.close, color: _kText2),
                    onPressed: () =>
                        Navigator.of(context, rootNavigator: true).pop(),
                  ),
                ),
                // Photo count
                if (photos.length > 1)
                  Positioned(
                    top: 44, right: 8,
                    child: _photoCountChip(photos.length),
                  ),
                // Title over gradient
                if (name != null && name.isNotEmpty)
                  Positioned(
                    bottom: 12, left: 16, right: 16,
                    child: Text(
                      name,
                      style: const TextStyle(
                        color: _kText1, fontSize: 18,
                        fontWeight: FontWeight.w700, letterSpacing: -0.3,
                      ),
                    ),
                  ),
              ],
            ),
          ),
          // Scrollable body
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    _fmtDate(_current['date'] as String?).toUpperCase(),
                    style: const TextStyle(
                      color: _kOrange, fontFamily: 'monospace',
                      fontSize: 11, letterSpacing: 1.5,
                    ),
                  ),
                  if (description.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Text(description,
                        style: const TextStyle(
                            color: _kText2, fontSize: 15, height: 1.7)),
                  ],
                  if (photos.length > 1) ...[
                    const SizedBox(height: 12),
                    SizedBox(
                      height: 60,
                      child: ListView.separated(
                        scrollDirection: Axis.horizontal,
                        itemCount: photos.length,
                        separatorBuilder: (_, __) => const SizedBox(width: 6),
                        itemBuilder: (_, i) => GestureDetector(
                          onTap: () => setState(() => _photoViewerIndex = i),
                          child: ClipRRect(
                            borderRadius: BorderRadius.circular(6),
                            child: Image.network(
                              _photoThumbUrl(photos[i]),
                              width: 60, height: 60, fit: BoxFit.cover,
                              headers: _authHeaders,
                            ),
                          ),
                        ),
                      ),
                    ),
                  ],
                  const SizedBox(height: 12),
                ],
              ),
            ),
          ),
          _footerRow(),
        ],
      ),
    );
  }

  // ── Photo mosaic (desktop left pane) ──────────────────────────────────────

  Widget _photoMosaic(List<String> photos) {
    return Container(
      color: _kBgDark,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Expanded(
            child: Stack(
              fit: StackFit.expand,
              children: [
                if (photos.isNotEmpty)
                  Image.network(
                    _photoThumbUrl(photos[0]),
                    fit: BoxFit.cover,
                    headers: _authHeaders,
                  )
                else
                  const Center(
                    child: Icon(Icons.photo_camera_outlined,
                        size: 64, color: Color(0x44CBD5E1)),
                  ),
                Positioned(
                  top: 8, left: 8,
                  child: _dayBadge(_current['date'] as String?),
                ),
                if (photos.length > 1)
                  Positioned(
                    top: 8, right: 8,
                    child: _photoCountChip(photos.length),
                  ),
              ],
            ),
          ),
          // Up to 2 thumbnails below hero
          if (photos.length > 1)
            Padding(
              padding: const EdgeInsets.all(8),
              child: Row(
                children: [
                  for (int i = 1; i <= 2 && i < photos.length; i++) ...[
                    if (i > 1) const SizedBox(width: 6),
                    Expanded(
                      child: GestureDetector(
                        onTap: () => setState(() => _photoViewerIndex = i),
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(6),
                          child: SizedBox(
                            height: 60,
                            child: Image.network(
                              _photoThumbUrl(photos[i]),
                              fit: BoxFit.cover,
                              headers: _authHeaders,
                            ),
                          ),
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ),
        ],
      ),
    );
  }

  // ── Content pane (desktop right pane) ─────────────────────────────────────

  Widget _contentPane(
    List<String> photos,
    List<Map<String, dynamic>> mems,
    int idx,
    bool hasPrev,
    bool hasNext,
  ) {
    final theme       = Theme.of(context);
    final name        = _current['name'] as String?;
    final dateStr     = _current['date'] as String?;
    final description = (_current['description'] as String?) ?? '';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(8, 8, 8, 0),
          child: _navRow(mems, idx, hasPrev, hasNext),
        ),
        const SizedBox(height: 16),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20),
          child: Text(
            _fmtDate(dateStr).toUpperCase(),
            style: const TextStyle(
              color: _kOrange, fontFamily: 'monospace',
              fontSize: 11, letterSpacing: 1.5,
            ),
          ),
        ),
        const SizedBox(height: 6),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20),
          child: Text(
            (name != null && name.isNotEmpty) ? name : _fmtDate(dateStr),
            style: theme.textTheme.headlineMedium?.copyWith(
              color: _kText1,
              fontWeight: FontWeight.w700,
              fontSize: 22,
              letterSpacing: -0.3,
            ),
          ),
        ),
        const SizedBox(height: 12),
        if (description.isNotEmpty)
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: SingleChildScrollView(
                child: Text(
                  description,
                  style: const TextStyle(
                      color: _kText2, fontSize: 15, height: 1.7),
                ),
              ),
            ),
          )
        else
          const Spacer(),
        _footerRow(),
      ],
    );
  }

  // ── Shared helpers ────────────────────────────────────────────────────────

  Widget _navRow(
      List<Map<String, dynamic>> mems, int idx, bool hasPrev, bool hasNext) {
    return Row(
      children: [
        IconButton(
          icon: const Icon(Icons.chevron_left, color: _kText2),
          visualDensity: VisualDensity.compact,
          onPressed: hasPrev ? () => _navigate(-1) : null,
        ),
        IconButton(
          icon: const Icon(Icons.chevron_right, color: _kText2),
          visualDensity: VisualDensity.compact,
          onPressed: hasNext ? () => _navigate(1) : null,
        ),
        if (mems.isNotEmpty)
          Text(
            '${idx + 1} / ${mems.length}',
            style: const TextStyle(color: _kDim, fontSize: 13),
          ),
        const Spacer(),
        IconButton(
          icon: const Icon(Icons.close, color: _kText2),
          visualDensity: VisualDensity.compact,
          onPressed: () => Navigator.of(context, rootNavigator: true).pop(),
        ),
      ],
    );
  }

  Widget _footerRow() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: const BoxDecoration(
        color: _kBgDark,
        border: Border(top: BorderSide(color: _kBorder)),
      ),
      child: Row(
        children: [
          if (!widget.readOnly)
            OutlinedButton.icon(
              style: OutlinedButton.styleFrom(
                foregroundColor: _kRed,
                side: const BorderSide(color: _kRed),
              ),
              icon: const Icon(Icons.delete_outline, size: 16),
              label: const Text('Delete'),
              onPressed: _delete,
            ),
          const Spacer(),
          if (!widget.readOnly)
            ElevatedButton.icon(
              style: ElevatedButton.styleFrom(
                backgroundColor: _kBlue,
                foregroundColor: Colors.white,
              ),
              icon: const Icon(Icons.edit_outlined, size: 16),
              label: const Text('Edit memory'),
              onPressed: _edit,
            ),
        ],
      ),
    );
  }

  static Widget _dayBadge(String? dateStr) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: _kBgDark,
        border: Border.all(color: _kBorder),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        _fmtDate(dateStr),
        style: const TextStyle(
          color: _kText2, fontSize: 11, fontWeight: FontWeight.w500),
      ),
    );
  }

  static Widget _photoCountChip(int count) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: const Color(0xCC0C1722),
        border: Border.all(color: _kBorder),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.photo_library_outlined, size: 12, color: _kText2),
          const SizedBox(width: 4),
          Text('$count photos',
              style: const TextStyle(color: _kText2, fontSize: 11)),
        ],
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
            Positioned(
              top: 16, right: 16,
              child: IconButton(
                icon: const Icon(Icons.close, color: Colors.white),
                onPressed: widget.onClose,
              ),
            ),
            if (widget.photos.length > 1)
              Positioned(
                left: 8, top: 0, bottom: 0,
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
            if (widget.photos.length > 1)
              Positioned(
                right: 8, top: 0, bottom: 0,
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
            Positioned(
              bottom: 16, left: 0, right: 0,
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
