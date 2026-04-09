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
  String dateKey,
) {
  showDialog(
    context: context,
    useRootNavigator: true,
    builder: (_) => _DayMetaDialogWrapper(notifier: notifier, dateKey: dateKey),
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

// ── Dialog wrapper ─────────────────────────────────────────────────────────

class _DayMetaDialogWrapper extends StatelessWidget {
  final ProjectNotifier notifier;
  final String dateKey;

  const _DayMetaDialogWrapper({required this.notifier, required this.dateKey});

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text('Edit day · $dateKey'),
      content: SizedBox(
        width: 440,
        child: SingleChildScrollView(
          child: DayMetaEditor(
            dateKey: dateKey,
            initialMeta: notifier.dayMeta[dateKey] ?? {},
            sleepingOptions: notifier.sleepingOptions,
            availableTags: notifier.availableTags,
            onSave: (meta) {
              _persist(notifier, dateKey, meta);
              Navigator.of(context, rootNavigator: true).pop();
            },
            onCancel: () => Navigator.of(context, rootNavigator: true).pop(),
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
        child: DayMetaEditor(
          dateKey: dateKey,
          initialMeta: notifier.dayMeta[dateKey] ?? {},
          sleepingOptions: notifier.sleepingOptions,
          availableTags: notifier.availableTags,
          onSave: (meta) {
            _persist(notifier, dateKey, meta);
            Navigator.of(ctx).pop();
          },
          onCancel: () => Navigator.of(ctx).pop(),
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
  final VoidCallback? onCancel;

  const DayMetaEditor({
    super.key,
    required this.dateKey,
    required this.initialMeta,
    required this.sleepingOptions,
    this.availableTags = const [],
    required this.onSave,
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

  @override
  void initState() {
    super.initState();
    final m = widget.initialMeta;
    _difficulty = m['difficulty'] as String?;
    _sleeping   = m['sleeping']   as String?;
    _weather    = m['weather']    as String?;
    _journalCtrl = TextEditingController(text: m['journal'] as String? ?? '');
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
                onSelected: (_) => setState(() => _difficulty = val),
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
                onSelected: (_) => setState(() => _weather = val),
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
          onChanged: (v) => setState(() => _sleeping = v),
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
        ),
        const SizedBox(height: 20),

        // ── Tags ────────────────────────────────────────────────────────
        Text('Tags', style: labelStyle),
        const SizedBox(height: 6),
        Wrap(
          spacing: 6,
          runSpacing: 4,
          children: [
            // Existing project tags as toggleable chips
            for (final tag in {
              ...widget.availableTags,
              ..._tags,   // include any tags on this day not yet in project-wide list
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
                }),
              ),
          ],
        ),
        const SizedBox(height: 8),
        // New tag input
        Row(
          children: [
            Expanded(
              child: TextField(
                controller: _tagInputCtrl,
                decoration: const InputDecoration(
                  isDense: true,
                  hintText: 'New tag…',
                  border: OutlineInputBorder(),
                  contentPadding:
                      EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                ),
                onSubmitted: _addTag,
                textInputAction: TextInputAction.done,
              ),
            ),
            const SizedBox(width: 8),
            IconButton.outlined(
              icon: const Icon(Icons.add),
              tooltip: 'Add tag',
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
            ElevatedButton(
              style: ElevatedButton.styleFrom(minimumSize: const Size(80, 44)),
              onPressed: () => widget.onSave(_buildMeta()),
              child: const Text('Save'),
            ),
          ],
        ),
      ],
    );
  }
}
