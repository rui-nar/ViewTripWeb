/// Immutable value object representing the current filter selection for a project.
library;

class ProjectFilters {
  final Set<String> tags;
  final Set<String> sleeping;
  final Set<String> activityTypes;
  final Set<String> transport;

  const ProjectFilters({
    this.tags = const {},
    this.sleeping = const {},
    this.activityTypes = const {},
    this.transport = const {},
  });

  static const empty = ProjectFilters();

  bool get hasActive =>
      tags.isNotEmpty || sleeping.isNotEmpty ||
      activityTypes.isNotEmpty || transport.isNotEmpty;

  int get activeCount =>
      tags.length + sleeping.length +
      activityTypes.length + transport.length;

  ProjectFilters copyWith({
    Set<String>? tags,
    Set<String>? sleeping,
    Set<String>? activityTypes,
    Set<String>? transport,
  }) =>
      ProjectFilters(
        tags: tags != null ? Set.unmodifiable(tags) : this.tags,
        sleeping: sleeping != null ? Set.unmodifiable(sleeping) : this.sleeping,
        activityTypes: activityTypes != null
            ? Set.unmodifiable(activityTypes)
            : this.activityTypes,
        transport:
            transport != null ? Set.unmodifiable(transport) : this.transport,
      );
}
