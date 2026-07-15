// Tests for the bare-root (`/`) redirect target used by app_router.dart's
// `redirect` callback (issue #93): a logged-in user hitting `/` should land
// on their last-opened project instead of /projects, when one is recorded.
//
// NOTE: this deliberately does NOT import app_router.dart / buildRouter().
// app_router.dart's `/app` route pulls in app_screen.dart, which imports
// `dart:html` (web-only, by design — see app_screen.dart's file header).
// `dart:html` is not available on the VM platform flutter_test runs under
// by default (confirmed: any test that imports app_screen.dart, even
// transitively, fails to compile with "Dart library 'dart:html' is not
// available on this platform" — and this repo's CI (.github/workflows/test.yml)
// doesn't run `flutter test` at all, only the Python backend suite). So
// app_router.dart's redirect logic can't be exercised end-to-end via a real
// GoRouter in this test suite. Instead, the `/`-specific decision it defers
// to — rootRedirectTarget() in last_opened_project.dart — is tested directly
// here; app_router.dart's own change is a one-line call to it (see
// app_router.dart's `redirect` callback), verified by `flutter analyze` and
// by reading the diff.

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:viewtrip_client/src/auth/auth_notifier.dart';
import 'package:viewtrip_client/src/auth/auth_service.dart';
import 'package:viewtrip_client/src/core/last_opened_project.dart';

AuthNotifier _loggedInAuth(String userId) {
  final auth = AuthNotifier(AuthService());
  auth.updateUser({
    'id': userId,
    'email': 'a@x.com',
    'display_name': 'A',
    'auth_provider': 'local',
  });
  return auth;
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test(
      'resolves to /view?project=<name> when a last-opened project pref is set',
      () async {
    final auth = _loggedInAuth('user-1');
    await saveLastOpenedProject(auth.user!.id, 'Trip A');

    final target = await rootRedirectTarget(auth.user?.id);

    expect(target, '/view?project=Trip%20A');
  });

  test('resolves to /projects when no last-opened project pref is set',
      () async {
    final auth = _loggedInAuth('user-1');

    final target = await rootRedirectTarget(auth.user?.id);

    expect(target, '/projects');
  });

  test('resolves to /projects for a different user than the one who saved',
      () async {
    final saver = _loggedInAuth('user-1');
    await saveLastOpenedProject(saver.user!.id, 'Trip A');
    final otherUser = _loggedInAuth('user-2');

    final target = await rootRedirectTarget(otherUser.user?.id);

    expect(target, '/projects');
  });
}
