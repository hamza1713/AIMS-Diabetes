import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../../core/network/token_storage.dart';

/// Talks to the backend `/auth/*` endpoints and stores tokens.
class AuthRepository {
  AuthRepository(this._api, this._tokens);
  final ApiClient _api;
  final TokenStorage _tokens;

  Future<bool> hasSession() async => (await _tokens.readAccess()) != null;

  Future<void> login({required String email, required String password}) async {
    final res = await _api.post<Map<String, dynamic>>(
      '/auth/login',
      data: {'email': email, 'password': password},
    );
    await _saveTokens(res);
  }

  Future<void> register({
    required String name,
    required String email,
    required String password,
  }) async {
    final res = await _api.post<Map<String, dynamic>>(
      '/auth/register',
      data: {'name': name, 'email': email, 'password': password},
    );
    await _saveTokens(res);
  }

  Future<void> forgotPassword(String email) =>
      _api.post<dynamic>('/auth/forgot-password', data: {'email': email});

  Future<void> logout() => _tokens.clear();

  Future<void> _saveTokens(Map<String, dynamic> res) => _tokens.save(
        access: res['access_token'] as String,
        refresh: res['refresh_token'] as String?,
      );
}

final authRepositoryProvider = Provider<AuthRepository>(
  (ref) => AuthRepository(
    ref.watch(apiClientProvider),
    ref.watch(tokenStorageProvider),
  ),
);
