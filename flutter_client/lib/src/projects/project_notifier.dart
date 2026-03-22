/// Notifier for a single open project — loads details + GeoJSON in parallel.
library;

import 'package:flutter/foundation.dart';

import 'project_service.dart';

class ProjectNotifier extends ChangeNotifier {
  final ProjectService _service;

  ProjectNotifier(this._service);

  String? projectName;
  List<Map<String, dynamic>> activities = [];
  Map<String, dynamic>? geo;
  bool isLoading = false;
  String? error;

  /// Loads project details and GeoJSON concurrently.
  Future<void> load(String name) async {
    if (name.isEmpty) return;
    projectName = name;
    isLoading = true;
    error = null;
    activities = [];
    geo = null;
    notifyListeners();

    try {
      final results = await Future.wait([
        _service.getDetails(name),
        _service.getGeo(name),
      ]);

      final details = results[0];
      final rawActivities = details['activities'];
      activities = rawActivities is List
          ? rawActivities.cast<Map<String, dynamic>>()
          : [];
      geo = results[1];
    } on Exception catch (e) {
      error = _msg(e);
    } finally {
      isLoading = false;
      notifyListeners();
    }
  }

  void clear() {
    projectName = null;
    activities = [];
    geo = null;
    isLoading = false;
    error = null;
    notifyListeners();
  }

  String _msg(Exception e) {
    final s = e.toString();
    final m = RegExp(r'"detail"\s*:\s*"([^"]+)"').firstMatch(s);
    return m?.group(1) ?? s.replaceFirst('Exception: ', '');
  }
}
