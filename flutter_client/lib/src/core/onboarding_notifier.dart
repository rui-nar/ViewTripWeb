/// Tracks whether the first-launch onboarding carousel has been shown, so it
/// only ever appears once per device (issue: Android launch UX). Loaded
/// synchronously in main() before runApp — see [readHasSeenOnboarding] —
/// rather than gated behind its own async isLoading flag, since a single
/// SharedPreferences read is fast enough to await before the first frame.
library;

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _kHasSeenOnboardingKey = 'has_seen_onboarding';

/// Reads the persisted onboarding flag. Called once in main(), before
/// runApp, so [OnboardingNotifier] can start with the real value.
Future<bool> readHasSeenOnboarding() async {
  final prefs = await SharedPreferences.getInstance();
  return prefs.getBool(_kHasSeenOnboardingKey) ?? false;
}

class OnboardingNotifier extends ChangeNotifier {
  OnboardingNotifier(this._hasSeenOnboarding);

  bool _hasSeenOnboarding;
  bool get hasSeenOnboarding => _hasSeenOnboarding;

  /// Marks onboarding as seen — persisted so it never shows again on this
  /// device, and notifies so the router's redirect re-evaluates immediately
  /// (skip and finish both call this before navigating to /login).
  Future<void> markSeen() async {
    if (_hasSeenOnboarding) return;
    _hasSeenOnboarding = true;
    notifyListeners();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_kHasSeenOnboardingKey, true);
  }
}
