/// Identifies a project for API addressing (issue #106 — travel companion).
///
/// A project is looked up server-side by `(caller, name)` unless [ownerId] is
/// given, in which case it resolves to `(ownerId, name)` and the caller must
/// be a member (editor) of that project. [ownerId] is null for the caller's
/// own projects — the common case — so most call sites are unaffected.
library;

class ProjectRef {
  /// The project's name (unique per owner, not globally).
  final String name;

  /// The owning user's id, or null for one of the caller's own projects.
  final int? ownerId;

  /// The caller's role on this project: "owner" or "editor". Meaningless
  /// (defaults to "owner") when [ownerId] is null.
  final String role;

  const ProjectRef({required this.name, this.ownerId, this.role = 'owner'});

  /// True when this is one of the caller's own projects (no `?owner=` needed).
  bool get isOwn => ownerId == null;

  /// True when the caller only has editor (not owner) access.
  bool get isEditor => role == 'editor';

  /// Appends the `owner` query param to [url] when this ref points at a
  /// shared (not own) project — `?owner=<id>` or `&owner=<id>` depending on
  /// whether [url] already carries a query string. No-op for an own project,
  /// so existing call sites are unaffected until a project is actually shared.
  String withOwner(String url) {
    final id = ownerId;
    if (id == null) return url;
    return '$url${url.contains('?') ? '&' : '?'}owner=$id';
  }

  /// Builds `/api/projects/{name}` (URL-encoded) with [suffix] appended
  /// (e.g. `/meta`, `/stats?tags=x`) and the owner query param applied.
  String path([String suffix = '']) =>
      withOwner('/api/projects/${Uri.encodeComponent(name)}$suffix');

  ProjectRef copyWith({String? name, int? ownerId, String? role}) => ProjectRef(
        name: name ?? this.name,
        ownerId: ownerId ?? this.ownerId,
        role: role ?? this.role,
      );

  /// Resolves [role] against the signed-in user's id ([selfId], the string id
  /// exposed by AuthNotifier). URL-derived refs (`?owner=`) don't carry a
  /// role, so a shared project deep link would otherwise default to "owner"
  /// and break owner-only UI gating ([isEditor]). Addressing another user's
  /// project can only ever be editor access (the server 404s otherwise);
  /// [ownerId] absent — or equal to [selfId], as own entries in the projects
  /// list carry their owner_id — means the caller owns the project.
  ProjectRef resolveRoleFor(String? selfId) {
    final id = ownerId;
    final resolved = (id != null && id.toString() != selfId) ? 'editor' : 'owner';
    return resolved == role ? this : copyWith(role: resolved);
  }

  /// Query params for a GoRouter location carrying this ref: `project`
  /// always, `owner` only when this is a shared project.
  Map<String, String> get routeParams => {
        'project': name,
        if (ownerId != null) 'owner': ownerId.toString(),
      };

  Map<String, dynamic> toJson() => {
        'name': name,
        if (ownerId != null) 'ownerId': ownerId,
        'role': role,
      };

  factory ProjectRef.fromJson(Map<String, dynamic> json) => ProjectRef(
        name: json['name'] as String,
        ownerId: json['ownerId'] as int?,
        role: json['role'] as String? ?? 'owner',
      );

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is ProjectRef &&
          other.name == name &&
          other.ownerId == ownerId &&
          other.role == role);

  @override
  int get hashCode => Object.hash(name, ownerId, role);

  @override
  String toString() =>
      'ProjectRef($name${ownerId != null ? ', owner=$ownerId, role=$role' : ''})';
}

/// Reads [ProjectRef] and display fields out of a raw `/api/projects/` list
/// entry (`{name, filename, owner_id, owner_name, role}` — issue #106).
/// Backward compatible with an older server that only sends `name`/`filename`:
/// [ref] then has a null [ProjectRef.ownerId] and role "owner", and
/// [ownerName] is null.
extension ProjectListEntry on Map<String, dynamic> {
  ProjectRef get ref => ProjectRef(
        name: this['name'] as String? ?? '',
        ownerId: this['owner_id'] as int?,
        role: this['role'] as String? ?? 'owner',
      );

  /// The owning user's display name, present only on shared (role: editor)
  /// entries.
  String? get ownerName => this['owner_name'] as String?;

  bool get isSharedWithMe => (this['role'] as String? ?? 'owner') == 'editor';
}
