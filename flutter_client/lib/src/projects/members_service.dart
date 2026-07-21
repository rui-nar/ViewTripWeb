/// Travel-companion service (issue #106) — project members and invite links.
///
/// Wraps the member-management endpoints under /api/projects/{name}/members
/// and the invite preview/accept endpoints under /api/invites/{token}.
/// [ApiException]s are propagated unchanged so callers can branch on the
/// status code (409 = E2EE-blocked invite / caller owns the trip,
/// 404 = unknown or revoked invite).
library;

import '../api/client.dart';
import '../core/project_ref.dart';

/// One row of GET /api/projects/{name}/members.
class ProjectMember {
  final int userId;
  final String displayName;
  final String avatarUrl;
  final String role; // "owner" | "editor"

  const ProjectMember({
    required this.userId,
    required this.displayName,
    required this.avatarUrl,
    required this.role,
  });

  bool get isOwner => role == 'owner';

  factory ProjectMember.fromJson(Map<String, dynamic> json) => ProjectMember(
        userId: (json['user_id'] as num?)?.toInt() ?? 0,
        displayName: json['display_name'] as String? ?? '',
        avatarUrl: json['avatar_url'] as String? ?? '',
        role: json['role'] as String? ?? 'editor',
      );
}

/// GET /api/invites/{token} — what the join screen shows before accepting.
class InvitePreview {
  final String projectName;
  final String ownerName;

  const InvitePreview({required this.projectName, required this.ownerName});

  factory InvitePreview.fromJson(Map<String, dynamic> json) => InvitePreview(
        projectName: json['project_name'] as String? ?? '',
        ownerName: json['owner_name'] as String? ?? '',
      );
}

class MembersService {
  final ApiClient _api;

  /// Uses the app-wide [api] singleton unless a client is injected (tests).
  MembersService([ApiClient? apiClient]) : _api = apiClient ?? api;

  /// GET /api/projects/{name}/members — owner first (server ordering).
  Future<List<ProjectMember>> listMembers(ProjectRef ref) async {
    final data = await _api.get(ref.path('/members')) as Map<String, dynamic>;
    final raw = data['members'];
    return [
      if (raw is List)
        for (final m in raw) ProjectMember.fromJson(m as Map<String, dynamic>),
    ];
  }

  /// POST /api/projects/{name}/members/invite — owner-only. Idempotent: the
  /// server returns the existing token when one exists. Throws
  /// [ApiException] 409 when the owner's account has E2EE enabled.
  Future<String> createInvite(ProjectRef ref) async {
    final data =
        await _api.post(ref.path('/members/invite'), {}) as Map<String, dynamic>;
    return data['token'] as String? ?? '';
  }

  /// DELETE /api/projects/{name}/members/invite — owner-only revoke.
  Future<void> revokeInvite(ProjectRef ref) async {
    await _api.delete(ref.path('/members/invite'));
  }

  /// DELETE /api/projects/{name}/members/{userId} — owner removes anyone;
  /// an editor may delete only their own user id (leave).
  Future<void> removeMember(ProjectRef ref, int userId) async {
    await _api.delete(ref.path('/members/$userId'));
  }

  /// GET /api/invites/{token} — throws [ApiException] 404 when the token is
  /// unknown or revoked.
  Future<InvitePreview> previewInvite(String token) async {
    final data = await _api.get('/api/invites/${Uri.encodeComponent(token)}')
        as Map<String, dynamic>;
    return InvitePreview.fromJson(data);
  }

  /// POST /api/invites/{token}/accept — joins as editor (idempotent for
  /// existing members). Returns the joined project's [ProjectRef]. Throws
  /// [ApiException] 409 when the caller owns the trip.
  Future<ProjectRef> acceptInvite(String token) async {
    final data =
        await _api.post('/api/invites/${Uri.encodeComponent(token)}/accept', {})
            as Map<String, dynamic>;
    return ProjectRef(
      name: data['name'] as String? ?? '',
      ownerId: (data['owner_id'] as num?)?.toInt(),
      role: 'editor',
    );
  }
}
