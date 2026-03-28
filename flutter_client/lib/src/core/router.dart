import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../auth/auth_notifier.dart';
import '../auth/login_screen.dart';
import '../projects/projects_screen.dart';

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
      final onLogin = state.matchedLocation == '/login';

      // Wait for restoreSession to finish before redirecting.
      if (isLoading) return null;

      if (!isLoggedIn && !onLogin) return '/login';
      if (isLoggedIn && onLogin) return '/projects';
      return null;
    },

    routes: [
      GoRoute(
        path: '/login',
        builder: (context, state) => const LoginScreen(),
      ),
      GoRoute(
        path: '/projects',
        builder: (context, state) => const ProjectsScreen(),
      ),
    ],
  );
}
