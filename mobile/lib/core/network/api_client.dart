import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config/env.dart';
import 'token_storage.dart';

/// Error surfaced to the UI with a human-readable message.
class ApiException implements Exception {
  ApiException(this.message, {this.statusCode});
  final String message;
  final int? statusCode;

  bool get isUnauthorized => statusCode == 401;
  bool get isOffline => statusCode == null;

  static ApiException from(Object error) {
    if (error is ApiException) return error;
    if (error is DioException) {
      final res = error.response;
      if (res == null) {
        return ApiException('Can\'t reach the server. Check your connection.');
      }
      final data = res.data;
      final detail = data is Map ? data['detail'] : null;
      return ApiException(
        detail is String ? detail : 'Something went wrong (${res.statusCode}).',
        statusCode: res.statusCode,
      );
    }
    return ApiException(error.toString());
  }

  @override
  String toString() => message;
}

/// Adds the bearer token and, on 401, tries one refresh before giving up.
class AuthInterceptor extends QueuedInterceptor {
  AuthInterceptor(this._tokens, this._dio, this._onSessionExpired);

  final TokenStorage _tokens;
  final Dio _dio;
  final void Function() _onSessionExpired;

  @override
  Future<void> onRequest(
      RequestOptions options, RequestInterceptorHandler handler) async {
    final token = await _tokens.readAccess();
    if (token != null) options.headers['Authorization'] = 'Bearer $token';
    handler.next(options);
  }

  @override
  Future<void> onError(
      DioException err, ErrorInterceptorHandler handler) async {
    final isAuthCall = err.requestOptions.path.startsWith('/auth/');
    if (err.response?.statusCode != 401 || isAuthCall) {
      return handler.next(err);
    }
    final refresh = await _tokens.readRefresh();
    if (refresh == null) {
      _onSessionExpired();
      return handler.next(err);
    }
    try {
      final res = await Dio(BaseOptions(baseUrl: _dio.options.baseUrl))
          .post('/auth/refresh', data: {'refresh_token': refresh});
      await _tokens.save(
        access: res.data['access_token'] as String,
        refresh: res.data['refresh_token'] as String?,
      );
      final retry = await _dio.fetch(err.requestOptions
        ..headers['Authorization'] = 'Bearer ${res.data['access_token']}');
      handler.resolve(retry);
    } catch (_) {
      await _tokens.clear();
      _onSessionExpired();
      handler.next(err);
    }
  }
}

/// Bumped whenever the session expires so the auth controller can react.
class SessionExpired extends Notifier<int> {
  @override
  int build() => 0;
  void bump() => state++;
}

final sessionExpiredProvider =
    NotifierProvider<SessionExpired, int>(SessionExpired.new);

final dioProvider = Provider<Dio>((ref) {
  final dio = Dio(BaseOptions(
    baseUrl: Env.apiBaseUrl,
    connectTimeout: const Duration(seconds: 10),
    receiveTimeout: const Duration(seconds: 60),
    contentType: Headers.jsonContentType,
  ));
  dio.interceptors.add(AuthInterceptor(
    ref.read(tokenStorageProvider),
    dio,
    () => ref.read(sessionExpiredProvider.notifier).bump(),
  ));
  return dio;
});

/// Thin wrapper so repositories get [ApiException]s instead of Dio errors.
class ApiClient {
  ApiClient(this.dio);
  final Dio dio;

  /// Every GET carries `tz_offset` (minutes east of UTC) so the backend's
  /// "today" / `?date=` filters match the phone's local day.
  Future<T> get<T>(String path, {Map<String, dynamic>? query}) => _guard(() =>
      dio.get<T>(path, queryParameters: {
        'tz_offset': DateTime.now().timeZoneOffset.inMinutes,
        ...?query,
      }));

  Future<T> post<T>(String path, {Object? data}) =>
      _guard(() => dio.post<T>(path, data: data));

  Future<T> put<T>(String path, {Object? data}) =>
      _guard(() => dio.put<T>(path, data: data));

  Future<T> delete<T>(String path) => _guard(() => dio.delete<T>(path));

  Future<T> _guard<T>(Future<Response<T>> Function() call) async {
    try {
      return (await call()).data as T;
    } catch (e) {
      throw ApiException.from(e);
    }
  }
}

final apiClientProvider =
    Provider<ApiClient>((ref) => ApiClient(ref.watch(dioProvider)));
