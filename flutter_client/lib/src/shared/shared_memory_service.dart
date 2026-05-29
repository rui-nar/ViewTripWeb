/// Comment and like operations for shared (unauthenticated) project views.
///
/// Read endpoints use plain GET (no auth needed — share token is in the URL).
/// Write endpoints forward the user's JWT via the global [api] client.
library;

import '../api/client.dart';

class SharedMemoryService {
  /// GET /api/share/{token}/memories/{mid}/comments
  Future<List<Map<String, dynamic>>> fetchComments(
    String shareToken,
    int memoryId,
  ) async {
    final data = await api.get(
      '/api/share/$shareToken/memories/$memoryId/comments',
    );
    return (data as List).cast<Map<String, dynamic>>();
  }

  /// POST /api/share/{token}/memories/{mid}/comments
  /// Requires the user to be authenticated (JWT via [api]).
  Future<void> addComment(
    String shareToken,
    int memoryId,
    String text, {
    int? parentCommentId,
  }) async {
    await api.post(
      '/api/share/$shareToken/memories/$memoryId/comments',
      {
        'text': text,
        if (parentCommentId != null) 'parent_comment_id': parentCommentId,
      },
    );
  }

  /// DELETE /api/share/{token}/memories/{mid}/comments/{cid}
  Future<void> deleteComment(
    String shareToken,
    int memoryId,
    int commentId,
  ) async {
    await api.delete(
      '/api/share/$shareToken/memories/$memoryId/comments/$commentId',
    );
  }

  /// GET /api/share/{token}/memories/{mid}/likes
  Future<Map<String, dynamic>> fetchLikes(
    String shareToken,
    int memoryId,
  ) async {
    final data = await api.get(
      '/api/share/$shareToken/memories/$memoryId/likes',
    );
    return data as Map<String, dynamic>;
  }

  /// POST /api/share/{token}/memories/{mid}/like
  Future<void> likeMemory(String shareToken, int memoryId) async {
    await api.post(
      '/api/share/$shareToken/memories/$memoryId/like',
      {},
    );
  }

  /// DELETE /api/share/{token}/memories/{mid}/like
  Future<void> unlikeMemory(String shareToken, int memoryId) async {
    await api.delete(
      '/api/share/$shareToken/memories/$memoryId/like',
    );
  }
}

final sharedMemoryService = SharedMemoryService();
