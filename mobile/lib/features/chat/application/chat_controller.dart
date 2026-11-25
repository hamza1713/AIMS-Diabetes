import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../../core/network/sse_client.dart';
import '../../../core/utils/json.dart';
import '../data/chat_models.dart';

/// Holds the conversation and consumes `/chat/stream` SSE events.
class ChatController extends Notifier<List<ChatMessage>> {
  CancelToken? _cancel;

  @override
  List<ChatMessage> build() {
    ref.onDispose(() => _cancel?.cancel());
    _loadHistory();
    return const [];
  }

  Dio get _dio => ref.read(dioProvider);
  bool get isStreaming => state.isNotEmpty && state.last.streaming;

  Future<void> _loadHistory() async {
    try {
      final res = await _dio.get<dynamic>('/chat/history',
          queryParameters: {'limit': 30});
      final items = jList(res.data, ['items', 'messages']);
      if (state.isNotEmpty) return; // user already started typing
      state = [
        for (final m in items)
          ChatMessage(
            role: jStr(m, ['role']) == 'user' ? ChatRole.user : ChatRole.assistant,
            content: jStr(m, ['content']) ?? '',
          ),
      ];
    } catch (_) {
      // History is optional; start with an empty chat.
    }
  }

  Future<void> send(String text) async {
    final query = text.trim();
    if (query.isEmpty || isStreaming) return;

    state = [
      ...state,
      ChatMessage(role: ChatRole.user, content: query),
      ChatMessage(role: ChatRole.assistant, content: '', streaming: true),
    ];
    _cancel = CancelToken();

    final buffer = StringBuffer();
    try {
      await for (final e in postSse(_dio, '/chat/stream',
          body: {'query': query}, cancelToken: _cancel)) {
        switch (e.type) {
          case 'status':
            _updateLast((m) => m.copyWith(status: jStr(e.data, ['message'])));
          case 'sources':
            _updateLast((m) => m.copyWith(
                sources: jList(e.data, ['sources']).map(ChatSource.fromJson).toList()));
          case 'token':
            buffer.write(jStr(e.data, ['content']) ?? '');
            _updateLast((m) => m.copyWith(content: buffer.toString()));
          case 'error':
            buffer.write(jStr(e.data, ['content']) ?? 'Something went wrong.');
            _updateLast((m) => m.copyWith(
                content: buffer.toString(), isError: true, streaming: false));
          case 'done':
            _updateLast((m) => m.copyWith(streaming: false));
        }
      }
    } catch (e) {
      if (!(e is DioException && CancelToken.isCancel(e))) {
        _updateLast((m) => m.copyWith(
              content: buffer.isEmpty
                  ? ApiException.from(e).message
                  : buffer.toString(),
              isError: buffer.isEmpty,
            ));
      }
    } finally {
      _updateLast((m) => m.copyWith(streaming: false));
      _cancel = null;
    }
  }

  void stop() => _cancel?.cancel();

  Future<void> clear() async {
    stop();
    state = const [];
    try {
      await _dio.delete<dynamic>('/chat/history');
    } catch (_) {}
  }

  void _updateLast(ChatMessage Function(ChatMessage) f) {
    if (state.isEmpty) return;
    state = [...state.sublist(0, state.length - 1), f(state.last)];
  }
}

final chatControllerProvider =
    NotifierProvider<ChatController, List<ChatMessage>>(ChatController.new);
