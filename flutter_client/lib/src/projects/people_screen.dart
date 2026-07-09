/// People section (issue #40): a searchable directory of people met on the trip,
/// with a per-person detail sheet listing every place + date you met them.
library;

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../core/countries.dart';
import '../core/design_tokens.dart';
import 'group_form_dialog.dart';
import 'people_search.dart';
import 'person_form_dialog.dart';
import 'project_notifier.dart';
import 'social_links_field.dart' show socialNetworkLabel;

/// Full-screen People directory for the open project.
class PeopleScreen extends StatefulWidget {
  final ProjectNotifier notifier;
  const PeopleScreen({super.key, required this.notifier});

  @override
  State<PeopleScreen> createState() => _PeopleScreenState();
}

class _PeopleScreenState extends State<PeopleScreen> {
  final _search = TextEditingController();
  bool _showGroups = false;

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
      appBar: AppBar(title: const Text('People & groups')),
      floatingActionButton: FloatingActionButton.extended(
        backgroundColor: kAccent,
        foregroundColor: Colors.white,
        onPressed: _showGroups
            ? () => showGroupFormDialog(context, widget.notifier)
            : () => showPersonFormDialog(context, widget.notifier),
        icon: Icon(_showGroups ? Icons.group_add : Icons.person_add_alt_1),
        label: Text(_showGroups ? 'Add group' : 'Add person'),
      ),
      body: AnimatedBuilder(
        animation: widget.notifier,
        builder: (context, _) {
          return Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
                child: SegmentedButton<bool>(
                  showSelectedIcon: false,
                  segments: const [
                    ButtonSegment(
                        value: false,
                        icon: Icon(Icons.person_outline, size: 18),
                        label: Text('People')),
                    ButtonSegment(
                        value: true,
                        icon: Icon(Icons.groups_outlined, size: 18),
                        label: Text('Groups')),
                  ],
                  selected: {_showGroups},
                  onSelectionChanged: (s) =>
                      setState(() => _showGroups = s.first),
                ),
              ),
              Expanded(
                  child: _showGroups ? _groupsBody(theme) : _peopleBody(theme)),
            ],
          );
        },
      ),
    );
  }

  Widget _peopleBody(ThemeData theme) {
    final notesByPerson = encounterNotesByPerson(widget.notifier.items);
    final counts = encounterCountByPerson(widget.notifier.items);
    final filtered =
        filterPeople(widget.notifier.people, _search.text, notesByPerson);
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 6),
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
                        encounterCount: counts[filtered[i]['id']] ?? 0,
                      ),
                    ),
        ),
      ],
    );
  }

  Widget _groupsBody(ThemeData theme) {
    final groups = widget.notifier.groups;
    if (groups.isEmpty) {
      return _empty(theme, 'No groups yet',
          'Group people you met — e.g. a hostel crew or a family.');
    }
    final counts = memberCountByGroup(widget.notifier.people);
    return ListView.builder(
      itemCount: groups.length,
      itemBuilder: (_, i) => _GroupTile(
        notifier: widget.notifier,
        group: groups[i],
        memberCount: counts[groups[i]['id']] ?? 0,
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
  List<Map<String, dynamic>>? _psTrips;
  bool _psLoading = false;

  int get _personId => (widget.person['id'] as num).toInt();

  String? get _psHandle {
    final h = (_full ?? widget.person)['polarsteps'] as String?;
    return (h != null && h.trim().isNotEmpty) ? h.trim() : null;
  }

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

  Future<void> _loadPsTrips() async {
    setState(() => _psLoading = true);
    final trips = await widget.notifier.fetchPersonPolarstepsTrips(_personId);
    if (!mounted) return;
    setState(() {
      _psTrips = trips ?? [];
      _psLoading = false;
    });
    if (trips == null) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(widget.notifier.error ?? 'Could not load Polarsteps trips'),
      ));
    }
  }

  Future<void> _showTrip(Map<String, dynamic> trip) async {
    final navigator = Navigator.of(context);
    final name = personDisplayName(_full ?? widget.person);
    final label = '$name · ${trip['name'] ?? 'Trip'}';
    final ok = await widget.notifier.showPersonPolarstepsTrip(
        _personId, (trip['id'] as num).toInt(), label);
    if (!mounted) return;
    if (ok) {
      navigator.pop(); // close sheet so the overlay is visible on the map
    } else {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(widget.notifier.error ?? 'Could not load that trip'),
      ));
    }
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
          if (_psHandle != null) ...[
            const Divider(height: 20),
            Row(
              children: [
                const Icon(Icons.travel_explore_outlined, size: 18),
                const SizedBox(width: 8),
                Text('Polarsteps trips', style: theme.textTheme.titleSmall),
                const Spacer(),
                if (_psTrips == null)
                  TextButton(
                    onPressed: _psLoading ? null : _loadPsTrips,
                    child: _psLoading
                        ? const SizedBox(
                            width: 14, height: 14,
                            child: CircularProgressIndicator(strokeWidth: 2))
                        : const Text('Show trips'),
                  ),
              ],
            ),
            if (_psTrips != null && _psTrips!.isEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Text('No trips visible to you.',
                    style: theme.textTheme.bodySmall),
              ),
            if (_psTrips != null && _psTrips!.isNotEmpty)
              Flexible(
                child: ListView(
                  shrinkWrap: true,
                  children: [
                    for (final t in _psTrips!)
                      ListTile(
                        dense: true,
                        leading: const Icon(Icons.map_outlined, size: 18),
                        title: Text(t['name']?.toString() ?? 'Trip'),
                        subtitle: Text([
                          if (t['start_date'] != null) t['start_date'],
                          if (t['steps_count'] != null)
                            '${t['steps_count']} steps',
                        ].join('  •  ')),
                        trailing: const Icon(Icons.arrow_forward, size: 16),
                        onTap: () => _showTrip(t),
                      ),
                  ],
                ),
              ),
          ],
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

