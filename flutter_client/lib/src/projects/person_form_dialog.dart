/// Create / edit a person (issues #40, #49). Name is optional — a blank name is
/// stored and rendered as "Unknown". Avatar upload lives on the person detail
/// sheet.
///
/// Beyond the basic identity fields this modal offers: several social links via
/// a "+" (Instagram / Facebook / Polarsteps / Strava / …), email-format
/// validation, multi-select nationalities from the ISO country list, and a
/// residence field with server-backed city autocomplete. Name is title-cased and
/// Notes sentence-cased as you type. The social + nationality editors are shared
/// with the group modal (issue #50).
library;

import 'package:flutter/material.dart';

import '../core/design_tokens.dart';
import 'nationality_field.dart';
import 'project_notifier.dart';
import 'social_links_field.dart';

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

class _PersonFormDialogState extends State<PersonFormDialog> {
  final _formKey = GlobalKey<FormState>();
  final _socialsKey = GlobalKey<SocialLinksFieldState>();
  final _nationalityKey = GlobalKey<NationalityFieldState>();

  late final TextEditingController _name =
      TextEditingController(text: widget.person?['name'] as String? ?? '');
  late final TextEditingController _email =
      TextEditingController(text: widget.person?['email'] as String? ?? '');
  late final TextEditingController _phone =
      TextEditingController(text: widget.person?['phone'] as String? ?? '');
  late final TextEditingController _notes =
      TextEditingController(text: widget.person?['notes'] as String? ?? '');

  // The Autocomplete-owned controller for the residence field, captured on first
  // build so its typed/selected value can be read at save time.
  TextEditingController? _residenceController;
  late final String _initialResidence =
      widget.person?['residence'] as String? ?? '';

  bool _saving = false;

  bool get _isEdit => widget.person != null;

  List<Map<String, dynamic>> _initialSocials() {
    final raw = widget.person?['socials'];
    return raw is List ? raw.cast<Map<String, dynamic>>() : const [];
  }

  List<String> _initialNationalities() {
    final raw = widget.person?['nationalities'];
    return raw is List ? [for (final c in raw) '$c'] : const [];
  }

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    _phone.dispose();
    _notes.dispose();
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

    final socials = _socialsKey.currentState?.value ?? const [];
    final nationalities = _nationalityKey.currentState?.value ?? const [];
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
        nationalities: nationalities,
        residence: (residence == null || residence.isEmpty) ? null : residence,
      );
    } else {
      id = await widget.notifier.createPerson(
        name: _t(_name),
        email: _t(_email),
        phone: _t(_phone),
        notes: _t(_notes),
        socials: socials,
        nationalities: nationalities,
        residence: (residence == null || residence.isEmpty) ? null : residence,
      );
    }
    if (!mounted) return;
    navigator.pop(id);
  }

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
                SocialLinksField(key: _socialsKey, initial: _initialSocials()),
                const SizedBox(height: 12),
                NationalityField(
                    key: _nationalityKey, initial: _initialNationalities()),
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
