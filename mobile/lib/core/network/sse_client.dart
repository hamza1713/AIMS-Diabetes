import 'dart:convert';

import 'package:dio/dio.dart';

/// One `data: {...}` event from `/chat/stream`.
///
/// Backend event types (see backend/app/agents/orchestrator.py):
/// `status`, `sources`, `bio_metadata`, `token`, `error`, `done`.
class SseEvent {
  SseEvent(this.type, this.data);
  final String type;
  final Map<String, dynamic> data;
}

/// Opens a POST SSE stream with [dio] and yields parsed events.
Stream<SseEvent> postSse(
  Dio dio,
  String path, {
  required Object body,
  CancelToken? cancelToken,
}) async* {
  final res = await dio.post<ResponseBody>(
    path,
    data: body,
    cancelToken: cancelToken,
    options: Options(
      responseType: ResponseType.stream,
      headers: {'Accept': 'text/event-stream'},
      receiveTimeout: const Duration(minutes: 5),
    ),
  );

  final lines = res.data!.stream
      .cast<List<int>>()
      .transform(utf8.decoder)
      .transform(const LineSplitter());

  final buffer = StringBuffer();
  await for (final line in lines) {
    if (line.startsWith('data:')) {
      buffer.write(line.substring(5).trimLeft());
    } else if (line.isEmpty && buffer.isNotEmpty) {
      final event = _parse(buffer.toString());
      buffer.clear();
      if (event != null) yield event;
    }
  }
  if (buffer.isNotEmpty) {
    final event = _parse(buffer.toString());
    if (event != null) yield event;
  }
}

SseEvent? _parse(String raw) {
  try {
    final json = jsonDecode(raw) as Map<String, dynamic>;
    return SseEvent(json['type'] as String? ?? 'unknown', json);
  } catch (_) {
    return null;
  }
}
