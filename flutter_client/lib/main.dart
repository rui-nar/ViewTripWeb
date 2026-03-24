import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
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

class ViewTripApp extends StatelessWidget {
  const ViewTripApp({super.key});

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
        builder: (context) {
          final themeMode = context.watch<ThemeNotifier>().mode;
          return MaterialApp.router(
            title: 'ViewTripWeb',
            theme: lightTheme,
            darkTheme: darkTheme,
            themeMode: themeMode,
            routerConfig: buildRouter(context),
            debugShowCheckedModeBanner: false,
          );
        },
      ),
    );
  }
}
