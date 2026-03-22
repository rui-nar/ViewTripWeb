import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'src/auth/auth_service.dart';
import 'src/auth/auth_notifier.dart';
import 'src/projects/projects_service.dart';
import 'src/projects/projects_notifier.dart';
import 'src/projects/project_service.dart';
import 'src/projects/project_notifier.dart';
import 'src/core/app_router.dart';
import 'src/core/theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const ViewTripApp());
}

class ViewTripApp extends StatelessWidget {
  const ViewTripApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider<AuthNotifier>(
          // ..init() restores a persisted JWT session immediately on creation.
          create: (_) => AuthNotifier(AuthService())..init(),
        ),
        ChangeNotifierProxyProvider<AuthNotifier, ProjectsNotifier>(
          create: (_) => ProjectsNotifier(ProjectsService()),
          // Reload projects on login; clear them on logout.
          update: (_, auth, previous) =>
              previous!..onAuthChanged(auth.user != null),
        ),
        ChangeNotifierProvider<ProjectNotifier>(
          create: (_) => ProjectNotifier(ProjectService()),
        ),
      ],
      child: Builder(
        builder: (context) => MaterialApp.router(
          title: 'ViewTripWeb',

          // Light / dark themes follow the OS preference automatically.
          // TODO: Replace ThemeMode.system with a ThemeNotifier backed by
          // shared_preferences once the Settings screen is added, so users
          // can override the system preference (Light / Dark / System).
          theme: lightTheme,
          darkTheme: darkTheme,
          themeMode: ThemeMode.system,

          routerConfig: buildRouter(context),
          debugShowCheckedModeBanner: false,
        ),
      ),
    );
  }
}
