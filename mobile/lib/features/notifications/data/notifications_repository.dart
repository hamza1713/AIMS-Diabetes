import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../../core/utils/json.dart';

class AppNotification {
  AppNotification({
    required this.id,
    required this.title,
    required this.body,
    required this.kind,
    required this.createdAt,
    required this.read,
  });

  final int id;
  final String title;
  final String body;
  final String kind; // medication | glucose | tip | system
  final DateTime createdAt;
  final bool read;

  factory AppNotification.fromJson(Json j) => AppNotification(
        id: jInt(j, ['id']) ?? 0,
        title: jStr(j, ['title']) ?? '',
        body: jStr(j, ['body', 'message']) ?? '',
        kind: jStr(j, ['kind', 'type', 'category']) ?? 'system',
        createdAt: jDate(j, ['created_at']) ?? DateTime.now(),
        read: jBool(j, ['read', 'is_read']),
      );
}

class NotificationsRepository {
  NotificationsRepository(this._api);
  final ApiClient _api;

  Future<List<AppNotification>> list() async {
    final res = await _api.get<dynamic>('/notifications');
    return jList(res, ['items', 'notifications'])
        .map(AppNotification.fromJson)
        .toList()
      ..sort((a, b) => b.createdAt.compareTo(a.createdAt));
  }

  Future<void> markAllRead() =>
      _api.post<dynamic>('/notifications/mark-all-read');
}

final notificationsRepositoryProvider =
    Provider((ref) => NotificationsRepository(ref.watch(apiClientProvider)));

final notificationsProvider = FutureProvider.autoDispose(
    (ref) => ref.watch(notificationsRepositoryProvider).list());

final unreadCountProvider = Provider.autoDispose<int>((ref) =>
    ref.watch(notificationsProvider).value?.where((n) => !n.read).length ?? 0);
