/// Immutable value object representing the current filter selection for a project.
library;

class ProjectFilters {
  final Set<String> tags;
  final Set<String> sleeping;
  final Set<String> activityTypes;
  final Set<String> transport;

  /// Where an activity came from: `'strava'` or `'gpx'`.
  ///
  /// The app has recorded this since GPX import shipped and drew a badge
  /// for it, but offered no way to ask the question — provenance you
  /// cannot query is provenance the app only pretends to keep.
  final Set<String> sources;

  const ProjectFilters({
    this.tags = const {},
    this.sleeping = const {},
    this.activityTypes = const {},
    this.transport = const {},
    this.sources = const {},
  });

  static const empty = ProjectFilters();

  bool get hasActive =>
      tags.isNotEmpty || sleeping.isNotEmpty ||
      activityTypes.isNotEmpty || transport.isNotEmpty ||
      sources.isNotEmpty;

  int get activeCount =>
      tags.length + sleeping.length +
      activityTypes.length + transport.length + sources.length;

  ProjectFilters copyWith({
    Set<String>? tags,
    Set<String>? sleeping,
    Set<String>? activityTypes,
    Set<String>? transport,
    Set<String>? sources,
  }) =>
      ProjectFilters(
        tags: tags != null ? Set.unmodifiable(tags) : this.tags,
        sleeping: sleeping != null ? Set.unmodifiable(sleeping) : this.sleeping,
        activityTypes: activityTypes != null
            ? Set.unmodifiable(activityTypes)
            : this.activityTypes,
        transport:
            transport != null ? Set.unmodifiable(transport) : this.transport,
        sources: sources != null ? Set.unmodifiable(sources) : this.sources,
      );
}
