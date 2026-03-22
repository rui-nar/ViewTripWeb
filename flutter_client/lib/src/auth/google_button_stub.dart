/// Stub for non-web platforms — renderButton is never called on mobile
/// (the login_screen uses a regular OutlinedButton instead).
library;

import 'package:flutter/material.dart';
import 'package:google_sign_in/google_sign_in.dart';

Widget buildGoogleSignInButton(GoogleSignIn googleSignIn) =>
    const SizedBox.shrink();
