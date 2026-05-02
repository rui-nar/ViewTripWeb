/// Named routes + auth guard for the ViewTripWeb Flutter client.
library;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../auth/auth_notifier.dart';
import '../auth/login_screen.dart';
import '../auth/register_screen.dart';
import '../auth/welcome_screen.dart';
import '../projects/projects_screen.dart';
import '../projects/app_screen.dart';
import '../projects/view_screen.dart';
import '../projects/strava_import_screen.dart';
import '../projects/strava_import_notifier.dart';
import '../projects/project_stats_screen.dart';
import '../settings/settings_screen.dart';
import '../shared/shared_project_screen.dart';

/// On web, derive the starting location from the actual browser URL so that
/// deep links (e.g. /share/TOKEN) are honoured even before auth resolves.
/// Falls back to /login on non-web platforms.
String _initialLocation() {
  if (!kIsWeb) return '/';
  final path = Uri.base.path;
  return (path.isEmpty || path == '/') ? '/' : path;
}

GoRouter buildRouter(BuildContext context) {
  final authNotifier = context.read<AuthNotifier>();

  return GoRouter(
    initialLocation: _initialLocation(),
    // Re-evaluate redirect whenever auth state changes (login / logout / init).
    refreshListenable: authNotifier,

    redirect: (BuildContext ctx, GoRouterState state) {
      final auth = ctx.read<AuthNotifier>();

      // Wait for restoreSession to complete before making routing decisions.
      if (auth.isLoading) return null;

      final isLoggedIn = auth.user != null;
      // Use the real browser URL path, not matchedLocation, so that timing
      // issues during auth init don't cause stale-route redirects.
      final loc = state.uri.path;

      // Shared-project links are accessible without login.
      if (loc.startsWith('/share/')) return null;

      // Redirect unauthenticated users away from protected routes.
      final isPublicPage = loc == '/' || loc == '/login' || loc == '/register';
      if (!isLoggedIn && !isPublicPage) return '/';

      // Redirect authenticated users away from public pages.
      if (isLoggedIn && isPublicPage) return '/projects';

      return null;
    },

    routes: [
      GoRoute(
        path: '/',
        builder: (context, state) => const WelcomeScreen(),
      ),
      GoRoute(
        path: '/login',
        builder: (context, state) => const LoginScreen(),
      ),
      GoRoute(
        path: '/register',
        builder: (context, state) => const RegisterScreen(),
      ),
      GoRoute(
        path: '/projects',
        builder: (context, state) => const ProjectsScreen(),
      ),
      GoRoute(
        path: '/app',
        builder: (context, state) {
          final projectName =
              state.uri.queryParameters['project'] ?? '';
          return AppScreen(projectName: projectName);
        },
      ),
      GoRoute(
        path: '/view',
        builder: (context, state) {
          final projectName =
              state.uri.queryParameters['project'] ?? '';
          return ViewScreen(projectName: projectName);
        },
      ),
      GoRoute(
        path: '/strava-import',
        builder: (context, state) {
          final projectName =
              state.uri.queryParameters['project'] ?? '';
          return ChangeNotifierProvider(
            create: (_) => StravaImportNotifier(),
            child: StravaImportScreen(projectName: projectName),
          );
        },
      ),
      GoRoute(
        path: '/stats',
        builder: (context, state) {
          final projectName =
              state.uri.queryParameters['project'] ?? '';
          final extra = state.extra as Map<String, dynamic>? ?? {};
          final availableTags =
              (extra['tags'] as List?)?.cast<String>() ?? const <String>[];
          final sleepingOptionGroups =
              (extra['groups'] as Map?)?.cast<String, String>() ?? const <String, String>{};
          return ProjectStatsScreen(
              projectName: projectName,
              availableTags: availableTags,
              sleepingOptionGroups: sleepingOptionGroups);
        },
      ),
      GoRoute(
        path: '/settings',
        builder: (context, state) => const SettingsScreen(),
      ),
      GoRoute(
        path: '/share/:token',
        builder: (context, state) {
          final token = state.pathParameters['token']!;
          return SharedProjectScreen(token: token);
        },
      ),
    ],
  );
}
