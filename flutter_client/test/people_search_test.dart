import 'package:flutter_test/flutter_test.dart';

import 'package:viewtrip_client/src/projects/people_search.dart';

Map<String, dynamic> _p(int id, {String? name, String? email, String? phone,
    String? polarsteps, String? notes}) => {
      'id': id, 'name': name, 'email': email, 'phone': phone,
      'polarsteps': polarsteps, 'notes': notes,
    };

Map<String, dynamic> _enc(int personId, {String? note}) => {
      'item_type': 'encounter',
      'encounter': {'person_id': personId, 'description': note},
    };

void main() {
  group('personDisplayName', () {
    test('falls back to Unknown when name is missing or blank', () {
      expect(personDisplayName(_p(1)), 'Unknown');
      expect(personDisplayName(_p(1, name: '  ')), 'Unknown');
      expect(personDisplayName(_p(1, name: 'Alice')), 'Alice');
    });
  });

  group('groups (#50)', () {
    test('groupDisplayName falls back to "Group" when unnamed', () {
      expect(groupDisplayName({'id': 1}), 'Group');
      expect(groupDisplayName({'id': 1, 'name': '  '}), 'Group');
      expect(groupDisplayName({'id': 1, 'name': 'Crew'}), 'Crew');
    });

    test('memberCountByGroup + membersOfGroup partition people by group_id', () {
      final people = [
        {'id': 1, 'name': 'A', 'group_id': 10},
        {'id': 2, 'name': 'B', 'group_id': 10},
        {'id': 3, 'name': 'C', 'group_id': 20},
        {'id': 4, 'name': 'D', 'group_id': null},
      ];
      expect(memberCountByGroup(people), {10: 2, 20: 1});
      expect(membersOfGroup(people, 10).map((p) => p['id']), [1, 2]);
      expect(membersOfGroup(people, 99), isEmpty);
    });

    test('classifyEncounterPin masks grouped people behind their group', () {
      final peopleById = {
        1: {'id': 1, 'name': 'A', 'group_id': 10},
        2: {'id': 2, 'name': 'B'}, // ungrouped
      };
      final groupsById = {
        10: {'id': 10, 'name': 'Crew'},
      };
      // Grouped person → group pin.
      final g = classifyEncounterPin(1, peopleById, groupsById)!;
      expect(g.kind, 'group');
      expect(g.entity['name'], 'Crew');
      // Ungrouped person → person pin.
      final p = classifyEncounterPin(2, peopleById, groupsById)!;
      expect(p.kind, 'person');
      expect(p.entity['name'], 'B');
      // Unknown person → null.
      expect(classifyEncounterPin(99, peopleById, groupsById), isNull);
      // Grouped but the group is missing → fall back to person.
      final orphan = classifyEncounterPin(1, peopleById, {})!;
      expect(orphan.kind, 'person');
    });
  });

  group('encounter aggregation', () {
    test('counts and collects notes per person', () {
      final items = [
        _enc(1, note: 'cafe'),
        _enc(1, note: 'beach'),
        _enc(2, note: 'trail'),
        {'item_type': 'activity'},
      ];
      expect(encounterCountByPerson(items), {1: 2, 2: 1});
      expect(encounterNotesByPerson(items), {1: ['cafe', 'beach'], 2: ['trail']});
    });
  });

  group('filterPeople', () {
    final people = [
      _p(1, name: 'Alice', email: 'alice@x.com', polarsteps: 'al_ps'),
      _p(2, name: 'Bob', phone: '555-123', notes: 'guide in Nepal'),
      _p(3), // Unknown
    ];

    test('blank query returns everyone', () {
      expect(filterPeople(people, '   ', {}).length, 3);
    });

    test('matches name case-insensitively', () {
      final r = filterPeople(people, 'ALI', {});
      expect(r.map((p) => p['id']), [1]);
    });

    test('matches email, phone, polarsteps and notes fields', () {
      expect(filterPeople(people, 'x.com', {}).map((p) => p['id']), [1]);
      expect(filterPeople(people, '555', {}).map((p) => p['id']), [2]);
      expect(filterPeople(people, 'al_ps', {}).map((p) => p['id']), [1]);
      expect(filterPeople(people, 'nepal', {}).map((p) => p['id']), [2]);
    });

    test('matches on a person\'s encounter notes', () {
      final notes = {3: ['met at the summit hut']};
      final r = filterPeople(people, 'summit', notes);
      expect(r.map((p) => p['id']), [3]);
    });

    test('no match returns empty', () {
      expect(filterPeople(people, 'zzz', {}), isEmpty);
    });
  });
}
