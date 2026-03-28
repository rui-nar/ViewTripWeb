/// Web implementation — renders Google's official GIS button via
/// google_sign_in_web/web_only.dart. The button fires onCurrentUserChanged
/// on the GoogleSignIn instance when the user authenticates.
library;

import 'package:flutter/material.dart';
import 'package:google_sign_in_web/web_only.dart' as gsi_web;

Widget buildGoogleSignInButton() {
  return SizedBox(
    height: 44,
    child: gsi_web.renderButton(),
  );
}
