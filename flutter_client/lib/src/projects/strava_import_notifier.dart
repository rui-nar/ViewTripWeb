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
  bool isLoadingMore = false;
  String? error;

  /// Count of selected activities not yet in the project.
  /// Pre-computed so the bottom bar never iterates the full list on each tap.
  int newCount = 0;

  /// Whether the last result was served from the server-side cache.
  bool lastResultCached = false;

  /// Total matching activities across all pages.
  int totalCount = 0;

  bool _hasMore = false;
  bool get hasMore => _hasMore;

  int _currentPage = 1;
  String? _lastProjectName;

  // ── Load (first page / reset) ───────────────────────────────────────────────

  /// Fetch page 1 from the backend, resetting the list.
  ///
  /// Pass [refresh] = true to bypass the server-side cache.
  Future<void> load({String? projectName, bool refresh = false}) async {
    _currentPage = 1;
    _lastProjectName = projectName;
    isLoading = true;
    error = null;
    notifyListeners();

    try {
      final envelope = await _fetchPage(
        page: 1,
        projectName: projectName,
        refresh: refresh,
      );

      final fetched = _parseActivities(envelope);
      _applyEnvelopeMeta(envelope);

      // Pre-select activities already in project
      final inProject = fetched
          .where((a) => a['in_project'] == true)
          .map((a) => a['id'] as int)
          .toSet();

      activities = fetched;
      selectedIds.clear();
      selectedIds.addAll(inProject);

      _rebuildTypes(activities);
      _recomputeNewCount();
    } on Exception catch (e) {
      error = e.toString().replaceFirst('Exception: ', '');
    } finally {
      isLoading = false;
      notifyListeners();
    }
  }

  // ── Load more (append next page) ────────────────────────────────────────────

  /// Append the next page of results to [activities].
  Future<void> loadMore() async {
    if (!_hasMore || isLoading || isLoadingMore) return;

    isLoadingMore = true;
    notifyListeners();

    try {
      final envelope = await _fetchPage(
        page: _currentPage + 1,
        projectName: _lastProjectName,
        refresh: false,
      );

      final more = _parseActivities(envelope);
      _applyEnvelopeMeta(envelope);
      _currentPage += 1;

      // Mark new activities in-project without clearing existing selection
      for (final a in more) {
        if (a['in_project'] == true) {
          selectedIds.add(a['id'] as int);
        }
      }

      activities = [...activities, ...more];
      _rebuildTypes(activities);
      _recomputeNewCount();
    } on Exception catch (e) {
      error = e.toString().replaceFirst('Exception: ', '');
    } finally {
      isLoadingMore = false;
      notifyListeners();
    }
  }

  // ── Helpers ─────────────────────────────────────────────────────────────────

  Future<Map<String, dynamic>> _fetchPage({
    required int page,
    String? projectName,
    bool refresh = false,
  }) async {
    final params = <String, String>{'page': '$page', 'per_page': '50'};
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
    if (projectName != null) params['project'] = projectName;
    if (refresh) params['refresh'] = 'true';

    final query = params.entries
        .map((e) =>
            '${Uri.encodeQueryComponent(e.key)}=${Uri.encodeQueryComponent(e.value)}')
        .join('&');

    return await api.get('/api/strava/activities?$query') as Map<String, dynamic>;
  }

  List<Map<String, dynamic>> _parseActivities(Map<String, dynamic> envelope) =>
      (envelope['activities'] as List<dynamic>).cast<Map<String, dynamic>>();

  void _applyEnvelopeMeta(Map<String, dynamic> envelope) {
    lastResultCached = envelope['cached'] == true;
    totalCount = (envelope['total'] as int?) ?? 0;
    _hasMore = envelope['has_more'] == true;
  }

  void _recomputeNewCount() {
    newCount = activities.where((a) =>
      selectedIds.contains(a['id'] as int) && a['in_project'] != true
    ).length;
  }

  void _rebuildTypes(List<Map<String, dynamic>> list) {
    final types = <String>{};
    for (final a in list) {
      final t = a['type'] as String?;
      if (t != null && t.isNotEmpty) types.add(t);
    }
    allTypes = types.toList()..sort();
  }

  // ── Selection ───────────────────────────────────────────────────────────────

  void toggleSelect(int id) {
    if (selectedIds.contains(id)) {
      selectedIds.remove(id);
    } else {
      selectedIds.add(id);
    }
    _recomputeNewCount();
    notifyListeners();
  }

  void selectAll() {
    selectedIds.addAll(activities.map((a) => a['id'] as int));
    _recomputeNewCount();
    notifyListeners();
  }

  void clearSelection() {
    selectedIds.clear();
    newCount = 0;
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

  // ── Add to project ──────────────────────────────────────────────────────────

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
