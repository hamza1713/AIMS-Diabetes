import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../../core/utils/json.dart';

class UserProfile {
  UserProfile({
    required this.name,
    required this.email,
    this.age,
    this.gender,
    this.heightCm,
    this.weightKg,
    this.diabetesType,
    this.photoUrl,
    double? bmi,
  }) : _bmi = bmi; // ignore: prefer_initializing_formals

  final String name;
  final String email;
  final int? age;
  final String? gender;
  final double? heightCm;
  final double? weightKg;
  final String? diabetesType;
  final String? photoUrl;
  final double? _bmi;

  double? get bmi {
    if (_bmi != null) return _bmi;
    if (heightCm == null || weightKg == null || heightCm! <= 0) return null;
    final m = heightCm! / 100;
    return weightKg! / (m * m);
  }

  String get firstName => name.trim().split(RegExp(r'\s+')).first;

  String get initials {
    final parts = name.trim().split(RegExp(r'\s+')).where((p) => p.isNotEmpty);
    return parts.take(2).map((p) => p[0].toUpperCase()).join();
  }

  factory UserProfile.fromJson(Json j) => UserProfile(
        name: jStr(j, ['name', 'full_name']) ?? '',
        email: jStr(j, ['email']) ?? '',
        age: jInt(j, ['age']),
        gender: jStr(j, ['gender', 'sex']),
        heightCm: jNum(j, ['height_cm', 'height']),
        weightKg: jNum(j, ['weight_kg', 'weight']),
        diabetesType: jStr(j, ['diabetes_type']),
        photoUrl: jStr(j, ['photo_url', 'avatar_url']),
        bmi: jNum(j, ['bmi']),
      );

  Json toJson() => {
        'name': name,
        'age': ?age,
        'gender': ?gender,
        'height_cm': ?heightCm,
        'weight_kg': ?weightKg,
        'diabetes_type': ?diabetesType,
      };
}

class Preferences {
  Preferences({
    this.glucoseUnit = 'mg/dL',
    this.language = 'en',
    this.medicationReminders = true,
    this.glucoseAlerts = true,
    this.dailyTips = true,
  });

  final String glucoseUnit;

  /// Language code (`en`, `ur`).
  final String language;
  final bool medicationReminders;
  final bool glucoseAlerts;
  final bool dailyTips;

  Preferences copyWith({
    String? glucoseUnit,
    String? language,
    bool? medicationReminders,
    bool? glucoseAlerts,
    bool? dailyTips,
  }) =>
      Preferences(
        glucoseUnit: glucoseUnit ?? this.glucoseUnit,
        language: language ?? this.language,
        medicationReminders: medicationReminders ?? this.medicationReminders,
        glucoseAlerts: glucoseAlerts ?? this.glucoseAlerts,
        dailyTips: dailyTips ?? this.dailyTips,
      );

  factory Preferences.fromJson(Json j) => Preferences(
        glucoseUnit: jStr(j, ['glucose_unit', 'units']) ?? 'mg/dL',
        language: jStr(j, ['language']) ?? 'en',
        medicationReminders:
            jBool(j, ['medication_reminders', 'notify_medication'], fallback: true),
        glucoseAlerts:
            jBool(j, ['glucose_alerts', 'notify_glucose'], fallback: true),
        dailyTips: jBool(j, ['daily_tips', 'notify_tips'], fallback: true),
      );

  Json toJson() => {
        'glucose_unit': glucoseUnit,
        'language': language,
        'medication_reminders': medicationReminders,
        'glucose_alerts': glucoseAlerts,
        'daily_tips': dailyTips,
      };
}

class ProfileRepository {
  ProfileRepository(this._api);
  final ApiClient _api;

  Future<UserProfile> me() async =>
      UserProfile.fromJson(await _api.get<Json>('/users/me'));

  Future<void> update(UserProfile p) =>
      _api.put<dynamic>('/users/me', data: p.toJson());

  Future<Preferences> preferences() async =>
      Preferences.fromJson(await _api.get<Json>('/users/me/preferences'));

  Future<void> savePreferences(Preferences p) =>
      _api.put<dynamic>('/users/me/preferences', data: p.toJson());

  Future<void> changePassword(String current, String next) =>
      _api.post<dynamic>('/auth/change-password', data: {
        'current_password': current,
        'new_password': next,
      });
}

final profileRepositoryProvider =
    Provider((ref) => ProfileRepository(ref.watch(apiClientProvider)));

final profileProvider =
    FutureProvider((ref) => ref.watch(profileRepositoryProvider).me());

final preferencesProvider = FutureProvider.autoDispose(
    (ref) => ref.watch(profileRepositoryProvider).preferences());
