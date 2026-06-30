import 'package:cryptography_plus/cryptography_plus.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:viewtrip_client/src/crypto/enable_encryption_screen.dart';
import 'package:viewtrip_client/src/crypto/encryption_service.dart';

class _FakeStore implements DeviceKeyStore {
  SimpleKeyPair? _kp;
  @override
  Future<SimpleKeyPair?> load() async => _kp;
  @override
  Future<void> save(SimpleKeyPair keyPair) async => _kp = keyPair;
}

class _FakeApi implements EncryptionApi {
  @override
  Future<void> enable(Map<String, dynamic> payload) async {}
  @override
  Future<EncryptionStatus> fetchStatus(String? d) async => const EncryptionStatus(
        enabled: false, recoveryMethods: [],
        deviceRegistered: false, deviceApproved: false,
      );
}

Widget _wrap() => MaterialApp(
      home: EnableEncryptionScreen(
        service: EncryptionService(_FakeStore(), _FakeApi()),
      ),
    );

void main() {
  testWidgets('renders the A/B recovery choice', (tester) async {
    await tester.pumpWidget(_wrap());
    expect(find.text('Recovery key  ·  Stronger'), findsOneWidget);
    expect(find.text('Security questions  ·  Easier'), findsOneWidget);
  });

  testWidgets('selecting security questions reveals the weaker-option warning',
      (tester) async {
    await tester.pumpWidget(_wrap());
    // The warning is not shown while the stronger option is selected.
    expect(find.textContaining('someone with access to the server'), findsNothing);

    await tester.tap(find.text('Security questions  ·  Easier'));
    await tester.pump();

    expect(find.textContaining('someone with access to the server'), findsOneWidget);
    expect(find.text('What was the name of your first pet?'), findsOneWidget);
  });

  testWidgets('recovery-key path reveals a one-time key to save', (tester) async {
    await tester.pumpWidget(_wrap());
    await tester.tap(find.text('Turn on encryption'));
    await tester.pumpAndSettle();

    expect(find.text('Save your recovery key'), findsOneWidget);
    // "Done" stays disabled until the user confirms they saved it.
    final doneBtn = tester.widget<FilledButton>(
      find.ancestor(of: find.text('Done'), matching: find.byType(FilledButton)),
    );
    expect(doneBtn.onPressed, isNull);

    await tester.tap(find.text("I've saved my recovery key somewhere safe"));
    await tester.pump();
    final doneBtn2 = tester.widget<FilledButton>(
      find.ancestor(of: find.text('Done'), matching: find.byType(FilledButton)),
    );
    expect(doneBtn2.onPressed, isNotNull);
  });
}
