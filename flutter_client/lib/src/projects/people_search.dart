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

/// Map of person id → that person's encounter notes, derived from project [items].
/// Used to make encounter descriptions searchable from the People list.
Map<int, List<String>> encounterNotesByPerson(
    List<Map<String, dynamic>> items) {
  final out = <int, List<String>>{};
  for (final it in items) {
    if (it['item_type'] != 'encounter') continue;
    final enc = it['encounter'];
    if (enc is! Map) continue;
    final pid = enc['person_id'];
    final note = (enc['description'] as String?)?.trim();
    if (pid is int && note != null && note.isNotEmpty) {
      (out[pid] ??= []).add(note);
    }
  }
  return out;
}

/// How many encounters each person has, derived from project [items].
Map<int, int> encounterCountByPerson(List<Map<String, dynamic>> items) {
  final out = <int, int>{};
  for (final it in items) {
    if (it['item_type'] != 'encounter') continue;
    final pid = (it['encounter'] as Map?)?['person_id'];
    if (pid is int) out[pid] = (out[pid] ?? 0) + 1;
  }
  return out;
}

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
