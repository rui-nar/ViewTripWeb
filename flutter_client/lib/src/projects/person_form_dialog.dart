/// Create / edit a person (issues #40, #49). Name is optional — a blank name is
/// stored and rendered as "Unknown". Avatar upload lives on the person detail
/// sheet.
///
/// Beyond the basic identity fields this modal offers: several social links via
/// a "+" (Instagram / Facebook / Polarsteps / Strava / …), email-format
/// validation, multi-select nationalities from the ISO country list, and a
/// residence field with server-backed city autocomplete. Name is title-cased and
/// Notes sentence-cased as you type.
library;

import 'package:flutter/material.dart';

import '../core/countries.dart';
import '../core/design_tokens.dart';
import 'project_notifier.dart';

/// Social networks offered in the "+" picker. Stored lower-case; the value is a
/// free handle or profile URL. Extensible — add a code here and a label below.
const List<String> kSocialNetworks = [
  'instagram',
  'facebook',
  'polarsteps',
  'strava',
  'tiktok',
  'x',
  'linkedin',
  'website',
];

String _networkLabel(String code) => switch (code) {
      'x' => 'X',
      'tiktok' => 'TikTok',
      'linkedin' => 'LinkedIn',
      _ => code[0].toUpperCase() + code.substring(1),
    };

/// Show the create/edit person dialog. Returns the person id on success (the new
/// id when creating, the existing id when editing), or null if cancelled.
Future<int?> showPersonFormDialog(
  BuildContext context,
  ProjectNotifier notifier, {
  Map<String, dynamic>? person,
}) {
  return showDialog<int?>(
    context: context,
    builder: (_) => PersonFormDialog(notifier: notifier, person: person),
  );
}

class PersonFormDialog extends StatefulWidget {
  final ProjectNotifier notifier;
  final Map<String, dynamic>? person;
  const PersonFormDialog({super.key, required this.notifier, this.person});

  @override
  State<PersonFormDialog> createState() => _PersonFormDialogState();
}

/// One editable social-link row: a network selection plus its handle controller.
class _SocialRow {
  String network;
  final TextEditingController handle;
  _SocialRow(this.network, String value)
      : handle = TextEditingController(text: value);
}

class _PersonFormDialogState extends State<PersonFormDialog> {
  final _formKey = GlobalKey<FormState>();

  late final TextEditingController _name =
      TextEditingController(text: widget.person?['name'] as String? ?? '');
  late final TextEditingController _email =
      TextEditingController(text: widget.person?['email'] as String? ?? '');
  late final TextEditingController _phone =
      TextEditingController(text: widget.person?['phone'] as String? ?? '');
  late final TextEditingController _notes =
      TextEditingController(text: widget.person?['notes'] as String? ?? '');

  late final List<_SocialRow> _socials = _initialSocials();
  late final List<String> _nationalities = _initialNationalities();
  // The Autocomplete-owned controller for the residence field, captured on first
  // build so its typed/selected value can be read at save time.
  TextEditingController? _residenceController;
  late final String _initialResidence =
      widget.person?['residence'] as String? ?? '';

  bool _saving = false;

  bool get _isEdit => widget.person != null;

  List<_SocialRow> _initialSocials() {
    final raw = widget.person?['socials'];
    if (raw is! List) return [];
    return [
      for (final e in raw)
        if (e is Map && e['network'] != null)
          _SocialRow('${e['network']}', '${e['handle'] ?? ''}'),
    ];
  }

