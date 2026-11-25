import '../../../core/config/env.dart';
import '../../../core/utils/json.dart';

/// Evidence page returned in the `sources` SSE event.
class ChatSource {
  ChatSource({
    required this.title,
    this.authors,
    this.journal,
    this.year,
    this.page,
    this.imageUrl,
  });

  final String title;
  final String? authors;
  final String? journal;
  final int? year;
  final int? page;
  final String? imageUrl;

  String get citation => [
        if (journal != null && journal != 'Unknown Journal') journal,
        ?year?.toString(),
        if (page != null) 'p. $page',
      ].join(' · ');

  /// Backend returns relative `/rendered_pages/...` URLs.
  String? get absoluteImageUrl {
    final u = imageUrl;
    if (u == null || u.isEmpty) return null;
    return u.startsWith('http') ? u : '${Env.apiOrigin}$u';
  }

  factory ChatSource.fromJson(Json j) => ChatSource(
        title: jStr(j, ['title']) ?? 'Research paper',
        authors: jStr(j, ['authors']),
        journal: jStr(j, ['journal']),
        year: jInt(j, ['publication_year', 'year']),
        page: jInt(j, ['page_number', 'page']),
        imageUrl: jStr(j, ['image_url']),
      );
}

enum ChatRole { user, assistant }

class ChatMessage {
  ChatMessage({
    required this.role,
    required this.content,
    this.sources = const [],
    this.status,
    this.streaming = false,
    this.isError = false,
  });

  final ChatRole role;
  final String content;
  final List<ChatSource> sources;

  /// Latest `status` event while the answer is being prepared.
  final String? status;
  final bool streaming;
  final bool isError;

  bool get isThinking => streaming && content.isEmpty;

  ChatMessage copyWith({
    String? content,
    List<ChatSource>? sources,
    String? status,
    bool? streaming,
    bool? isError,
  }) =>
      ChatMessage(
        role: role,
        content: content ?? this.content,
        sources: sources ?? this.sources,
        status: status ?? this.status,
        streaming: streaming ?? this.streaming,
        isError: isError ?? this.isError,
      );
}
