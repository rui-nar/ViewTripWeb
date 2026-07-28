/// The Plan section of Settings (issue #121).
///
/// The load-bearing case is the self-hosted one: a deployment that sells
/// nothing must render no billing UI at all.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:viewtrip_client/src/billing/billing_section.dart';
import 'package:viewtrip_client/src/billing/billing_service.dart';

class _FakeBilling implements BillingService {
  final Map<String, dynamic> payload;
  final bool failCheckout;
  int checkoutCalls = 0;
  int portalCalls = 0;

  _FakeBilling(this.payload, {this.failCheckout = false});

  @override
  Future<BillingStatus> status() async => BillingStatus.fromJson(payload);

  @override
  Future<String> checkoutUrl({String returnPath = '/settings'}) async {
    checkoutCalls++;
    if (failCheckout) throw Exception('nope');
    return 'https://pay.test/checkout';
  }

  @override
  Future<String> portalUrl({String returnPath = '/settings'}) async {
    portalCalls++;
    return 'https://pay.test/portal';
  }

  @override
  Future<List<PlanInfo>> plans() async => const [];
}

Future<void> _pump(
  WidgetTester tester,
  _FakeBilling billing, {
  List<String>? opened,
}) async {
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: BillingSection(
        service: billing,
        launcher: (url) async => opened?.add(url),
      ),
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  group('self-hosted', () {
    testWidgets('renders nothing when billing is disabled', (tester) async {
      await _pump(tester, _FakeBilling({'billing_enabled': false}));
      expect(find.text('Plan'), findsNothing);
      expect(find.byType(Card), findsNothing);
    });
  });

  group('free plan', () {
    final free = {
      'billing_enabled': true,
      'plan': 'free',
      'status': 'none',
      'limits': {'max_projects': 1, 'max_storage_bytes': 500 * 1024 * 1024},
      'usage': {'projects': 1, 'storage_bytes': 250 * 1024 * 1024},
    };

    testWidgets('shows the plan and its usage', (tester) async {
      await _pump(tester, _FakeBilling(free));
      expect(find.text('Plan'), findsOneWidget);
      expect(find.text('Free'), findsOneWidget);
      expect(find.text('1 / 1'), findsOneWidget);
      expect(find.text('250 MB / 500 MB'), findsOneWidget);
    });

    testWidgets('offers an upgrade', (tester) async {
      final billing = _FakeBilling(free);
      final opened = <String>[];
      await _pump(tester, billing, opened: opened);
      await tester.tap(find.text('Upgrade to Cloud'));
      await tester.pumpAndSettle();
      expect(billing.checkoutCalls, 1);
      expect(opened, ['https://pay.test/checkout']);
    });

    testWidgets('hides "Manage billing" before the first purchase',
        (tester) async {
      await _pump(tester, _FakeBilling(free));
      expect(find.text('Manage billing'), findsNothing);
    });

    testWidgets('a failed checkout says so instead of doing nothing',
        (tester) async {
      await _pump(tester, _FakeBilling(free, failCheckout: true));
      await tester.tap(find.text('Upgrade to Cloud'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Could not reach'), findsOneWidget);
    });
  });

  group('paid plan', () {
    final cloud = {
      'billing_enabled': true,
      'plan': 'cloud',
      'status': 'active',
      'limits': {'max_projects': null, 'max_storage_bytes': 1024 * 1024 * 1024},
      'usage': {'projects': 7, 'storage_bytes': 1024 * 1024},
    };

    testWidgets('shows unlimited trips and no upgrade button', (tester) async {
      await _pump(tester, _FakeBilling(cloud));
      expect(find.text('Cloud'), findsOneWidget);
      expect(find.text('7 / unlimited'), findsOneWidget);
      expect(find.text('Upgrade to Cloud'), findsNothing);
    });

    testWidgets('opens the billing portal', (tester) async {
      final billing = _FakeBilling(cloud);
      final opened = <String>[];
      await _pump(tester, billing, opened: opened);
      await tester.tap(find.text('Manage billing'));
      await tester.pumpAndSettle();
      expect(billing.portalCalls, 1);
      expect(opened, ['https://pay.test/portal']);
    });

    testWidgets('flags a subscription that is ending', (tester) async {
      await _pump(tester, _FakeBilling({...cloud, 'cancel_at_period_end': true}));
      expect(find.text('Ends soon'), findsOneWidget);
    });

    testWidgets('flags a failed payment', (tester) async {
      await _pump(tester, _FakeBilling({...cloud, 'status': 'past_due'}));
      expect(find.text('Payment failed'), findsOneWidget);
    });

    testWidgets('flags a comped account', (tester) async {
      await _pump(tester, _FakeBilling({...cloud, 'admin_override': true}));
      expect(find.text('Granted'), findsOneWidget);
    });
  });
}
