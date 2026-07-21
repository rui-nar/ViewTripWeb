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
  final String role; // "owner" | "co-owner" | "editor" | "viewer"

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

  /// The role this invite grants on accept (issue #109).
  final String role;

  const InvitePreview({
    required this.projectName,
    required this.ownerName,
    required this.role,
  });

  factory InvitePreview.fromJson(Map<String, dynamic> json) => InvitePreview(
        projectName: json['project_name'] as String? ?? '',
        ownerName: json['owner_name'] as String? ?? '',
        role: json['role'] as String? ?? 'editor',
      );
}

/// POST .../members/invite response — the token plus the role it grants
/// (idempotent creation may return an existing invite's role, which can
/// differ from the one just requested).
typedef CreatedInvite = ({String token, String role});

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

  /// POST /api/projects/{name}/members/invite — co-owner+. Idempotent: the
  /// server returns the existing invite (role unchanged) when one exists, so
  /// [role] may be silently ignored — read [CreatedInvite.role] for what was
  /// actually granted. Only the strict owner may request "co-owner"; a
  /// co-owner requesting it gets a 403. Throws [ApiException] 409 when the
  /// owner's account has E2EE enabled.
  Future<CreatedInvite> createInvite(ProjectRef ref, {String role = 'editor'}) async {
    final data = await _api.post(ref.path('/members/invite'), {'role': role})
        as Map<String, dynamic>;
    return (
      token: data['token'] as String? ?? '',
      role: data['role'] as String? ?? role,
    );
  }

  /// DELETE /api/projects/{name}/members/invite — co-owner+ revoke.
  Future<void> revokeInvite(ProjectRef ref) async {
    await _api.delete(ref.path('/members/invite'));
  }

  /// DELETE /api/projects/{name}/members/{userId} — co-owner+ removes an
  /// editor/viewer (removing a co-owner is strict-owner-only); any member
  /// may delete only their own user id (leave), at any role.
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

  /// POST /api/invites/{token}/accept — joins with the invite's role
  /// (idempotent for existing members — role is not changed by re-accepting).
  /// [role] should be the role shown by [previewInvite] (the accept response
  /// itself only carries name/owner_id) so the returned [ProjectRef] reflects
  /// what the caller actually got. Throws [ApiException] 409 when the caller
  /// owns the trip.
  Future<ProjectRef> acceptInvite(String token, {String role = 'editor'}) async {
    final data =
        await _api.post('/api/invites/${Uri.encodeComponent(token)}/accept', {})
            as Map<String, dynamic>;
    return ProjectRef(
      name: data['name'] as String? ?? '',
      ownerId: (data['owner_id'] as num?)?.toInt(),
      role: role,
    );
  }
}
