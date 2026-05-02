import 'package:flutter/material.dart';

import 'project_notifier.dart';

const _kAppVersion = '0.23.0';

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
  late List<String> _optGroups; // parallel to _optCtrls: "Outdoors"|"Indoors"|"Other"

  static const _groups = ['Outdoors', 'Indoors', 'Other'];

  // Track style
  late Color _trackColor;
  late double _trackWidth;
  late bool _alternating;

  static const _presetColors = [
    Color(0xFFF97316), // orange (default)
    Color(0xFFEF4444), // red
    Color(0xFF3B82F6), // blue
    Color(0xFF22C55E), // green
    Color(0xFFA855F7), // purple
    Color(0xFFEC4899), // pink
    Color(0xFFEAB308), // yellow
    Color(0xFF06B6D4), // cyan
    Color(0xFFFFFFFF), // white
    Color(0xFF374151), // dark grey
  ];

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
    _optGroups = widget.notifier.sleepingOptions
        .map((opt) => widget.notifier.sleepingOptionGroups[opt] ?? 'Other')
        .toList();
    _trackColor = widget.notifier.trackColor;
    _trackWidth = widget.notifier.trackWidth;
    _alternating = widget.notifier.alternatingTrackColors;
  }

  @override
  void dispose() {
    for (final c in _optCtrls) { c.dispose(); }
    super.dispose();
  }

  void _addOption() {
    setState(() {
      _optCtrls.add(TextEditingController());
      _optGroups.add('Other');
    });
  }

  void _removeOption(int i) {
    setState(() {
      _optCtrls.removeAt(i).dispose();
      _optGroups.removeAt(i);
    });
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    await widget.notifier.setTripStart(
      _tripStart == null ? null : _toIso(_tripStart!),
    );
    final updatedOpts = <String>[];
    final updatedGroups = <String, String>{};
    for (int i = 0; i < _optCtrls.length; i++) {
      final name = _optCtrls[i].text.trim();
      if (name.isNotEmpty) {
        updatedOpts.add(name);
        updatedGroups[name] = _optGroups[i];
      }
    }
    await widget.notifier.updateSleepingOptions(updatedOpts, groups: updatedGroups);
    widget.notifier.setTrackStyle(
      color: _trackColor,
      width: _trackWidth,
      alternating: _alternating,
    );
    if (mounted) Navigator.of(context).pop();
  }

  // Preview swatch showing primary + alternate colour when alternating is on.
  Widget _colorPreview(Color base) {
    final alt = _MapPanelStateColorHelper.alternateColor(base);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 24, height: 24,
          decoration: BoxDecoration(
            color: base,
            shape: BoxShape.circle,
            border: Border.all(color: Colors.white24, width: 1),
          ),
        ),
        if (_alternating) ...[
          const SizedBox(width: 4),
          Container(
            width: 24, height: 24,
            decoration: BoxDecoration(
              color: alt,
              shape: BoxShape.circle,
              border: Border.all(color: Colors.white24, width: 1),
            ),
          ),
        ],
      ],
    );
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

              // ── Track style ───────────────────────────────────────────
              Text('Track style', style: theme.textTheme.labelMedium),
              const SizedBox(height: 12),

              // Color swatches
              Text('Colour', style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              )),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: _presetColors.map((c) {
                  final selected = _trackColor.toARGB32() == c.toARGB32();
                  return GestureDetector(
                    onTap: () => setState(() => _trackColor = c),
                    child: Container(
                      width: 32, height: 32,
                      decoration: BoxDecoration(
                        color: c,
                        shape: BoxShape.circle,
                        border: Border.all(
                          color: selected
                              ? theme.colorScheme.primary
                              : theme.colorScheme.outlineVariant,
                          width: selected ? 2.5 : 1,
                        ),
                        boxShadow: selected
                            ? [BoxShadow(
                                color: theme.colorScheme.primary.withAlpha(80),
                                blurRadius: 6)]
                            : null,
                      ),
                      child: selected
                          ? Icon(Icons.check,
                              size: 16,
                              color: ThemeData.estimateBrightnessForColor(c) ==
                                      Brightness.dark
                                  ? Colors.white
                                  : Colors.black87)
                          : null,
                    ),
                  );
                }).toList(),
              ),

              const SizedBox(height: 16),

              // Thickness slider
              Row(
                children: [
                  Text('Thickness', style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  )),
                  const Spacer(),
                  Text(_trackWidth.toStringAsFixed(1),
                      style: theme.textTheme.bodySmall),
                ],
              ),
              Slider(
                value: _trackWidth,
                min: 1.0,
                max: 6.0,
                divisions: 10,
                onChanged: (v) => setState(() => _trackWidth = v),
              ),

              const SizedBox(height: 4),

              // Alternating colours checkbox + preview
              Row(
                children: [
                  Checkbox(
                    value: _alternating,
                    visualDensity: VisualDensity.compact,
                    onChanged: (v) => setState(() => _alternating = v ?? false),
                  ),
                  const SizedBox(width: 4),
                  Expanded(
                    child: GestureDetector(
                      onTap: () => setState(() => _alternating = !_alternating),
                      child: Text(
                        'Alternating colours — every other activity uses a muted hue',
                        style: theme.textTheme.bodySmall,
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  _colorPreview(_trackColor),
                ],
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
                      DropdownButton<String>(
                        value: _optGroups[i],
                        isDense: true,
                        underline: const SizedBox.shrink(),
                        style: theme.textTheme.bodySmall,
                        items: _groups.map((g) => DropdownMenuItem(
                          value: g,
                          child: Text(g),
                        )).toList(),
                        onChanged: (v) => setState(() => _optGroups[i] = v!),
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

              const Divider(height: 32),

              Text(
                '© ${DateTime.now().year} ViewTripWeb · v$_kAppVersion',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
                textAlign: TextAlign.center,
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

// Thin helper so the dialog can reuse _alternateColor without depending on
// the private _MapPanelState class.
class _MapPanelStateColorHelper {
  static Color alternateColor(Color base) {
    final hsl = HSLColor.fromColor(base);
    return hsl
        .withSaturation((hsl.saturation * 0.42).clamp(0.0, 1.0))
        .withLightness((hsl.lightness * 1.18).clamp(0.0, 1.0))
        .toColor();
  }
}
