/// Projects service — wraps /api/projects/* endpoints.
library;

import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import '../api/client.dart';

class ProjectsService {
  Future<List<Map<String, dynamic>>> list() async {
    final data = await api.get('/api/projects/') as List;
    return data.cast<Map<String, dynamic>>();
  }

  Future<Map<String, dynamic>> create(String name) async {
    return await api.post('/api/projects/', {'name': name})
        as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> get(String name) async {
    return await api.get('/api/projects/$name') as Map<String, dynamic>;
  }

  Future<void> delete(String name) async {
    await api.delete('/api/projects/$name');
  }

  Future<Map<String, dynamic>> importFile(File file) async {
    final request = http.MultipartRequest(
      'POST',
      Uri.parse('${api.baseUrl}/api/projects/import'),
    )
      ..headers['Authorization'] = 'Bearer ${api.tokenForUpload}'
      ..files.add(await http.MultipartFile.fromPath('file', file.path));
    final streamed = await request.send();
    final res = await http.Response.fromStream(streamed);
    if (res.statusCode != 201) throw ApiException(res.statusCode, res.body);
    if (res.body.isEmpty) return {};
    final decoded = jsonDecode(res.body);
    return decoded as Map<String, dynamic>;
  }

  /// Convenience wrapper used by [ProjectsNotifier] on native platforms.
  Future<Map<String, dynamic>> importFileByPath(String path) =>
      importFile(File(path));
}
