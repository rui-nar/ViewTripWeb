/// Native-mobile detection, shared by the router (onboarding entry point)
/// and the login screen (self-hosting server override).
library;

import 'package:flutter/foundation.dart'
    show kIsWeb, defaultTargetPlatform, TargetPlatform;

/// True on an installed Android/iOS build. False on web (including a mobile
/// browser, where [defaultTargetPlatform] reflects the host OS) and on
/// desktop, so the marketing [WelcomeScreen] and its self-hosted-Docker
/// story stay unaffected.
bool get isNativeMobile =>
    !kIsWeb &&
    (defaultTargetPlatform == TargetPlatform.android ||
        defaultTargetPlatform == TargetPlatform.iOS);
