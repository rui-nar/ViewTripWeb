/// Pure post-composition logic for social sharing.
///
/// No Flutter, no platform, no I/O — assembles the final post text and the
/// list of assets to include from the user's selections. Fully unit-testable.
library;

/// The composed result handed to the transport layer.
class ComposedPost {
  /// Final body text, with the link appended (blank-line separated) when
  /// [link] is included.
  final String text;

  /// The deep link, or null when the user disabled it / no token exists.
  final String? link;

  /// Base UUIDs of the memory photos to attach.
  final List<String> photoUuids;

  /// Whether to attach the rendered trip map image.
  final bool includeMap;

  const ComposedPost({
    required this.text,
    required this.link,
    required this.photoUuids,
    required this.includeMap,
  });
}

/// Stateless assembler — pure function wrapped in a class for namespacing.
class SocialPostComposer {
  const SocialPostComposer._();

  static ComposedPost compose({
    required String customText,
    required bool includeLink,
    required String? link,
    required List<String> selectedPhotoUuids,
    required bool includeMap,
  }) {
    final body = customText.trim();
    final useLink = includeLink && link != null && link.isNotEmpty;

    final text = useLink
        ? [body, link].where((s) => s.isNotEmpty).join('\n\n')
        : body;

    return ComposedPost(
      text: text,
      link: useLink ? link : null,
      photoUuids: List.unmodifiable(selectedPhotoUuids),
      includeMap: includeMap,
    );
  }
}
