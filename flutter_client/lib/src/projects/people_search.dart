/// Pure helpers for the People section (issue #40) — display name, encounter
/// grouping, and keyword search. Kept free of Flutter/IO so they are unit-testable
/// headless, and so search stays client-side (E2EE-ready).
library;

/// The label to show for a person: their name, or "Unknown" when unnamed.
String personDisplayName(Map<String, dynamic> person) {
  final name = (person['name'] as String?)?.trim();
  return (name == null || name.isEmpty) ? 'Unknown' : name;
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
