// Unit tests for the "last opened project" shared_preferences helper
// (issue #93): scoped per-user, write-then-read round trip, and the
// null-userId no-op guard used when auth hasn't resolved yet.

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:viewtrip_client/src/core/last_opened_project.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('saveLastOpenedProject then readLastOpenedProject round-trips', () async {
    await saveLastOpenedProject('user-1', 'Trip A');
    expect(await readLastOpenedProject('user-1'), 'Trip A');
  });

  test('is scoped per-user — user-2 has no value after user-1 writes', () async {
    await saveLastOpenedProject('user-1', 'Trip A');
    expect(await readLastOpenedProject('user-2'), isNull);
  });

  test('readLastOpenedProject returns null when nothing was ever saved', () async {
    expect(await readLastOpenedProject('user-1'), isNull);
  });

  test('saveLastOpenedProject is a no-op when userId is null', () async {
    await saveLastOpenedProject(null, 'Trip A');
    expect(await readLastOpenedProject('user-1'), isNull);
  });

  test('readLastOpenedProject returns null when userId is null', () async {
    await saveLastOpenedProject('user-1', 'Trip A');
    expect(await readLastOpenedProject(null), isNull);
  });

  test('a later save overwrites the earlier value for the same user', () async {
    await saveLastOpenedProject('user-1', 'Trip A');
    await saveLastOpenedProject('user-1', 'Trip B');
    expect(await readLastOpenedProject('user-1'), 'Trip B');
  });
}
