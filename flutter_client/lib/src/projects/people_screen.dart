/// People section (issue #40): a searchable directory of people met on the trip,
/// with a per-person detail sheet listing every place + date you met them.
library;

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../core/design_tokens.dart';
import 'people_search.dart';
import 'person_form_dialog.dart';
import 'project_notifier.dart';

/// Full-screen People directory for the open project.
class PeopleScreen extends StatefulWidget {
  final ProjectNotifier notifier;
  const PeopleScreen({super.key, required this.notifier});

  @override
  State<PeopleScreen> createState() => _PeopleScreenState();
}

class _PeopleScreenState extends State<PeopleScreen> {
  final _search = TextEditingController();

  @override
  void initState() {
    super.initState();
    _search.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('People')),
      floatingActionButton: FloatingActionButton.extended(
        backgroundColor: kAccent,
        foregroundColor: Colors.white,
        onPressed: () => showPersonFormDialog(context, widget.notifier),
        icon: const Icon(Icons.person_add_alt_1),
        label: const Text('Add person'),
      ),
      body: AnimatedBuilder(
        animation: widget.notifier,
        builder: (context, _) {
          final notesByPerson = encounterNotesByPerson(widget.notifier.items);
          final counts = encounterCountByPerson(widget.notifier.items);
          final filtered =
              filterPeople(widget.notifier.people, _search.text, notesByPerson);
          return Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 12, 12, 6),
                child: TextField(
                  controller: _search,
                  decoration: InputDecoration(
                    prefixIcon: const Icon(Icons.search),
                    hintText: 'Search people, details or encounter notes',
                    isDense: true,
                    border: const OutlineInputBorder(),
                    suffixIcon: _search.text.isEmpty
                        ? null
                        : IconButton(
                            icon: const Icon(Icons.clear),
                            onPressed: () => _search.clear(),
                          ),
                  ),
                ),
              ),
              Expanded(
                child: widget.notifier.people.isEmpty
                    ? _empty(theme, 'No people yet',
                        'Add someone you met, or log an encounter on a day.')
                    : filtered.isEmpty
                        ? _empty(theme, 'No matches', 'Try a different search.')
                        : ListView.builder(
                            itemCount: filtered.length,
                            itemBuilder: (_, i) => _PersonTile(
                              notifier: widget.notifier,
                              person: filtered[i],
                              encounterCount:
                                  counts[filtered[i]['id']] ?? 0,
                            ),
                          ),
              ),
            ],
          );
        },
      ),
    );
  }

  Widget _empty(ThemeData theme, String title, String subtitle) => Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.groups_outlined, size: 48,
                  color: theme.colorScheme.onSurfaceVariant),
              const SizedBox(height: 12),
              Text(title, style: theme.textTheme.titleMedium),
              const SizedBox(height: 4),
              Text(subtitle,
                  textAlign: TextAlign.center,
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
            ],
          ),
        ),
      );
}

class _PersonTile extends StatelessWidget {
  final ProjectNotifier notifier;
  final Map<String, dynamic> person;
  final int encounterCount;
  const _PersonTile({
    required this.notifier,
    required this.person,
    required this.encounterCount,
  });

  @override
  Widget build(BuildContext context) {
    final subtitleParts = <String>[
      if (encounterCount > 0)
        '$encounterCount ${encounterCount == 1 ? 'encounter' : 'encounters'}',
      if ((person['email'] as String?)?.isNotEmpty ?? false) person['email'],
    ];
    return ListTile(
      leading: PersonAvatar(notifier: notifier, person: person, radius: 22),
      title: Text(personDisplayName(person)),
      subtitle: subtitleParts.isEmpty ? null : Text(subtitleParts.join('  •  ')),
      onTap: () => showPersonDetailSheet(context, notifier, person),
    );
  }
}

/// Circular avatar: the person's photo thumbnail, or their initial on an accent
/// background when there's no photo.
class PersonAvatar extends StatelessWidget {
  final ProjectNotifier notifier;
  final Map<String, dynamic> person;
  final double radius;
  const PersonAvatar({
    super.key,
    required this.notifier,
    required this.person,
    this.radius = 22,
  });

  @override
  Widget build(BuildContext context) {
    final hasPhoto = (person['avatar_photo'] as String?)?.isNotEmpty ?? false;
    final label = personDisplayName(person);
    final initial = label.isNotEmpty ? label.characters.first.toUpperCase() : '?';
    if (hasPhoto) {
      final url =
          '${notifier.apiBaseUrl}/api/people/${person['id']}/avatar/thumb';
      return CircleAvatar(
        radius: radius,
        backgroundImage: NetworkImage(url, headers: notifier.photoAuthHeaders),
      );
    }
    return CircleAvatar(
      radius: radius,
      backgroundColor: kAccentSoft,
      child: Text(initial,
          style: TextStyle(color: kAccent, fontWeight: FontWeight.w600)),
    );
  }
}

