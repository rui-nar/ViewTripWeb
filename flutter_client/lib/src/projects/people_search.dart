/// Pure helpers for the People section (issue #40) — display name, encounter
/// grouping, and keyword search. Kept free of Flutter/IO so they are unit-testable
/// headless, and so search stays client-side (E2EE-ready).
library;

/// The label to show for a person: their name, or "Unknown" when unnamed.
String personDisplayName(Map<String, dynamic> person) {
  final name = (person['name'] as String?)?.trim();
  return (name == null || name.isEmpty) ? 'Unknown' : name;
}

/// The label to show for a group: its name, or "Group" when unnamed (issue #50).
String groupDisplayName(Map<String, dynamic> group) {
  final name = (group['name'] as String?)?.trim();
  return (name == null || name.isEmpty) ? 'Group' : name;
}

/// How many people belong to each group id, derived from the people list (#50).
Map<int, int> memberCountByGroup(List<Map<String, dynamic>> people) {
  final out = <int, int>{};
  for (final p in people) {
    final gid = p['group_id'];
    if (gid is int) out[gid] = (out[gid] ?? 0) + 1;
  }
  return out;
}

/// The people belonging to [groupId] (issue #50).
List<Map<String, dynamic>> membersOfGroup(
        List<Map<String, dynamic>> people, int groupId) =>
    [for (final p in people) if (p['group_id'] == groupId) p];

/// Classify an encounter's map pin: a **group** pin either when the encounter
/// directly references a group (issue #56), or when its person belongs to a
/// group (the individual is masked, issue #50); else a **person** pin. Returns
/// null when neither the group nor the person resolves. [kind] is 'group' or
/// 'person'; [entity] is the group/person map to render + open.
({String kind, Map<String, dynamic> entity})? classifyEncounterPin(
  int? personId,
  int? groupId,
  Map<int, Map<String, dynamic>> peopleById,
  Map<int, Map<String, dynamic>> groupsById,
) {
  if (groupId != null) {
    final group = groupsById[groupId];
    return group != null ? (kind: 'group', entity: group) : null;
  }
  if (personId == null) return null;
  final person = peopleById[personId];
  if (person == null) return null;
  final gid = person['group_id'];
  if (gid is int) {
    final group = groupsById[gid];
    if (group != null) return (kind: 'group', entity: group);
  }
  return (kind: 'person', entity: person);
}

/// The label for an encounter a person inherited from the group they belong to
/// (issue #124 — `source: "group"` in the `GET /api/people/{id}` payload), or
/// null for a direct, one-to-one encounter with that person.
String? inheritedGroupLabel(Map<String, dynamic> encounter) {
  if (encounter['source'] != 'group') return null;
  final name = (encounter['group_name'] as String?)?.trim();
  return 'With ${(name == null || name.isEmpty) ? 'the group' : name}';
}

/// Map of person id → every encounter that applies to them, derived from project
/// [items] and [people]: the ones logged against the person, plus the ones
/// logged directly against the group they belong to (issue #124 — meeting the
/// group means meeting its members). Encounter order follows [items].
Map<int, List<Map<String, dynamic>>> encountersByPerson(
  List<Map<String, dynamic>> items,
  List<Map<String, dynamic>> people,
) {
  final membersByGroup = <int, List<int>>{};
  for (final p in people) {
    final gid = p['group_id'];
    final pid = p['id'];
    if (gid is int && pid is int) (membersByGroup[gid] ??= []).add(pid);
  }
  final out = <int, List<Map<String, dynamic>>>{};
  for (final it in items) {
    if (it['item_type'] != 'encounter') continue;
    final enc = it['encounter'];
    if (enc is! Map) continue;
    final e = enc.cast<String, dynamic>();
    final pid = e['person_id'];
    if (pid is int) {
      (out[pid] ??= []).add(e);
      continue;
    }
    final gid = e['group_id'];
    if (gid is int) {
      for (final memberId in membersByGroup[gid] ?? const <int>[]) {
        (out[memberId] ??= []).add(e);
      }
    }
  }
  return out;
}

/// Map of person id → that person's encounter notes (own + inherited from their
/// group, see [encountersByPerson]). Used to make encounter descriptions
/// searchable from the People list.
Map<int, List<String>> encounterNotesByPerson(
  List<Map<String, dynamic>> items,
  List<Map<String, dynamic>> people,
) {
  final out = <int, List<String>>{};
  encountersByPerson(items, people).forEach((pid, encounters) {
    final notes = [
      for (final e in encounters)
        if (((e['description'] as String?)?.trim() ?? '').isNotEmpty)
          (e['description'] as String).trim(),
    ];
    if (notes.isNotEmpty) out[pid] = notes;
  });
  return out;
}

/// How many encounters each person has — their own plus the ones inherited from
/// their group (see [encountersByPerson]).
Map<int, int> encounterCountByPerson(
  List<Map<String, dynamic>> items,
  List<Map<String, dynamic>> people,
) =>
    encountersByPerson(items, people)
        .map((pid, encounters) => MapEntry(pid, encounters.length));

/// Map of group id → that group's encounter notes, derived from project
/// [items] (issue #56 — direct group encounters, mirrors [encounterNotesByPerson]).
Map<int, List<String>> encounterNotesByGroup(
    List<Map<String, dynamic>> items) {
  final out = <int, List<String>>{};
  for (final it in items) {
    if (it['item_type'] != 'encounter') continue;
    final enc = it['encounter'];
    if (enc is! Map) continue;
    final gid = enc['group_id'];
    final note = (enc['description'] as String?)?.trim();
    if (gid is int && note != null && note.isNotEmpty) {
      (out[gid] ??= []).add(note);
    }
  }
  return out;
}

/// How many direct encounters each group has, derived from project [items]
/// (issue #56, mirrors [encounterCountByPerson]).
Map<int, int> encounterCountByGroup(List<Map<String, dynamic>> items) {
  final out = <int, int>{};
  for (final it in items) {
    if (it['item_type'] != 'encounter') continue;
    final gid = (it['encounter'] as Map?)?['group_id'];
    if (gid is int) out[gid] = (out[gid] ?? 0) + 1;
  }
  return out;
}

/// The encounter maps (date/time/description/...) logged directly against
/// [groupId], derived from project [items] (issue #56).
List<Map<String, dynamic>> encountersForGroup(
    List<Map<String, dynamic>> items, int groupId) {
  final out = <Map<String, dynamic>>[];
  for (final it in items) {
    if (it['item_type'] != 'encounter') continue;
    final enc = it['encounter'];
    if (enc is! Map) continue;
    if (enc['group_id'] == groupId) out.add(enc.cast<String, dynamic>());
  }
  return out;
}

/// Filter [people] by [query], matching a person's own text fields (name, email,
/// phone, polarsteps, notes) OR any of their encounter notes. An empty/blank
/// query returns everyone. Case-insensitive, substring match.
List<Map<String, dynamic>> filterPeople(
  List<Map<String, dynamic>> people,
  String query,
  Map<int, List<String>> notesByPerson,
) {
  final q = query.trim().toLowerCase();
  if (q.isEmpty) return List<Map<String, dynamic>>.from(people);
  return people.where((p) {
    final haystack = <String?>[
      p['name'] as String?,
      p['email'] as String?,
      p['phone'] as String?,
      p['polarsteps'] as String?,
      p['notes'] as String?,
      ...?notesByPerson[p['id']],
    ];
    return haystack.any((s) => s != null && s.toLowerCase().contains(q));
  }).toList();
}
