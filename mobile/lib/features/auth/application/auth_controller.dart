import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../data/auth_repository.dart';

enum AuthStatus { unknown, signedIn, signedOut }

/// App-wide auth state; the router redirects on changes.
class AuthController extends Notifier<AuthStatus> {
  @override
  AuthStatus build() {
    ref.listen(sessionExpiredProvider, (_, _) => state = AuthStatus.signedOut);
    _restore();
    return AuthStatus.unknown;
  }

  AuthRepository get _repo => ref.read(authRepositoryProvider);

  Future<void> _restore() async {
    state = await _repo.hasSession() ? AuthStatus.signedIn : AuthStatus.signedOut;
  }

  Future<void> login(String email, String password) async {
    await _repo.login(email: email, password: password);
    state = AuthStatus.signedIn;
  }

  Future<void> register(String name, String email, String password) async {
    await _repo.register(name: name, email: email, password: password);
    state = AuthStatus.signedIn;
  }

  Future<void> logout() async {
    await _repo.logout();
    state = AuthStatus.signedOut;
  }
}

final authControllerProvider =
    NotifierProvider<AuthController, AuthStatus>(AuthController.new);
