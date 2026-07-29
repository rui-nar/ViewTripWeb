// Tests for the brand splash and the gate that shows it
// (lib/src/core/splash_screen.dart).
//
// Two things matter here. First, the layout switch: the design has a stacked
// board and a side-by-side one, and only the wide board carries the blurb, the
// rule and the "Loading" label.
//
// Second, and the reason AuthNotifier gained isRestoring: the splash must cover
// the app while a persisted session is restored at start-up, and must *not*
// come back over the login form during an interactive sign-in. Both states used
// to be the single isLoading flag.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:viewtrip_client/src/auth/auth_notifier.dart';
import 'package:viewtrip_client/src/auth/auth_service.dart';
import 'package:viewtrip_client/src/core/brand_mark.dart';
import 'package:viewtrip_client/src/core/splash_screen.dart';

/// Lets a test drive the two loading flags independently, which the real
/// notifier only ever does from inside a network call.
class _FakeAuth extends AuthNotifier {
  _FakeAuth() : super(AuthService());

  bool restoring = false;
  bool signingIn = false;

  @override
  bool get isRestoring => restoring;

  @override
  bool get isLoading => signingIn;

  void publish() => notifyListeners();
}

Future<void> _pumpSplash(WidgetTester tester, Size size) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  await tester.pumpWidget(const MaterialApp(home: SplashScreen()));
  await tester.pump();
}

Future<void> _pumpGate(WidgetTester tester, _FakeAuth auth) async {
  tester.view.physicalSize = const Size(400, 800);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  await tester.pumpWidget(
    ChangeNotifierProvider<AuthNotifier>.value(
      value: auth,
      child: const MaterialApp(
        home: SplashGate(child: Text('the app')),
      ),
    ),
  );
  await tester.pump();
}

void main() {
  group('SplashScreen layout', () {
    testWidgets('below the breakpoint it stacks, with no wide-only pieces',
        (tester) async {
      await _pumpSplash(tester, const Size(390, 844));

      expect(find.byType(BrandMark), findsOneWidget);
      expect(find.text('TraxJourney'), findsOneWidget);
      expect(find.text('MERGE · VISUALISE · EXPORT'), findsOneWidget);
      // The blurb and the "Loading" label belong to the large board only.
      expect(find.textContaining('one continuous journey'), findsNothing);
      expect(find.text('Loading'), findsNothing);
    });

    testWidgets('at the breakpoint it switches to the wide board',
        (tester) async {
      await _pumpSplash(tester, const Size(kSplashWideBreakpoint, 900));

      expect(find.byType(BrandMark), findsOneWidget);
      expect(find.text('TraxJourney'), findsOneWidget);
      expect(find.textContaining('one continuous journey'), findsOneWidget);
      expect(find.text('Loading'), findsOneWidget);
    });

    testWidgets('one pixel under the breakpoint is still the stacked board',
        (tester) async {
      await _pumpSplash(tester, const Size(kSplashWideBreakpoint - 1, 900));

      expect(find.text('Loading'), findsNothing);
    });

    testWidgets('the mark grows on the wide board', (tester) async {
      await _pumpSplash(tester, const Size(390, 844));
      final stacked = tester.getSize(find.byType(BrandMark));

      await _pumpSplash(tester, const Size(1200, 900));
      final wide = tester.getSize(find.byType(BrandMark));

      expect(wide.width, greaterThan(stacked.width));
    });

    testWidgets('shows the build version, which is "dev" untouched by a define',
        (tester) async {
      await _pumpSplash(tester, const Size(390, 844));

      expect(find.text('dev'), findsOneWidget);
    });

    testWidgets('lays out without overflow on a short, wide window',
        (tester) async {
      await _pumpSplash(tester, const Size(1000, 420));

      expect(tester.takeException(), isNull);
    });
  });

  group('SplashGate', () {
    testWidgets('covers the app while a session is being restored',
        (tester) async {
      final auth = _FakeAuth()..restoring = true;
      await _pumpGate(tester, auth);

      expect(find.byType(SplashScreen), findsOneWidget);
    });

    testWidgets('uncovers the app once the restore finishes', (tester) async {
      final auth = _FakeAuth()..restoring = true;
      await _pumpGate(tester, auth);
      expect(find.byType(SplashScreen), findsOneWidget);

      auth
        ..restoring = false
        ..publish();
      await tester.pump();

      expect(find.byType(SplashScreen), findsNothing);
      expect(find.text('the app'), findsOneWidget);
    });

    testWidgets('does not reappear for an interactive sign-in', (tester) async {
      // The regression isRestoring exists to prevent: loginWithPassword also
      // raises isLoading, and keying the splash off that flag would throw it
      // back over the login form on every attempt.
      final auth = _FakeAuth()
        ..restoring = false
        ..signingIn = true;
      await _pumpGate(tester, auth);

      expect(find.byType(SplashScreen), findsNothing);
      expect(find.text('the app'), findsOneWidget);
    });
  });
}
