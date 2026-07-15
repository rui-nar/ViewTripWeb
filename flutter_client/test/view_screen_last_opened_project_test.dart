// Regression test for issue #93: ViewScreen must only record a project as
// "last opened" after a *successful* load — never on failure, so a deleted/
// renamed project can never become the bare-root (`/`) redirect target.
//
// ViewProjectNotifier.loadView() always fails in this test sandbox (no host
// to talk to — same setup as view_screen_test.dart), which is exactly the
// scenario under test here: on error, no pref should be written.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:viewtrip_client/src/api/client.dart' show ApiException;
import 'package:viewtrip_client/src/auth/auth_notifier.dart';
import 'package:viewtrip_client/src/auth/auth_service.dart';
import 'package:viewtrip_client/src/projects/view_screen.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('does not save last-opened-project pref when loadView() errors',
      (tester) async {
    // As in view_screen_test.dart: every request fails with a fake network
    // error in this sandbox; ProjectNotifier.load() fires two requests
    // concurrently but only awaits one before its catch block returns — the
    // other's later rejection is an orphaned Future error unrelated to what's
    // under test here, so ignore just that.
    final previousReporter = reportTestException;
    reportTestException = (details, description) {
      if (details.exception is! ApiException) previousReporter(details, description);
    };

    final auth = AuthNotifier(AuthService());
    auth.updateUser(const {
      'id': 'user-1',
      'email': 'a@x.com',
      'display_name': 'A',
      'auth_provider': 'local',
    });

    await tester.pumpWidget(MaterialApp(
      home: ChangeNotifierProvider<AuthNotifier>.value(
        value: auth,
        child: const ViewScreen(projectName: 'Trip'),
      ),
    ));
    await tester.pump();
    reportTestException = previousReporter;

    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('last_opened_project_user-1'), isNull);

    // Flush the background geo-fetch retry backoff and the one-shot
    // background-sync-check timer so none remain pending at teardown
    // (mirrors view_screen_test.dart).
    await tester.pump(const Duration(seconds: 6));
  });
}
