/// Named routes + auth guard for the ViewTripWeb Flutter client.
library;

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../auth/auth_notifier.dart';
import '../auth/login_screen.dart';
import '../auth/register_screen.dart';
import '../projects/projects_screen.dart';
import '../projects/app_screen.dart';

GoRouter buildRouter(BuildContext context) {
  final authNotifier = context.read<AuthNotifier>();

  return GoRouter(
    initialLocation: '/login',
    // Re-evaluate redirect whenever auth state changes (login / logout / init).
    refreshListenable: authNotifier,

    redirect: (BuildContext ctx, GoRouterState state) {
      final auth = ctx.read<AuthNotifier>();
      final isLoading = auth.isLoading;
      final isLoggedIn = auth.user != null;
      final loc = state.matchedLocation;
      final onPublic = loc == '/login' || loc == '/register';

      // Wait for restoreSession to complete before making routing decisions.
      if (isLoading) return null;

      if (!isLoggedIn && !onPublic) return '/login';
      if (isLoggedIn && onPublic) return '/projects';
      return null;
    },

    routes: [
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
    ],
  );
}
