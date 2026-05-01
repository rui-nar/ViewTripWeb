import 'package:flutter/material.dart';
import 'project_notifier.dart';

// ── Chip data ──────────────────────────────────────────────────────────────

const _difficultyOptions = [
  (null,         '—'),
  ('easy',       'Easy'),
  ('normal',     'Normal'),
  ('hard',       'Hard'),
  ('super_hard', 'Super hard'),
];

const _weatherOptions = [
  (null,         '—'),
  ('hot',        'Hot'),
  ('clear',      'Clear'),
  ('cloudy',     'Cloudy'),
  ('some_rain',  'Some rain'),
  ('heavy_rain', 'Heavy rain'),
];

// ── Public launchers ───────────────────────────────────────────────────────

void showDayMetaDialog(
  BuildContext context,
  ProjectNotifier notifier,
  String dateKey, {
  List<String> orderedDateKeys = const [],
}) {
  showDialog(
    context: context,
    useRootNavigator: true,
    builder: (_) => _DayMetaDialogWrapper(
      notifier: notifier,
      dateKey: dateKey,
      orderedDateKeys: orderedDateKeys,
    ),
  );
}

void showDayMetaSheet(
  BuildContext context,
  ProjectNotifier notifier,
  String dateKey,
) {
  showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    builder: (_) => _DayMetaSheetWrapper(notifier: notifier, dateKey: dateKey),
  );
}

// ── Dialog wrapper — stateful for prev/next navigation ─────────────────────

class _DayMetaDialogWrapper extends StatefulWidget {
  final ProjectNotifier notifier;
  final String dateKey;
  final List<String> orderedDateKeys;

  const _DayMetaDialogWrapper({
    required this.notifier,
    required this.dateKey,
    this.orderedDateKeys = const [],
  });

  @override
  State<_DayMetaDialogWrapper> createState() => _DayMetaDialogWrapperState();
}

class _DayMetaDialogWrapperState extends State<_DayMetaDialogWrapper> {
  late String _currentDateKey;
  final _editorKey = GlobalKey<_DayMetaEditorState>();

  @override
  void initState() {
    super.initState();
    _currentDateKey = widget.dateKey;
  }

  int get _currentIdx => widget.orderedDateKeys.indexOf(_currentDateKey);
  bool get _hasPrev => _currentIdx > 0;
  bool get _hasNext => _currentIdx < widget.orderedDateKeys.length - 1;

  Future<void> _navigate(int delta) async {
    final nextIdx = _currentIdx + delta;
    if (nextIdx < 0 || nextIdx >= widget.orderedDateKeys.length) return;
    final nextKey = widget.orderedDateKeys[nextIdx];

    if (_editorKey.currentState?._dirty ?? false) {
      final result = await showDialog<String>(
        context: context,
        useRootNavigator: true,
        builder: (ctx) => AlertDialog(
          title: const Text('Unsaved changes'),
          content: const Text('Save changes to this day before navigating?'),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop('cancel'),
              child: const Text('Cancel'),
            ),
            TextButton(
              onPressed: () => Navigator.of(ctx).pop('discard'),
              child: const Text('Discard'),
            ),
            ElevatedButton(
              onPressed: () => Navigator.of(ctx).pop('save'),
              child: const Text('Save'),
            ),
          ],
        ),
      );
      if (!mounted || result == null || result == 'cancel') return;
      if (result == 'save') {
        final meta = _editorKey.currentState?._buildMeta() ?? {};
        _persist(widget.notifier, _currentDateKey, meta);
      }
    }

    setState(() => _currentDateKey = nextKey);
  }

  @override
  Widget build(BuildContext context) {
    final hasNav = widget.orderedDateKeys.length > 1;

    return GestureDetector(
      onHorizontalDragEnd: hasNav
          ? (details) {
              final v = details.primaryVelocity ?? 0;
              if (v < -300) _navigate(1);
              if (v > 300) _navigate(-1);
            }
          : null,
      child: AlertDialog(
        title: hasNav
            ? Row(
                children: [
                  IconButton(
                    icon: const Icon(Icons.chevron_left),
                    onPressed: _hasPrev ? () => _navigate(-1) : null,
                  ),
                  Expanded(
                    child: Text(
                      'Edit day · $_currentDateKey',
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                  ),
                  IconButton(
                    icon: const Icon(Icons.chevron_right),
                    onPressed: _hasNext ? () => _navigate(1) : null,
                  ),
                ],
              )
            : Text('Edit day · $_currentDateKey'),
        content: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 440),
          child: SingleChildScrollView(
            child: DayMetaEditor(
              key: _editorKey,
              dateKey: _currentDateKey,
              initialMeta: widget.notifier.dayMeta[_currentDateKey] ?? {},
              sleepingOptions: widget.notifier.sleepingOptions,
              availableTags: widget.notifier.availableTags,
              onSaveOnly: (meta) => _persist(widget.notifier, _currentDateKey, meta),
              onSave: (meta) {
                _persist(widget.notifier, _currentDateKey, meta);
                Navigator.of(context, rootNavigator: true).pop();
              },
              onCancel: () => Navigator.of(context, rootNavigator: true).pop(),
            ),
          ),
        ),
      ),
    );
  }
}

