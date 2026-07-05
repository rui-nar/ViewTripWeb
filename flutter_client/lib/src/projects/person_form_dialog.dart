/// Create / edit a person (issue #40). Name is optional — a blank name is stored
/// and rendered as "Unknown". Avatar upload lives on the person detail sheet.
library;

import 'package:flutter/material.dart';

import '../core/design_tokens.dart';
import 'project_notifier.dart';

/// Show the create/edit person dialog. Returns the person id on success (the new
/// id when creating, the existing id when editing), or null if cancelled.
Future<int?> showPersonFormDialog(
  BuildContext context,
  ProjectNotifier notifier, {
  Map<String, dynamic>? person,
}) {
  return showDialog<int?>(
    context: context,
    builder: (_) => _PersonFormDialog(notifier: notifier, person: person),
  );
}

class _PersonFormDialog extends StatefulWidget {
  final ProjectNotifier notifier;
  final Map<String, dynamic>? person;
  const _PersonFormDialog({required this.notifier, this.person});

  @override
  State<_PersonFormDialog> createState() => _PersonFormDialogState();
}

class _PersonFormDialogState extends State<_PersonFormDialog> {
  late final TextEditingController _name =
      TextEditingController(text: widget.person?['name'] as String? ?? '');
  late final TextEditingController _email =
      TextEditingController(text: widget.person?['email'] as String? ?? '');
  late final TextEditingController _phone =
      TextEditingController(text: widget.person?['phone'] as String? ?? '');
  late final TextEditingController _polarsteps =
      TextEditingController(text: widget.person?['polarsteps'] as String? ?? '');
  late final TextEditingController _notes =
      TextEditingController(text: widget.person?['notes'] as String? ?? '');
  bool _saving = false;

  bool get _isEdit => widget.person != null;

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    _phone.dispose();
    _polarsteps.dispose();
    _notes.dispose();
    super.dispose();
  }

  String? _t(TextEditingController c) {
    final v = c.text.trim();
    return v.isEmpty ? null : v;
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    final navigator = Navigator.of(context);
    int? id;
    if (_isEdit) {
      id = (widget.person!['id'] as num).toInt();
      await widget.notifier.updatePerson(
        id,
        name: _t(_name),
        email: _t(_email),
        phone: _t(_phone),
        polarsteps: _t(_polarsteps),
        notes: _t(_notes),
      );
    } else {
      id = await widget.notifier.createPerson(
        name: _t(_name),
        email: _t(_email),
        phone: _t(_phone),
        polarsteps: _t(_polarsteps),
        notes: _t(_notes),
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
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              _field(_name, 'Name', hint: 'optional — blank shows as "Unknown"'),
              _field(_email, 'Email', keyboard: TextInputType.emailAddress),
              _field(_phone, 'Phone', keyboard: TextInputType.phone),
              _field(_polarsteps, 'Polarsteps', hint: 'username or profile URL'),
              _field(_notes, 'Notes', maxLines: 3),
            ],
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

  Widget _field(TextEditingController c, String label,
      {String? hint, TextInputType? keyboard, int maxLines = 1}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: TextField(
        controller: c,
        keyboardType: keyboard,
        maxLines: maxLines,
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
