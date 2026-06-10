/// Compose-and-share UI for posting a memory to social media.
///
/// Holds form state only; all decision logic lives in [SocialShareController]
/// and its injected edges. The OS share sheet is the primary action (it can
/// carry the map image + photos); WhatsApp/Facebook are text+link shortcuts.
library;

import 'package:flutter/material.dart';

import '../share/share_asset_source_impl.dart';
import '../share/share_capabilities.dart';
import '../share/share_interfaces.dart';
import '../share/share_link_resolver_impl.dart';
import '../share/share_strategy.dart';
import '../share/share_transport_impl.dart';
import '../share/social_share_controller.dart';
import 'project_notifier.dart';

/// Builds the sorted memory list and opens the share dialog.
void showSocialShareDialog(
  BuildContext context,
  ProjectNotifier notifier, {
  String? initialMemoryPublicId,
}) {
  final memories = notifier.items
      .where((i) => i['item_type'] == 'memory' && i['memory'] != null)
      .map((i) => (i['memory'] as Map).cast<String, dynamic>())
      .toList()
    ..sort((a, b) =>
        (a['date'] as String? ?? '').compareTo(b['date'] as String? ?? ''));

  if (memories.isEmpty) {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Add a memory first to share it.')),
    );
    return;
  }

  showDialog<void>(
    context: context,
    builder: (_) => SocialShareDialog(
      notifier: notifier,
      allMemories: memories,
      initialMemoryPublicId: initialMemoryPublicId,
    ),
  );
}

class SocialShareDialog extends StatefulWidget {
  final ProjectNotifier notifier;
  final List<Map<String, dynamic>> allMemories;
  final String? initialMemoryPublicId;

  const SocialShareDialog({
    super.key,
    required this.notifier,
    required this.allMemories,
    this.initialMemoryPublicId,
  });

  @override
  State<SocialShareDialog> createState() => _SocialShareDialogState();
}

class _SocialShareDialogState extends State<SocialShareDialog> {
  late SocialShareController _controller;
  late ShareCapabilities _caps;

  late Map<String, dynamic> _memory;
  bool _dayFocus = false;
  bool _includeMap = true;
  bool _includeLink = true;
  final _selectedPhotos = <String>{};
  final _textCtrl = TextEditingController();
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _caps = createShareCapabilities();
    _controller = SocialShareController(
      assets: ShareAssetSourceImpl(widget.notifier, () => context),
      links: ShareLinkResolverImpl(widget.notifier),
      transport: const ShareTransportImpl(),
      caps: _caps,
    );