// ── Bottom-sheet wrapper ───────────────────────────────────────────────────

class _DayMetaSheetWrapper extends StatelessWidget {
  final ProjectNotifier notifier;
  final String dateKey;

  const _DayMetaSheetWrapper({required this.notifier, required this.dateKey});

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      initialChildSize: 0.65,
      minChildSize: 0.4,
      maxChildSize: 0.95,
      expand: false,
      builder: (ctx, sc) => Padding(
        padding: EdgeInsets.only(bottom: MediaQuery.of(ctx).viewInsets.bottom),
        child: Column(
          children: [
            const _SheetHandle(),
            Expanded(
              child: SingleChildScrollView(
                controller: sc,
                padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
                child: DayMetaEditor(
                  dateKey: dateKey,
                  initialMeta: notifier.dayMeta[dateKey] ?? {},
                  sleepingOptions: notifier.sleepingOptions,
                  availableTags: notifier.availableTags,
                  onSaveOnly: (meta) => _persist(notifier, dateKey, meta),
                  onSave: (meta) {
                    _persist(notifier, dateKey, meta);
                    Navigator.of(ctx).pop();
                  },
                  onCancel: () => Navigator.of(ctx).pop(),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ── Sheet drag handle ──────────────────────────────────────────────────────

class _SheetHandle extends StatelessWidget {
  const _SheetHandle();

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 10),
      child: Container(
        width: 36,
        height: 4,
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.onSurfaceVariant.withValues(alpha: 0.4),
          borderRadius: BorderRadius.circular(2),
        ),
      ),
    );
  }
}

// ── Shared helper ──────────────────────────────────────────────────────────

void _persist(
  ProjectNotifier notifier,
  String dateKey,
  Map<String, dynamic> meta,
) {
  final updated = Map<String, Map<String, dynamic>>.from(notifier.dayMeta);
  if (meta.isEmpty) {
    updated.remove(dateKey);
  } else {
    updated[dateKey] = meta;
  }
  notifier.saveDayMeta(newDayMeta: updated);
}

// ── Editor widget ──────────────────────────────────────────────────────────

class DayMetaEditor extends StatefulWidget {
  final String dateKey;
  final Map<String, dynamic> initialMeta;
  final List<String> sleepingOptions;
  final List<String> availableTags;
  final void Function(Map<String, dynamic> meta) onSave;
  final void Function(Map<String, dynamic> meta)? onSaveOnly;
  final VoidCallback? onCancel;

  const DayMetaEditor({
    super.key,
    required this.dateKey,
    required this.initialMeta,
    required this.sleepingOptions,
    this.availableTags = const [],
    required this.onSave,
    this.onSaveOnly,
    this.onCancel,
  });

  @override
  State<DayMetaEditor> createState() => _DayMetaEditorState();
}

class _DayMetaEditorState extends State<DayMetaEditor> {
  String? _difficulty;
  String? _sleeping;
  String? _weather;
  late TextEditingController _journalCtrl;
  late List<String> _tags;
  final TextEditingController _tagInputCtrl = TextEditingController();
  bool _dirty = false;

  @override
  void initState() {
    super.initState();
    _applyMeta(widget.initialMeta);
  }

  @override
  void didUpdateWidget(DayMetaEditor oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.dateKey != widget.dateKey) {
      _journalCtrl.text = widget.initialMeta['journal'] as String? ?? '';
      setState(() {
        _applyMetaNoJournal(widget.initialMeta);
        _dirty = false;
      });
    }
  }

  void _applyMeta(Map<String, dynamic> m) {
    _difficulty  = m['difficulty'] as String?;
    _sleeping    = m['sleeping']   as String?;
    _weather     = m['weather']    as String?;
    _journalCtrl = TextEditingController(text: m['journal'] as String? ?? '');
    final rawTags = m['tags'];
    _tags = rawTags is List ? List<String>.from(rawTags.cast<String>()) : [];
  }

  void _applyMetaNoJournal(Map<String, dynamic> m) {
    _difficulty = m['difficulty'] as String?;
    _sleeping   = m['sleeping']   as String?;
    _weather    = m['weather']    as String?;
    final rawTags = m['tags'];
    _tags = rawTags is List ? List<String>.from(rawTags.cast<String>()) : [];
  }

  @override
  void dispose() {
    _journalCtrl.dispose();
    _tagInputCtrl.dispose();
    super.dispose();
  }

  void _addTag(String tag) {
    final t = tag.trim();
    if (t.isEmpty || _tags.contains(t)) return;
    setState(() {
      _tags.add(t);
      _tagInputCtrl.clear();
      _dirty = true;
    });
  }

  Map<String, dynamic> _buildMeta() {
    final result = <String, dynamic>{};
    if (_difficulty != null) result['difficulty'] = _difficulty;
    if (_sleeping   != null) result['sleeping']   = _sleeping;
    if (_weather    != null) result['weather']    = _weather;
    final j = _journalCtrl.text.trim();
    if (j.isNotEmpty) result['journal'] = j;
    if (_tags.isNotEmpty) result['tags'] = List<String>.from(_tags);
    return result;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final labelStyle = theme.textTheme.labelMedium;

    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // ── Difficulty ──────────────────────────────────────────────────
        Text('Difficulty', style: labelStyle),
        const SizedBox(height: 6),
        Wrap(
          spacing: 6,
          children: [
            for (final (val, label) in _difficultyOptions)
              ChoiceChip(
                label: Text(label),
                selected: _difficulty == val,
                onSelected: (_) => setState(() { _difficulty = val; _dirty = true; }),
              ),
          ],
        ),
        const SizedBox(height: 16),

        // ── Weather ─────────────────────────────────────────────────────
        Text('Weather', style: labelStyle),
        const SizedBox(height: 6),
        Wrap(
          spacing: 6,
          children: [
            for (final (val, label) in _weatherOptions)
              ChoiceChip(
                label: Text(label),
                selected: _weather == val,
                onSelected: (_) => setState(() { _weather = val; _dirty = true; }),
              ),
          ],
        ),
        const SizedBox(height: 16),

        // ── Sleeping ────────────────────────────────────────────────────
        Text('Sleeping', style: labelStyle),
        const SizedBox(height: 6),
        DropdownButtonFormField<String?>(
          initialValue: widget.sleepingOptions.contains(_sleeping) ? _sleeping : null,
          decoration: const InputDecoration(
            isDense: true,
            border: OutlineInputBorder(),
            contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          ),
          items: [
            const DropdownMenuItem(value: null, child: Text('— none —')),
            for (final opt in widget.sleepingOptions)
              DropdownMenuItem(value: opt, child: Text(opt)),
          ],
          onChanged: (v) => setState(() { _sleeping = v; _dirty = true; }),
        ),
        const SizedBox(height: 16),

        // ── Journal ─────────────────────────────────────────────────────
        Text('Journal', style: labelStyle),
        const SizedBox(height: 6),
        TextField(
          controller: _journalCtrl,
          maxLines: null,
          minLines: 4,
          textInputAction: TextInputAction.newline,
          decoration: const InputDecoration(
            border: OutlineInputBorder(),
            hintText: 'Notes, highlights, thoughts…',
            contentPadding: EdgeInsets.all(12),
          ),
          onChanged: (_) => setState(() => _dirty = true),
        ),
        const SizedBox(height: 20),

        // ── Tags ────────────────────────────────────────────────────────
        Text('Tags', style: labelStyle),
        const SizedBox(height: 6),
        Wrap(
          spacing: 6,
          runSpacing: 4,
          children: [
            for (final tag in {
              ...widget.availableTags,
              ..._tags,
            }.toList()..sort())
              FilterChip(
                label: Text(tag),
                selected: _tags.contains(tag),
                onSelected: (on) => setState(() {
                  if (on) {
                    if (!_tags.contains(tag)) _tags.add(tag);
                  } else {
                    _tags.remove(tag);
                  }
                  _dirty = true;
                }),
              ),
          ],
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: TextField(
                controller: _tagInputCtrl,
                decoration: const InputDecoration(
                  isDense: true,
                  hintText: 'New tag…',
                  border: OutlineInputBorder(),
                  contentPadding: EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                ),
                onSubmitted: _addTag,
                textInputAction: TextInputAction.done,
              ),
            ),
            const SizedBox(width: 8),
            IconButton.outlined(
              icon: const Icon(Icons.add),
              onPressed: () => _addTag(_tagInputCtrl.text),
            ),
          ],
        ),
        const SizedBox(height: 20),

        // ── Actions ─────────────────────────────────────────────────────
        Row(
          mainAxisAlignment: MainAxisAlignment.end,
          children: [
            if (widget.onCancel != null)
              TextButton(
                onPressed: widget.onCancel,
                child: const Text('Cancel'),
              ),
            const SizedBox(width: 8),
            if (widget.onSaveOnly != null) ...[
              ElevatedButton(
                style: ElevatedButton.styleFrom(minimumSize: const Size(80, 44)),
                onPressed: _dirty
                    ? () {
                        widget.onSaveOnly!(_buildMeta());
                        setState(() => _dirty = false);
                      }
                    : null,
                child: const Text('Save'),
              ),
              const SizedBox(width: 8),
            ],
            ElevatedButton(
              style: ElevatedButton.styleFrom(minimumSize: const Size(80, 44)),
              onPressed: _dirty ? () => widget.onSave(_buildMeta()) : null,
              child: Text(widget.onSaveOnly != null ? 'Save & Close' : 'Save'),
            ),
          ],
        ),
      ],
    );
  }
}
