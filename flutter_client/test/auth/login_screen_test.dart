// Widget tests for ServerConfigDialog (login_screen.dart's "Self-hosting?
// Click here" link): prefill from a saved override, validation, save/cancel
// round-trip through core/server_config.dart.
//
// LoginScreen itself isn't pumped here — it wires up GoogleSignIn in
// initState, which no existing test in this suite exercises either; the
// dialog is exposed as a standalone public widget precisely so this new
// logic can be tested in isolation from that.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:viewtrip_client/src/auth/login_screen.dart';
import 'package:viewtrip_client/src/core/server_config.dart';

/// Mutable box so a test can read the dialog's pop() result after tapping
/// Save/Cancel — showDialog()'s own return value isn't available until its
/// awaiting future resolves, which happens inside the pumped widget tree.
class _Result {
  bool? value;
}

Future<_Result> _pump(WidgetTester tester) async {
  final result = _Result();
  await tester.pumpWidget(MaterialApp(
    home: Builder(
      builder: (context) => ElevatedButton(
        onPressed: () async {
          result.value = await showDialog<bool>(
            context: context,
            builder: (_) => const ServerConfigDialog(),
          );
        },
        child: const Text('open'),
      ),
    ),
  ));
  await tester.tap(find.text('open'));
  await tester.pumpAndSettle();
  return result;
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('opens blank when no override is saved', (tester) async {
    await _pump(tester);

    final field = find.widgetWithText(TextField, 'Server URL');
    expect(field, findsOneWidget);
    expect(tester.widget<TextField>(field).controller!.text, isEmpty);
  });

  testWidgets('prefills the field with a previously saved override',
      (tester) async {
    await writeCustomServerUrl('https://home.example.com');

    await _pump(tester);

    expect(find.text('https://home.example.com'), findsOneWidget);
  });

  testWidgets('rejects a malformed URL without saving', (tester) async {
    await _pump(tester);

    await tester.enterText(
        find.widgetWithText(TextField, 'Server URL'), 'not-a-url');
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();

    expect(find.textContaining('Enter a full URL'), findsOneWidget);
    expect(await readCustomServerUrl(), isNull);
  });

  testWidgets('saves a valid URL and pops true', (tester) async {
    final result = await _pump(tester);

    await tester.enterText(
        find.widgetWithText(TextField, 'Server URL'), 'https://trax.example.com');
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();

    expect(result.value, isTrue);
    expect(await readCustomServerUrl(), 'https://trax.example.com');
  });

  testWidgets('Cancel pops false without saving', (tester) async {
    final result = await _pump(tester);

    await tester.enterText(
        find.widgetWithText(TextField, 'Server URL'), 'https://trax.example.com');
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();

    expect(result.value, isFalse);
    expect(await readCustomServerUrl(), isNull);
  });

  testWidgets('clearing the field back to empty removes a saved override',
      (tester) async {
    await writeCustomServerUrl('https://home.example.com');
    await _pump(tester);

    await tester.enterText(find.widgetWithText(TextField, 'Server URL'), '');
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();

    expect(await readCustomServerUrl(), isNull);
  });
}
