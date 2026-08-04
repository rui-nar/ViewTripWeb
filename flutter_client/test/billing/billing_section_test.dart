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
  int checkoutCalls = 0;
  int portalCalls = 0;

  _FakeBilling(this.payload);

  @override
  Future<BillingStatus> status() async => BillingStatus.fromJson(payload);

  @override
  Future<String> checkoutUrl({String? plan, String returnPath = '/settings'}) async {
    checkoutCalls++;
    return 'https://pay.test/checkout';
  }

  @override
  Future<String> portalUrl({String returnPath = '/settings'}) async {
    portalCalls++;
    return 'https://pay.test/portal';
  }

  @override
  Future<List<PlanInfo>> plans() async => const [
        PlanInfo(id: 'free', name: 'Free', priceLabel: 'Free', features: []),
        PlanInfo(id: 'tier_1', name: 'Tier 1', priceLabel: '€1 / month',
            features: []),
      ];
}

Future<void> _pump(
  WidgetTester tester,
  BillingService billing, {
  List<String>? opened,
  Uri? currentUri,
}) async {
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: BillingSection(
        service: billing,
        launcher: (url) async => opened?.add(url),
        currentUri: currentUri,
        retryDelay: Duration.zero,
      ),
    ),
  ));
  await tester.pumpAndSettle();
}

/// Returns each entry of [payloads] in turn, repeating the last one once
/// exhausted — for simulating a webhook that lands a few calls in.
class _SequenceBilling implements BillingService {
  final List<Map<String, dynamic>> payloads;
  int calls = 0;

  _SequenceBilling(this.payloads);

  @override
  Future<BillingStatus> status() async {
    final payload = payloads[calls < payloads.length ? calls : payloads.length - 1];
    calls++;
    return BillingStatus.fromJson(payload);
  }

  @override
  Future<String> checkoutUrl({String? plan, String returnPath = '/settings'}) async =>
      'https://pay.test/checkout';

  @override
  Future<String> portalUrl({String returnPath = '/settings'}) async =>
      'https://pay.test/portal';

  @override
  Future<List<PlanInfo>> plans() async => const [];
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
      'plan_name': 'Free',
      'status': 'none',
      'limits': {
        'max_projects': 1,
        'max_storage_bytes': 500 * 1024 * 1024,
        'max_trip_days': 10,
      },
      'usage': {'projects': 1, 'storage_bytes': 250 * 1024 * 1024},
    };

    testWidgets('shows the plan and its usage', (tester) async {
      await _pump(tester, _FakeBilling(free));
      expect(find.text('Plan'), findsOneWidget);
      expect(find.text('Free'), findsOneWidget);
      expect(find.text('1 / 1'), findsOneWidget);
      expect(find.text('250 MB / 500 MB'), findsOneWidget);
    });

    testWidgets('states the trip-length limit', (tester) async {
      await _pump(tester, _FakeBilling(free));
      expect(find.text('Trip length'), findsOneWidget);
      expect(find.text('up to 10 days'), findsOneWidget);
    });

    testWidgets('opens the plan picker to upgrade', (tester) async {
      await _pump(tester, _FakeBilling(free));
      await tester.tap(find.text('Upgrade'));
      await tester.pumpAndSettle();
      expect(find.text('Choose a plan'), findsOneWidget);
      expect(find.text('Choose Tier 1'), findsOneWidget);
    });

    testWidgets('hides "Manage billing" before the first purchase',
        (tester) async {
      await _pump(tester, _FakeBilling(free));
      expect(find.text('Manage billing'), findsNothing);
    });
  });

  group('paid plan', () {
    final cloud = {
      'billing_enabled': true,
      'plan': 'tier_3',
      'plan_name': 'Tier 3',
      'status': 'active',
      'limits': {
        'max_projects': null,
        'max_storage_bytes': 1024 * 1024 * 1024,
        'max_trip_days': null,
      },
      'usage': {'projects': 7, 'storage_bytes': 1024 * 1024},
    };

    testWidgets('names the tier and shows what is unlimited', (tester) async {
      await _pump(tester, _FakeBilling(cloud));
      expect(find.text('Tier 3'), findsOneWidget);
      expect(find.text('7 / unlimited'), findsOneWidget);
      expect(find.text('any length'), findsOneWidget);
    });

    testWidgets('offers a plan change rather than an upgrade', (tester) async {
      await _pump(tester, _FakeBilling(cloud));
      expect(find.text('Change plan'), findsOneWidget);
      expect(find.text('Upgrade'), findsNothing);
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

  group('returning from checkout (issue #192)', () {
    final free = {
      'billing_enabled': true,
      'plan': 'free',
      'plan_name': 'Free',
      'status': 'none',
      'limits': {'max_projects': 1, 'max_storage_bytes': 1, 'max_trip_days': 1},
      'usage': {'projects': 0, 'storage_bytes': 0},
    };
    final paid = {
      'billing_enabled': true,
      'plan': 'tier_1',
      'plan_name': 'Tier 1',
      'status': 'active',
      'limits': {'max_projects': 2, 'max_storage_bytes': 1, 'max_trip_days': 1},
      'usage': {'projects': 0, 'storage_bytes': 0},
    };

    testWidgets('without ?checkout=success, a free read is not retried',
        (tester) async {
      final billing = _SequenceBilling([free]);
      await _pump(tester, billing, currentUri: Uri.parse('https://x/settings'));
      expect(billing.calls, 1);
      expect(find.text('Free'), findsOneWidget);
    });

    testWidgets('?checkout=success but already paid needs no retry',
        (tester) async {
      final billing = _SequenceBilling([paid]);
      await _pump(tester,
          billing, currentUri: Uri.parse('https://x/settings?checkout=success'));
      expect(billing.calls, 1);
      expect(find.text('Tier 1'), findsOneWidget);
    });

    testWidgets(
        '?checkout=success retries until the webhook-updated plan shows',
        (tester) async {
      final billing = _SequenceBilling([free, free, paid]);
      await _pump(tester,
          billing, currentUri: Uri.parse('https://x/settings?checkout=success'));
      expect(billing.calls, 3);
      expect(find.text('Tier 1'), findsOneWidget);
    });

    testWidgets('gives up after 6 reads rather than retrying forever',
        (tester) async {
      final billing = _SequenceBilling([free]);
      await _pump(tester,
          billing, currentUri: Uri.parse('https://x/settings?checkout=success'));
      expect(billing.calls, 6); // 1 initial + 5 retries
      expect(find.text('Free'), findsOneWidget);
    });
  });
}
