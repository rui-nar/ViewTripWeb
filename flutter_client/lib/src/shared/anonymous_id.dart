import 'dart:math';

import 'package:shared_preferences/shared_preferences.dart';

const _kKey = 'anon_visitor_id';

Future<String> getOrCreateAnonId() async {
  final prefs = await SharedPreferences.getInstance();
  var id = prefs.getString(_kKey);
  if (id == null || id.isEmpty) {
    final r = Random.secure();
    id = List.generate(32, (_) => r.nextInt(16).toRadixString(16)).join();
    await prefs.setString(_kKey, id);
  }
  return id;
}
