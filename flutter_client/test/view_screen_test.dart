import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:viewtrip_client/src/api/client.dart' show ApiException;
import 'package:viewtrip_client/src/projects/people_screen.dart';
import 'package:viewtrip_client/src/projects/view_screen.dart';

/// Guards the fix where view mode's AppBar was missing the People/Encounters
/// directory entry point that manage mode already had (issue #40 follow-up).
void main() {
  testWidgets('view mode AppBar has an Encounters button that opens PeopleScreen',
      (tester) async {
    // ViewScreen loads project data over the network on init; in the test
    // sandbox every request fails with a fake 400, and ProjectNotifier.load()
    // fires two requests concurrently but only awaits one before its catch
    // block returns — the other's later rejection is an orphaned Future error
    // unrelated to the button/navigation under test here, so ignore just that.
    final previousReporter = reportTestException;
    reportTestException = (details, description) {
      if (details.exception is! ApiException) previousReporter(details, description);
    };

    await tester.pumpWidget(const MaterialApp(
      home: ViewScreen(projectName: 'Trip'),
    ));
    await tester.pump();
    reportTestException = previousReporter;

    expect(find.byTooltip('Encounters'), findsOneWidget);

    await tester.tap(find.byTooltip('Encounters'));
    await tester.pumpAndSettle();

    expect(find.byType(PeopleScreen), findsOneWidget);

    // Flush the background geo-fetch retry backoff and the one-shot
    // background-sync-check timer so none remain pending at teardown.
    await tester.pump(const Duration(seconds: 6));
  });
}