  List<String> _initialNationalities() {
    final raw = widget.person?['nationalities'];
    if (raw is! List) return [];
    return [for (final c in raw) '$c'];
  }

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    _phone.dispose();
    _notes.dispose();
    for (final s in _socials) {
      s.handle.dispose();
    }
    super.dispose();
  }

  String? _t(TextEditingController c) {
    final v = c.text.trim();
    return v.isEmpty ? null : v;
  }

  String? _emailValidator(String? v) {
    final s = (v ?? '').trim();
    if (s.isEmpty) return null; // optional
    final re = RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$');
    return re.hasMatch(s) ? null : 'Enter a valid email';
  }

  Future<void> _save() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() => _saving = true);
    final navigator = Navigator.of(context);

    final socials = [
      for (final s in _socials)
        if (s.handle.text.trim().isNotEmpty)
          {'network': s.network, 'handle': s.handle.text.trim()},
    ];
    final residence = _residenceController?.text.trim();

    int? id;
    if (_isEdit) {
      id = (widget.person!['id'] as num).toInt();
      await widget.notifier.updatePerson(
        id,
        name: _t(_name),
        email: _t(_email),
        phone: _t(_phone),
        notes: _t(_notes),
        socials: socials,
        nationalities: _nationalities,
        residence: (residence == null || residence.isEmpty) ? null : residence,
      );
    } else {
      id = await widget.notifier.createPerson(
        name: _t(_name),
        email: _t(_email),
        phone: _t(_phone),
        notes: _t(_notes),
        socials: socials,
        nationalities: _nationalities,
        residence: (residence == null || residence.isEmpty) ? null : residence,
      );
    }
    if (!mounted) return;
    navigator.pop(id);
  }

  // ── Socials ─────────────────────────────────────────────────────────────────

  void _addSocial() {
    // Default to the first network not already present, else the first network.
    final used = _socials.map((s) => s.network).toSet();
    final next = kSocialNetworks.firstWhere((n) => !used.contains(n),
        orElse: () => kSocialNetworks.first);
    setState(() => _socials.add(_SocialRow(next, '')));
  }

  void _removeSocial(int i) {
    setState(() => _socials.removeAt(i).handle.dispose());
  }

  // ── Nationalities ─────────────────────────────────────────────────────────

  Future<void> _addNationality() async {
    final code = await showDialog<String>(
      context: context,
      builder: (_) => _CountryPickerDialog(exclude: _nationalities.toSet()),
    );
    if (code == null || !mounted) return;
    if (!_nationalities.contains(code)) {
      setState(() => _nationalities.add(code));
    }
  }

  // ── Build ────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(_isEdit ? 'Edit person' : 'Add person'),
      content: SizedBox(
        width: 360,
        child: Form(
          key: _formKey,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _text(_name, 'Name',
                    hint: 'optional — blank shows as "Unknown"',
                    capitalization: TextCapitalization.words),
                _text(_email, 'Email',
                    keyboard: TextInputType.emailAddress,
                    validator: _emailValidator,
                    key: const Key('person-email')),
                _text(_phone, 'Phone', keyboard: TextInputType.phone),
                const SizedBox(height: 12),
                _socialsSection(),
                const SizedBox(height: 12),
                _nationalitySection(),
                const SizedBox(height: 12),
                _residenceField(),
                const SizedBox(height: 12),
                _text(_notes, 'Notes',
                    maxLines: 3, capitalization: TextCapitalization.sentences),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: _saving ? null : () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        FilledButton(
          style: FilledButton.styleFrom(backgroundColor: kAccent),
          onPressed: _saving ? null : _save,
          child: _saving
              ? const SizedBox(
                  width: 16, height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : Text(_isEdit ? 'Save' : 'Add'),
        ),
      ],
    );
  }

  Widget _sectionLabel(String label, {Widget? trailing}) {
    final theme = Theme.of(context);
    return Row(
      children: [
        Text(label, style: theme.textTheme.labelLarge),
        const Spacer(),
        if (trailing != null) trailing,
      ],
    );
  }

  Widget _socialsSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _sectionLabel(
          'Social networks',
          trailing: TextButton.icon(
            key: const Key('add-social'),
            onPressed: _addSocial,
            icon: const Icon(Icons.add, size: 18),
            label: const Text('Add'),
          ),
        ),
        for (var i = 0; i < _socials.length; i++)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Row(
              children: [
                DropdownButton<String>(
                  value: _socials[i].network,
                  underline: const SizedBox.shrink(),
                  items: [
                    for (final n in kSocialNetworks)
                      DropdownMenuItem(value: n, child: Text(_networkLabel(n))),
                  ],
                  onChanged: (v) =>
                      setState(() => _socials[i].network = v ?? _socials[i].network),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: TextField(
                    controller: _socials[i].handle,
                    decoration: const InputDecoration(
                      hintText: 'handle or URL',
                      isDense: true,
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                IconButton(
                  key: Key('remove-social-$i'),
                  icon: const Icon(Icons.close, size: 18),
                  onPressed: () => _removeSocial(i),
                ),
              ],
            ),
          ),
      ],
    );
  }

  Widget _nationalitySection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _sectionLabel(
          'Nationality',
          trailing: TextButton.icon(
            key: const Key('add-nationality'),
            onPressed: _addNationality,
            icon: const Icon(Icons.add, size: 18),
            label: const Text('Add'),
          ),
        ),
        if (_nationalities.isNotEmpty)
          Wrap(
            spacing: 6,
            runSpacing: 4,
            children: [
              for (final code in _nationalities)
                Chip(
                  label: Text(countryName(code)),
                  onDeleted: () => setState(() => _nationalities.remove(code)),
                ),
            ],
          ),
      ],
    );
  }

  Widget _residenceField() {
    return Autocomplete<String>(
      initialValue: TextEditingValue(text: _initialResidence),
      optionsBuilder: (TextEditingValue value) async {
        return widget.notifier.searchPlaces(value.text);
      },
      fieldViewBuilder: (context, controller, focusNode, onFieldSubmitted) {
        _residenceController = controller;
        return TextField(
          key: const Key('person-residence'),
          controller: controller,
          focusNode: focusNode,
          decoration: const InputDecoration(
            labelText: 'Lives in',
            hintText: 'start typing a city…',
            border: OutlineInputBorder(),
            isDense: true,
          ),
        );
      },
    );
  }

  Widget _text(
    TextEditingController c,
    String label, {
    String? hint,
    TextInputType? keyboard,
    int maxLines = 1,
    TextCapitalization capitalization = TextCapitalization.none,
    String? Function(String?)? validator,
    Key? key,
  }) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: TextFormField(
        key: key,
        controller: c,
        keyboardType: keyboard,
        maxLines: maxLines,
        textCapitalization: capitalization,
        validator: validator,
        decoration: InputDecoration(
          labelText: label,
          hintText: hint,
          border: const OutlineInputBorder(),
          isDense: true,
        ),
      ),
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
