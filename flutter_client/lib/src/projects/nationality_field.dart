/// Reusable multi-select nationality editor — chips + a searchable country
/// picker (issues #49, #50). Shared by the person and group modals.
///
/// Uncontrolled: read the current ISO 3166-1 alpha-2 codes from
/// [NationalityFieldState.value] (via a GlobalKey) at save time.
library;

import 'package:flutter/material.dart';

import '../core/countries.dart';

class NationalityField extends StatefulWidget {
  /// Initial ISO 3166-1 alpha-2 codes.
  final List<String> initial;
  const NationalityField({super.key, this.initial = const []});

  @override
  State<NationalityField> createState() => NationalityFieldState();
}

class NationalityFieldState extends State<NationalityField> {
  late final List<String> _codes = List<String>.of(widget.initial);

  /// The current selected alpha-2 codes.
  List<String> get value => List<String>.of(_codes);

  Future<void> _add() async {
    final code = await showDialog<String>(
      context: context,
      builder: (_) => _CountryPickerDialog(exclude: _codes.toSet()),
    );
    if (code == null || !mounted) return;
    if (!_codes.contains(code)) setState(() => _codes.add(code));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Text('Nationality', style: theme.textTheme.labelLarge),
            const Spacer(),
            TextButton.icon(
              key: const Key('add-nationality'),
              onPressed: _add,
              icon: const Icon(Icons.add, size: 18),
              label: const Text('Add'),
            ),
          ],
        ),
        if (_codes.isNotEmpty)
          Wrap(
            spacing: 6,
            runSpacing: 4,
            children: [
              for (final code in _codes)
                Chip(
                  label: Text(countryName(code)),
                  onDeleted: () => setState(() => _codes.remove(code)),
                ),
            ],
          ),
      ],
    );
  }
}

/// Searchable single-select country list; pops the chosen alpha-2 code.
class _CountryPickerDialog extends StatefulWidget {
  final Set<String> exclude;
  const _CountryPickerDialog({required this.exclude});

  @override
  State<_CountryPickerDialog> createState() => _CountryPickerDialogState();
}

class _CountryPickerDialogState extends State<_CountryPickerDialog> {
  String _query = '';

  @override
  Widget build(BuildContext context) {
    final q = _query.trim().toLowerCase();
    final matches = [
      for (final c in kCountries)
        if (!widget.exclude.contains(c.code) &&
            (q.isEmpty || c.name.toLowerCase().contains(q)))
          c,
    ];
    return AlertDialog(
      title: const Text('Add nationality'),
      content: SizedBox(
        width: 320,
        height: 420,
        child: Column(
          children: [
            TextField(
              key: const Key('country-search'),
              autofocus: true,
              decoration: const InputDecoration(
                hintText: 'Search countries…',
                prefixIcon: Icon(Icons.search),
                isDense: true,
                border: OutlineInputBorder(),
              ),
              onChanged: (v) => setState(() => _query = v),
            ),
            const SizedBox(height: 8),
            Expanded(
              child: ListView.builder(
                itemCount: matches.length,
                itemBuilder: (_, i) => ListTile(
                  dense: true,
                  title: Text(matches[i].name),
                  onTap: () => Navigator.of(context).pop(matches[i].code),
                ),
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
      ],
    );
  }
}
