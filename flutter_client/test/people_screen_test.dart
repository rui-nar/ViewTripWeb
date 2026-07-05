import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:viewtrip_client/src/projects/people_screen.dart';
import 'package:viewtrip_client/src/projects/project_notifier.dart';
import 'package:viewtrip_client/src/projects/project_service.dart';

ProjectNotifier _notifier() {
  final n = ProjectNotifier(ProjectService())..projectName = 'Trip';
  n.people = [
    {'id': 1, 'name': 'Alice', 'email': 'alice@x.com'},
    {'id': 2, 'name': 'Bob'},
    {'id': 3}, // unnamed → "Unknown"
  ];
  n.items = [
    {'item_type': 'encounter', 'encounter': {'person_id': 1, 'description': 'summit hut'}},
  ];
  return n;
}

void main() {
  testWidgets('lists people and shows Unknown for unnamed', (tester) async {
    await tester.pumpWidget(MaterialApp(home: PeopleScreen(notifier: _notifier())));
    await tester.pump();
    expect(find.text('Alice'), findsOneWidget);
    expect(find.text('Bob'), findsOneWidget);
    expect(find.text('Unknown'), findsOneWidget);
  });

  testWidgets('search filters by person field', (tester) async {
    await tester.pumpWidget(MaterialApp(home: PeopleScreen(notifier: _notifier())));
    await tester.pump();
    await tester.enterText(find.byType(TextField).first, 'bob');
    await tester.pump();
    expect(find.text('Bob'), findsOneWidget);
    expect(find.text('Alice'), findsNothing);
  });

  testWidgets('search matches encounter notes', (tester) async {
    await tester.pumpWidget(MaterialApp(home: PeopleScreen(notifier: _notifier())));
    await tester.pump();
    await tester.enterText(find.byType(TextField).first, 'summit');
    await tester.pump();
    // Only Alice (person 1) has the "summit hut" encounter note.
    expect(find.text('Alice'), findsOneWidget);
    expect(find.text('Bob'), findsNothing);
  });
}