/// Show the per-person detail sheet: info + every place/date you met them.
Future<void> showPersonDetailSheet(
  BuildContext context,
  ProjectNotifier notifier,
  Map<String, dynamic> person,
) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (_) => _PersonDetailSheet(notifier: notifier, person: person),
  );
}

class _PersonDetailSheet extends StatefulWidget {
  final ProjectNotifier notifier;
  final Map<String, dynamic> person;
  const _PersonDetailSheet({required this.notifier, required this.person});

  @override
  State<_PersonDetailSheet> createState() => _PersonDetailSheetState();
}

class _PersonDetailSheetState extends State<_PersonDetailSheet> {
  Map<String, dynamic>? _full;
  bool _loading = true;

  int get _personId => (widget.person['id'] as num).toInt();

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final full = await widget.notifier.fetchPerson(_personId);
    if (!mounted) return;
    setState(() {
      _full = full;
      _loading = false;
    });
  }

  Future<void> _edit() async {
    final navigator = Navigator.of(context);
    await showPersonFormDialog(context, widget.notifier,
        person: _full ?? widget.person);
    navigator.pop();
  }

  Future<void> _pickAvatar() async {
    final result = await FilePicker.pickFiles(type: FileType.image, withData: true);
    final f = result?.files.firstOrNull;
    if (f?.bytes == null) return;
    await widget.notifier.uploadPersonAvatar(_personId, f!.bytes!, f.name);
    await _load();
  }

  Future<void> _delete() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete person?'),
        content: const Text(
            'This also removes all encounters with them. This cannot be undone.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: const Text('Cancel')),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: kAccent),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    final navigator = Navigator.of(context);
    await widget.notifier.deletePerson(_personId);
    navigator.pop();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final person = _full ?? widget.person;
    final encounters =
        (_full?['encounters'] as List?)?.cast<Map<String, dynamic>>() ?? const [];
    return Padding(
      padding: EdgeInsets.only(
        left: 16, right: 16, top: 4,
        bottom: MediaQuery.of(context).viewInsets.bottom + 16,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Stack(
                children: [
                  PersonAvatar(
                      notifier: widget.notifier, person: person, radius: 28),
                  Positioned(
                    right: -6,
                    bottom: -6,
                    child: IconButton(
                      tooltip: 'Change photo',
                      iconSize: 18,
                      visualDensity: VisualDensity.compact,
                      icon: const Icon(Icons.photo_camera_outlined),
                      onPressed: _pickAvatar,
                    ),
                  ),
                ],
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(personDisplayName(person),
                    style: theme.textTheme.titleLarge),
              ),
              IconButton(
                  icon: const Icon(Icons.edit_outlined), onPressed: _edit),
              IconButton(
                  icon: Icon(Icons.delete_outline, color: kAccent),
                  onPressed: _delete),
            ],
          ),
          const SizedBox(height: 8),
          _detailRow(Icons.email_outlined, person['email']),
          _detailRow(Icons.phone_outlined, person['phone']),
          _detailRow(Icons.travel_explore_outlined, person['polarsteps']),
          _detailRow(Icons.notes_outlined, person['notes']),
          const SizedBox(height: 12),
          Text('Places & dates met', style: theme.textTheme.titleSmall),
          const SizedBox(height: 4),
          if (_loading)
            const Padding(
                padding: EdgeInsets.all(16),
                child: Center(child: CircularProgressIndicator()))
          else if (encounters.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Text('No encounters logged yet.',
                  style: theme.textTheme.bodySmall),
            )
          else
            Flexible(
              child: ListView(
                shrinkWrap: true,
                children: [
                  for (final e in encounters)
                    ListTile(
                      dense: true,
                      leading: const Icon(Icons.place_outlined, size: 18),
                      title: Text(e['date']?.toString() ?? ''),
                      subtitle: (e['description'] as String?)?.isNotEmpty ?? false
                          ? Text(e['description'] as String)
                          : null,
                    ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Widget _detailRow(IconData icon, Object? value) {
    final text = value?.toString().trim();
    if (text == null || text.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 18, color: Theme.of(context).colorScheme.onSurfaceVariant),
          const SizedBox(width: 10),
          Expanded(child: Text(text)),
        ],
      ),
    );
  }
}
