import 'package:flutter/foundation.dart';

import '../api/client.dart';

class StravaImportNotifier extends ChangeNotifier {
  List<Map<String, dynamic>> activities = [];
  final Set<int> selectedIds = {};
  DateTime? startDate;
  DateTime? endDate;
  List<String> allTypes = [];
  final Set<String> selectedTypes = {};
  bool isLoading = false;
  String? error;

  /// Fetch activities from the backend, optionally with date/type filters.
  /// Pass [projectName] so the backend can mark activities already in the project.
  Future<void> load({String? projectName}) async {
    isLoading = true;
    error = null;
    notifyListeners();

    try {
      final params = <String, String>{};
      if (startDate != null) {
        params['start_date'] =
            '${startDate!.year.toString().padLeft(4, '0')}-'
            '${startDate!.month.toString().padLeft(2, '0')}-'
            '${startDate!.day.toString().padLeft(2, '0')}';
      }
      if (endDate != null) {
        params['end_date'] =
            '${endDate!.year.toString().padLeft(4, '0')}-'
            '${endDate!.month.toString().padLeft(2, '0')}-'
            '${endDate!.day.toString().padLeft(2, '0')}';
      }
      if (selectedTypes.isNotEmpty) {
        params['types'] = selectedTypes.join(',');
      }
      if (projectName != null) {
        params['project'] = projectName;
      }
      params['per_page'] = '100';

      final query = params.entries
          .map((e) =>
              '${Uri.encodeQueryComponent(e.key)}=${Uri.encodeQueryComponent(e.value)}')
          .join('&');

      final raw = await api.get('/api/strava/activities?$query') as List<dynamic>;
      final fetched = raw.cast<Map<String, dynamic>>();

      // Pre-select activities already in project
      final inProject = fetched
          .where((a) => a['in_project'] == true)
          .map((a) => a['id'] as int)
          .toSet();

      activities = fetched;
      selectedIds.clear();
      selectedIds.addAll(inProject);

      // Collect distinct types
      final types = <String>{};
      for (final a in fetched) {
        final t = a['type'] as String?;
        if (t != null && t.isNotEmpty) types.add(t);
      }
      allTypes = types.toList()..sort();
    } on Exception catch (e) {
      error = e.toString().replaceFirst('Exception: ', '');
    } finally {
      isLoading = false;
      notifyListeners();
    }
  }

  void toggleSelect(int id) {
    if (selectedIds.contains(id)) {
      selectedIds.remove(id);
    } else {
      selectedIds.add(id);
    }
    notifyListeners();
  }

  void selectAll() {
    selectedIds.addAll(activities.map((a) => a['id'] as int));
    notifyListeners();
  }

  void clearSelection() {
    selectedIds.clear();
    notifyListeners();
  }

  void setDateRange(DateTime? start, DateTime? end) {
    startDate = start;
    endDate = end;
    notifyListeners();
  }

  void toggleType(String type) {
    if (selectedTypes.contains(type)) {
      selectedTypes.remove(type);
    } else {
      selectedTypes.add(type);
    }
    notifyListeners();
  }

  /// POST selected activities to the project. Returns count added.
  Future<int> addSelected(String projectName) async {
    final toAdd = activities
        .where((a) => selectedIds.contains(a['id'] as int))
        .toList();
    if (toAdd.isEmpty) return 0;

    isLoading = true;
    error = null;
    notifyListeners();

    try {
      final result = await api.post(
        '/api/projects/${Uri.encodeComponent(projectName)}/activities',
        {'activities': toAdd},
      ) as Map<String, dynamic>;
      return (result['added'] as int?) ?? 0;
    } on Exception catch (e) {
      error = e.toString().replaceFirst('Exception: ', '');
      return 0;
    } finally {
      isLoading = false;
      notifyListeners();
    }
  }
}
