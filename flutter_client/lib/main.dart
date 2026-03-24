import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:provider/provider.dart';

import 'src/auth/auth_service.dart';
import 'src/auth/auth_notifier.dart';
import 'src/projects/projects_service.dart';
import 'src/projects/projects_notifier.dart';
import 'src/projects/project_service.dart';
import 'src/projects/project_notifier.dart';
import 'src/settings/theme_notifier.dart';
import 'src/core/app_router.dart';
import 'src/core/theme.dart';

// Server client ID used on Android/iOS to receive an idToken.
// On web, GIS reads the client ID from <meta name="google-signin-client_id">
// in web/index.html — so serverClientId must be null on web.
const _kGoogleServerClientId =
    '544571555396-gj0q3hndadfo00ifotme305jcf4ii5cc.apps.googleusercontent.com';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // Initialize GoogleSignIn exactly once before the widget tree starts.
  await GoogleSignIn.instance.initialize(
    serverClientId: kIsWeb ? null : _kGoogleServerClientId,
  );
  runApp(const ViewTripApp());
}

class ViewTripApp extends StatefulWidget {
  const ViewTripApp({super.key});

  @override
  State<ViewTripApp> createState() => _ViewTripAppState();
}

class _ViewTripAppState extends State<ViewTripApp> {
  GoRouter? _router;

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider<ThemeNotifier>(
          create: (_) => ThemeNotifier(),
        ),
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
        builder: (innerContext) {
          final themeMode = innerContext.watch<ThemeNotifier>().mode;
          // Router is created once and reused — recreating it on every theme
          // change would destroy the navigation stack.
          _router ??= buildRouter(innerContext);
          return MaterialApp.router(
            title: 'ViewTripWeb',
            theme: lightTheme,
            darkTheme: darkTheme,
            themeMode: themeMode,
            routerConfig: _router!,
            debugShowCheckedModeBanner: false,
          );
        },
      ),
    );
  }
}
