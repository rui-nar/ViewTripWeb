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
