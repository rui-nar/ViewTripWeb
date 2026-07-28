/// The upgrade prompt shown when the server refuses on a plan limit (#121).
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:viewtrip_client/src/billing/billing_service.dart';
import 'package:viewtrip_client/src/billing/upgrade_sheet.dart';

const _tripLimit = QuotaError(
  resource: 'projects',
  plan: 'free',
  detail: 'Your plan includes 1 trip. Upgrade to create more.',
  limit: 1,
  used: 1,
);

const _storageFull = QuotaError(
  resource: 'storage',
  plan: 'free',
  detail: "This upload would exceed your plan's storage.",
  limit: 500,
  used: 500,
);

Future<void> _pump(
  WidgetTester tester,
  QuotaError error, {
  Future<String> Function()? onUpgrade,
  List<String>? opened,
}) async {
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: UpgradeSheet(
        error: error,
        onUpgrade: onUpgrade ?? () async => 'https://pay.test/checkout',
        launcher: (url) async => opened?.add(url),
      ),
    ),
  ));
}

void main() {
  testWidgets('a trip limit reads as a limit, not an error', (tester) async {
    await _pump(tester, _tripLimit);
    expect(find.text('Trip limit reached'), findsOneWidget);
    expect(find.text(_tripLimit.detail), findsOneWidget);
  });

  testWidgets('a storage limit gets its own heading', (tester) async {
    await _pump(tester, _storageFull);
    expect(find.text('Storage is full'), findsOneWidget);
  });

  testWidgets('upgrading opens the checkout url', (tester) async {
    final opened = <String>[];
    await _pump(tester, _tripLimit, opened: opened);
    await tester.tap(find.text('Upgrade'));
    await tester.pumpAndSettle();
    expect(opened, ['https://pay.test/checkout']);
  });

  testWidgets('a failed checkout keeps the sheet open and explains',
      (tester) async {
    await _pump(tester, _tripLimit,
        onUpgrade: () async => throw Exception('provider down'));
    await tester.tap(find.text('Upgrade'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Could not start checkout'), findsOneWidget);
    expect(find.text('Upgrade'), findsOneWidget);
  });

  testWidgets('an empty checkout url is treated as a failure', (tester) async {
    final opened = <String>[];
    await _pump(tester, _tripLimit, onUpgrade: () async => '', opened: opened);
    await tester.tap(find.text('Upgrade'));
    await tester.pumpAndSettle();
    expect(opened, isEmpty);
    expect(find.textContaining('Could not start checkout'), findsOneWidget);
  });

  testWidgets('"Not now" is always available', (tester) async {
    await _pump(tester, _tripLimit);
    expect(find.text('Not now'), findsOneWidget);
  });
}
