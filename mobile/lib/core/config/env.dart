import 'package:flutter/foundation.dart';

/// Runtime configuration.
///
/// Override the API base with:
///   flutter run --dart-define=API_BASE_URL=http://192.168.1.10:8000
abstract final class Env {
  static const _override = String.fromEnvironment('API_BASE_URL');

  /// Backend origin (no trailing slash). The Android emulator reaches the
  /// host machine through 10.0.2.2; iOS simulator and web use localhost.
  static String get apiOrigin {
    if (_override.isNotEmpty) return _override;
    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
      return 'http://10.0.2.2:8000';
    }
    return 'http://127.0.0.1:8000';
  }

  static String get apiBaseUrl => '$apiOrigin/api/v1';
}
