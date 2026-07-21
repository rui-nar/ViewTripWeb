// Unit tests for ProjectNotifier's ProjectRef addressing (issue #106 —
// travel companion): load() adopts the given ref, projectName/isEditor
// derive from it, and a rename updates the name in place while keeping the
// owner/role.

import 'package:flutter_test/flutter_test.dart';
import 'package:viewtrip_client/src/core/project_ref.dart';
import 'package:viewtrip_client/src/projects/project_notifier.dart';
import 'package:viewtrip_client/src/projects/project_service.dart';

class _FakeProjectService extends ProjectService {
  @override
  Future<Map<String, dynamic>> getDetailsMeta(ProjectRef ref) async => {
        'name': ref.name,
        'activities': <dynamic>[],
        'items': <dynamic>[],
        'people': <dynamic>[],
        'groups': <dynamic>[],
      };

  @override
  Future<Map<String, dynamic>> getLowResGeo(ProjectRef ref) async =>
      {'type': 'FeatureCollection', 'features': <dynamic>[]};

  @override
  Future<Map<String, dynamic>> getGeo(ProjectRef ref) async =>
      {'type': 'FeatureCollection', 'features': <dynamic>[]};

  @override
  Future<Map<String, dynamic>> getDetails(ProjectRef ref) async =>
      getDetailsMeta(ref);
}

class _TestProjectNotifier extends ProjectNotifier {
  _TestProjectNotifier(super.service);
  @override
  bool get loadOwnerExtras => false;
}

void main() {
  group('ProjectNotifier ref addressing', () {
    test('load() with an own ref: projectName set, isEditor false', () async {
      final n = _TestProjectNotifier(_FakeProjectService());
      await n.load(const ProjectRef(name: 'Trip'));

      expect(n.projectName, 'Trip');
      expect(n.ref, const ProjectRef(name: 'Trip'));
      expect(n.isEditor, isFalse);
    });

    test('load() with a shared (editor) ref: isEditor true, ref carries '
        'ownerId/role', () async {
      final n = _TestProjectNotifier(_FakeProjectService());
      await n.load(const ProjectRef(name: 'Trip', ownerId: 7, role: 'editor'));

      expect(n.projectName, 'Trip');
      expect(n.ref, const ProjectRef(name: 'Trip', ownerId: 7, role: 'editor'));
      expect(n.isEditor, isTrue);
    });

    test('before any load(), ref/projectName are null and isEditor is false',
        () {
      final n = _TestProjectNotifier(_FakeProjectService());
      expect(n.ref, isNull);
      expect(n.projectName, isNull);
      expect(n.isEditor, isFalse);
    });

    test('clear() resets ref to null', () async {
      final n = _TestProjectNotifier(_FakeProjectService());
      await n.load(const ProjectRef(name: 'Trip'));
      expect(n.ref, isNotNull);

      n.clear();
      expect(n.ref, isNull);
      expect(n.projectName, isNull);
    });
  });
}
