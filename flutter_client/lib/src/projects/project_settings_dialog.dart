import 'package:flutter/material.dart';

import 'project_notifier.dart';

class ProjectSettingsDialog extends StatefulWidget {
  final ProjectNotifier notifier;

  const ProjectSettingsDialog({super.key, required this.notifier});

  @override
  State<ProjectSettingsDialog> createState() => _ProjectSettingsDialogState();
}

class _ProjectSettingsDialogState extends State<ProjectSettingsDialog> {
  DateTime? _tripStart;
  bool _saving = false;

  late List<TextEditingController> _optCtrls;

  static const _months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  static String _fmtDate(DateTime d) => '${_months[d.month - 1]} ${d.day}, ${d.year}';
  static String _toIso(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  @override
  void initState() {
    super.initState();
    final ts = widget.notifier.tripStart;
    if (ts != null) _tripStart = DateTime.tryParse(ts);
    _optCtrls = widget.notifier.sleepingOptions
        .map((opt) => TextEditingController(text: opt))
        .toList();
  }

  @override
  void dispose() {
    for (final c in _optCtrls) c.dispose();
    super.dispose();
  }

  void _addOption() {
    setState(() => _optCtrls.add(TextEditingController()));
  }

  void _removeOption(int i) {
    setState(() => _optCtrls.removeAt(i).dispose());
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    await widget.notifier.setTripStart(
      _tripStart == null ? null : _toIso(_tripStart!),
    );
    final updatedOpts = _optCtrls
        .map((c) => c.text.trim())
        .where((s) => s.isNotEmpty)
        .toList();
    await widget.notifier.updateSleepingOptions(updatedOpts);
    if (mounted) Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return AlertDialog(
      title: const Text('Project settings'),
      content: SizedBox(
        width: 480,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // ── Trip start ────────────────────────────────────────────
              Text('Trip start', style: theme.textTheme.labelMedium),
              const SizedBox(height: 4),
              Text(
                'Day 1 is normally inferred from the earliest activity date. '
                'Override it here to set a custom trip start.',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
              const SizedBox(height: 8),
              InkWell(
                borderRadius: BorderRadius.circular(8),
                onTap: () async {
                  final picked = await showDatePicker(
                    context: context,
                    useRootNavigator: true,
                    initialDate: _tripStart ?? DateTime.now(),
                    firstDate: DateTime(2000),
                    lastDate: DateTime(2100),
                  );
                  if (picked != null) setState(() => _tripStart = picked);
                },
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  child: Row(
                    children: [
                      Icon(Icons.calendar_today, size: 18,
                          color: theme.colorScheme.onSurfaceVariant),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          _tripStart == null
                              ? 'Inferred from activities'
                              : _fmtDate(_tripStart!),
                          style: theme.textTheme.bodyMedium?.copyWith(
                            color: _tripStart == null
                                ? theme.colorScheme.onSurfaceVariant
                                : null,
                          ),
                        ),
                      ),
                      if (_tripStart != null)
                        IconButton(
                          icon: const Icon(Icons.close, size: 16),
                          visualDensity: VisualDensity.compact,
                          tooltip: 'Clear override',
                          onPressed: () => setState(() => _tripStart = null),
                        ),
                    ],
                  ),
                ),
              ),

              const Divider(height: 24),

              // ── Sleeping options ──────────────────────────────────────
              Text('Sleeping options', style: theme.textTheme.labelMedium),
              const SizedBox(height: 4),
              Text(
                'Options available when editing a day.',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
              const SizedBox(height: 8),
              ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 220),
                child: ListView.builder(
                  shrinkWrap: true,
                  itemCount: _optCtrls.length,
                  itemBuilder: (_, i) => Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: _optCtrls[i],
                          style: theme.textTheme.bodyMedium,
                          decoration: const InputDecoration(
                            isDense: true,
                            border: InputBorder.none,
                            contentPadding: EdgeInsets.symmetric(
                                vertical: 6, horizontal: 4),
                          ),
                        ),
                      ),
                      IconButton(
                        icon: const Icon(Icons.delete_outline, size: 16),
                        visualDensity: VisualDensity.compact,
                        tooltip: 'Remove',
                        onPressed: () => _removeOption(i),
                      ),
                    ],
                  ),
                ),
              ),
              TextButton.icon(
                icon: const Icon(Icons.add, size: 16),
                label: const Text('Add option'),
                onPressed: _addOption,
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