    _memory = widget.allMemories.firstWhere(
      (m) => m['public_id'] == widget.initialMemoryPublicId,
      orElse: () => widget.allMemories.last,
    );
    _syncMemorySelection();
  }

  void _syncMemorySelection() {
    _selectedPhotos
      ..clear()
      ..addAll(_photosOf(_memory));
    _textCtrl.text = (_memory['description'] as String?) ?? '';
  }

  List<String> _photosOf(Map<String, dynamic> m) =>
      (m['photos'] as List?)?.cast<String>() ?? const [];

  @override
  void dispose() {
    _textCtrl.dispose();
    super.dispose();
  }

  String _memoryLabel(Map<String, dynamic> m) {
    final date = m['date'] as String? ?? '';
    final name = (m['name'] as String?)?.trim();
    return (name == null || name.isEmpty) ? date : '$date · $name';
  }

  Future<void> _share(ShareTarget target) async {
    setState(() => _busy = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      await _controller.share(
        target: target,
        memoryId: (_memory['id'] as num).toInt(),
        memoryPublicId: _memory['public_id'] as String? ?? '',
        memoryDate: _memory['date'] as String?,
        customText: _textCtrl.text,
        includeLink: _includeLink,
        includeMap: _includeMap,
        dayFocus: _dayFocus,
        selectedPhotoUuids: _selectedPhotos.toList(),
      );

      // Honest feedback when the platform couldn't attach images.
      final wantedFiles = _includeMap || _selectedPhotos.isNotEmpty;
      if (target == ShareTarget.system &&
          !_caps.canShareFiles &&
          wantedFiles) {
        messenger.showSnackBar(const SnackBar(
          content: Text(
              "Images can't be attached here — shared text + link instead."),
        ));
      }
      if (mounted) Navigator.of(context).pop();
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('Share failed: $e')));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final photos = _photosOf(_memory);

    return AlertDialog(
      title: const Text('Share memory'),
      content: SizedBox(
        width: 420,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // ── Memory selector ─────────────────────────────────────────
              InputDecorator(
                decoration: const InputDecoration(
                  labelText: 'Memory',
                  border: OutlineInputBorder(),
                  isDense: true,
                  contentPadding:
                      EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                ),
                child: DropdownButton<String>(
                  value: _memory['public_id'] as String?,
                  isExpanded: true,
                  isDense: true,
                  underline: const SizedBox.shrink(),
                  items: [
                    for (final m in widget.allMemories)
                      DropdownMenuItem(
                        value: m['public_id'] as String?,
                        child: Text(_memoryLabel(m),
                            overflow: TextOverflow.ellipsis),
                      ),
                  ],
                  onChanged: _busy
                      ? null
                      : (pid) {
                          final m = widget.allMemories.firstWhere(
                              (m) => m['public_id'] == pid,
                              orElse: () => _memory);
                          setState(() {
                            _memory = m;
                            _syncMemorySelection();
                          });
                        },
                ),
              ),
              const SizedBox(height: 12),

              // ── Toggles ─────────────────────────────────────────────────
              SwitchListTile(
                title: const Text('Include trip map'),
                value: _includeMap,
                onChanged:
                    _busy ? null : (v) => setState(() => _includeMap = v),
                contentPadding: EdgeInsets.zero,
                dense: true,
              ),
              if (_includeMap)
                SwitchListTile(
                  title: const Text('Zoom map to this day'),
                  value: _dayFocus,
                  onChanged:
                      _busy ? null : (v) => setState(() => _dayFocus = v),
                  contentPadding: const EdgeInsets.only(left: 16),
                  dense: true,
                ),

              // ── Photos ──────────────────────────────────────────────────
              if (photos.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text('Photos', style: theme.textTheme.labelLarge),
                const SizedBox(height: 6),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    for (final uuid in photos)
                      _PhotoChip(
                        url: widget.notifier
                            .photoThumbUrl(_memory['id'].toString(), uuid),
                        headers: widget.notifier.photoAuthHeaders,
                        selected: _selectedPhotos.contains(uuid),
                        onTap: _busy
                            ? null
                            : () => setState(() {
                                  if (!_selectedPhotos.remove(uuid)) {
                                    _selectedPhotos.add(uuid);
                                  }
                                }),
                      ),
                  ],
                ),
              ],
              const SizedBox(height: 12),

              // ── Post text ───────────────────────────────────────────────
              TextField(
                controller: _textCtrl,
                enabled: !_busy,
                minLines: 2,
                maxLines: 5,
                decoration: const InputDecoration(
                  labelText: 'Post text',
                  border: OutlineInputBorder(),
                  isDense: true,
                ),
              ),
              const SizedBox(height: 4),
              SwitchListTile(
                title: const Text('Include link to memory'),
                value: _includeLink,
                onChanged:
                    _busy ? null : (v) => setState(() => _includeLink = v),
                contentPadding: EdgeInsets.zero,
                dense: true,
              ),

              if (_busy)
                const Padding(
                  padding: EdgeInsets.only(top: 12),
                  child: Row(children: [
                    SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2)),
                    SizedBox(width: 12),
                    Text('Preparing…'),
                  ]),
                ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: _busy ? null : () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        // Quick links — text + link only.
        OutlinedButton.icon(
          onPressed: _busy ? null : () => _share(ShareTarget.whatsapp),
          icon: const Icon(Icons.chat_outlined, size: 18),
          label: const Text('WhatsApp'),
        ),
        OutlinedButton.icon(
          onPressed: _busy ? null : () => _share(ShareTarget.facebook),
          icon: const Icon(Icons.facebook_outlined, size: 18),
          label: const Text('Facebook'),
        ),
        // Primary — OS share sheet (carries images).
        FilledButton.icon(
          onPressed: _busy ? null : () => _share(ShareTarget.system),
          icon: const Icon(Icons.ios_share, size: 18),
          label: const Text('Share…'),
        ),
      ],
    );
  }
}

class _PhotoChip extends StatelessWidget {
  final String url;
  final Map<String, String> headers;
  final bool selected;
  final VoidCallback? onTap;

  const _PhotoChip({
    required this.url,
    required this.headers,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return InkWell(
      onTap: onTap,
      child: Stack(
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: Image.network(
              url,
              headers: headers,
              width: 64,
              height: 64,
              fit: BoxFit.cover,
              errorBuilder: (_, __, ___) => Container(
                width: 64,
                height: 64,
                color: theme.colorScheme.surfaceContainerHighest,
                child: const Icon(Icons.broken_image_outlined, size: 20),
              ),
            ),
          ),
          // Dim unselected photos (painted under the selection icon).
          if (!selected)
            Positioned.fill(
              child: ClipRRect(
                borderRadius: BorderRadius.circular(6),
                child: Container(color: Colors.black.withValues(alpha: 0.35)),
              ),
            ),
          Positioned(
            top: 2,
            right: 2,
            child: Icon(
              selected ? Icons.check_circle : Icons.circle_outlined,
              size: 18,
              color: selected
                  ? theme.colorScheme.primary
                  : Colors.white.withValues(alpha: 0.9),
            ),
          ),
        ],
      ),
    );
  }
}