// ── Groups (issue #50) ────────────────────────────────────────────────────────

class _GroupTile extends StatelessWidget {
  final ProjectNotifier notifier;
  final Map<String, dynamic> group;
  final int memberCount;
  const _GroupTile({
    required this.notifier,
    required this.group,
    required this.memberCount,
  });

  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: CircleAvatar(
        radius: 22,
        backgroundColor: kAccentSoft,
        child: const Icon(Icons.groups, color: kAccent),
      ),
      title: Text(groupDisplayName(group)),
      subtitle: Text('$memberCount ${memberCount == 1 ? 'member' : 'members'}'),
      onTap: () => showGroupDetailSheet(context, notifier, group),
    );
  }
}

/// Per-group detail sheet: info + members (tap a member → their sheet).
Future<void> showGroupDetailSheet(
  BuildContext context,
  ProjectNotifier notifier,
  Map<String, dynamic> group,
) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (_) => _GroupDetailSheet(notifier: notifier, group: group),
  );
}

class _GroupDetailSheet extends StatelessWidget {
  final ProjectNotifier notifier;
  final Map<String, dynamic> group;
  const _GroupDetailSheet({required this.notifier, required this.group});

  int get _groupId => (group['id'] as num).toInt();

  Future<void> _edit(BuildContext context) async {
    final navigator = Navigator.of(context);
    await showGroupFormDialog(context, notifier, group: group);
    navigator.pop();
  }

  Future<void> _delete(BuildContext context) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete group?'),
        content: const Text(
            'The group is removed; its members are kept (just ungrouped).'),
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
    if (ok != true || !context.mounted) return;
    final navigator = Navigator.of(context);
    await notifier.deleteGroup(_groupId);
    navigator.pop();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final nationalities =
        (group['nationalities'] as List?)?.cast<String>() ?? const [];
    final socials =
        (group['socials'] as List?)?.cast<Map<String, dynamic>>() ?? const [];
    final members = membersOfGroup(notifier.people, _groupId);
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
              CircleAvatar(
                radius: 24,
                backgroundColor: kAccentSoft,
                child: const Icon(Icons.groups, color: kAccent),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(groupDisplayName(group),
                    style: theme.textTheme.titleLarge),
              ),
              IconButton(
                  icon: const Icon(Icons.edit_outlined),
                  onPressed: () => _edit(context)),
              IconButton(
                  icon: Icon(Icons.delete_outline, color: kAccent),
                  onPressed: () => _delete(context)),
            ],
          ),
          const SizedBox(height: 8),
          if (nationalities.isNotEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Wrap(
                spacing: 6,
                runSpacing: 4,
                children: [
                  for (final c in nationalities)
                    Chip(
                      label: Text(countryName(c)),
                      visualDensity: VisualDensity.compact,
                    ),
                ],
              ),
            ),
          for (final s in socials)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Row(
                children: [
                  const Icon(Icons.link, size: 18),
                  const SizedBox(width: 10),
                  Text('${socialNetworkLabel('${s['network']}')}: '
                      '${s['handle'] ?? ''}'),
                ],
              ),
            ),
          const SizedBox(height: 12),
          Text('Members', style: theme.textTheme.titleSmall),
          const SizedBox(height: 4),
          if (members.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child:
                  Text('No members yet.', style: theme.textTheme.bodySmall),
            )
          else
            Flexible(
              child: ListView(
                shrinkWrap: true,
                children: [
                  for (final p in members)
                    ListTile(
                      dense: true,
                      leading:
                          PersonAvatar(notifier: notifier, person: p, radius: 16),
                      title: Text(personDisplayName(p)),
                      onTap: () {
                        Navigator.of(context).pop();
                        showPersonDetailSheet(context, notifier, p);
                      },
                    ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
