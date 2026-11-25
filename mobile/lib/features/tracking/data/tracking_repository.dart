import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../../core/utils/json.dart';
import 'tracking_models.dart';

/// All health-log endpoints used by the Track tab and Home.
class TrackingRepository {
  TrackingRepository(this._api);
  final ApiClient _api;

  // ── Glucose ────────────────────────────────────────────────────────────
  Future<List<GlucoseReading>> glucose({int days = 7}) async {
    final res = await _api.get<dynamic>('/health-logs/glucose',
        query: {'days': days});
    return jList(res, ['items', 'readings']).map(GlucoseReading.fromJson).toList()
      ..sort((a, b) => b.recordedAt.compareTo(a.recordedAt));
  }

  Future<GlucoseSummary> glucoseSummary({int days = 7}) async {
    final res = await _api.get<Json>('/health-logs/glucose/summary',
        query: {'days': days});
    return GlucoseSummary.fromJson(res);
  }

  Future<void> addGlucose({
    required double value,
    required GlucoseWhen when,
    required DateTime at,
    String? notes,
  }) =>
      _api.post<dynamic>('/health-logs/glucose', data: {
        'glucose_value': value,
        'when': when.api,
        'recorded_at': at.toUtc().toIso8601String(),
        'notes': ?(notes?.isEmpty ?? true ? null : notes),
      });

  // ── Meals ──────────────────────────────────────────────────────────────
  Future<List<Meal>> meals({DateTime? date, int? days}) async {
    final res = await _api.get<dynamic>('/health-logs/meals', query: {
      'date': ?(date == null ? null : isoDay(date)),
      'days': ?days,
    });
    return jList(res, ['items', 'meals']).map(Meal.fromJson).toList()
      ..sort((a, b) => b.loggedAt.compareTo(a.loggedAt));
  }

  Future<void> addMeal({
    required MealType type,
    required String name,
    required double carbs,
    double? calories,
    double? protein,
    double? fat,
    required DateTime at,
  }) =>
      _api.post<dynamic>('/health-logs/meals', data: {
        'meal_type': type.label,
        'description': name,
        'name': name,
        'carbs_grams': carbs,
        'calories': ?calories,
        'protein_g': ?protein,
        'fat_g': ?fat,
        'logged_at': at.toUtc().toIso8601String(),
      });

  /// Vision AI (Figma 11): photo → food, confidence, nutrition.
  /// Takes bytes (not a path) so it also works on Flutter web.
  Future<Json> analyzeMealPhoto(List<int> bytes, {String filename = 'meal.jpg'}) async {
    final form = FormData.fromMap({
      'image': MultipartFile.fromBytes(bytes, filename: filename),
    });
    return _api.post<Json>('/vision/meal-analysis', data: form);
  }

  // ── Exercise ───────────────────────────────────────────────────────────
  Future<List<Workout>> workouts({int days = 7}) async {
    final res = await _api.get<dynamic>('/health-logs/exercise',
        query: {'days': days});
    return jList(res, ['items', 'workouts']).map(Workout.fromJson).toList()
      ..sort((a, b) => b.loggedAt.compareTo(a.loggedAt));
  }

  Future<void> addWorkout({
    required String activity,
    required double minutes,
    double? calories,
    required Intensity intensity,
    required DateTime at,
  }) =>
      _api.post<dynamic>('/health-logs/exercise', data: {
        'activity': activity,
        'duration_min': minutes.round(),
        'calories': ?calories,
        'intensity': intensity.name,
        'performed_at': at.toUtc().toIso8601String(),
      });

  // ── Water ──────────────────────────────────────────────────────────────
  Future<List<WaterLog>> water({int days = 1}) async {
    final res = await _api.get<dynamic>('/health-logs/water',
        query: {'days': days});
    return jList(res, ['items', 'logs']).map(WaterLog.fromJson).toList()
      ..sort((a, b) => b.loggedAt.compareTo(a.loggedAt));
  }

  Future<void> addWater({required double ml, required DateTime at}) =>
      _api.post<dynamic>('/health-logs/water', data: {
        'amount_ml': ml.round(),
        'recorded_at': at.toUtc().toIso8601String(),
      });

  // ── Medications ────────────────────────────────────────────────────────
  /// Medications with today's taken slots merged in from `/medications/today`.
  Future<List<Medication>> medications() async {
    final (meds, today) = await (
      _api.get<dynamic>('/medications', query: {'active_only': true}),
      _api.get<dynamic>('/medications/today'),
    ).wait;
    final taken = <int, Set<String>>{};
    for (final slot in jList(today, ['items'])) {
      if (jStr(slot, ['status']) != 'taken') continue;
      final id = jInt(slot, ['medication_id']);
      final time = jStr(slot, ['time']);
      if (id != null && time != null) (taken[id] ??= {}).add(time);
    }
    return [
      for (final j in jList(meds, ['items']))
        Medication.fromJson(j, takenToday: taken[jInt(j, ['id'])] ?? const {}),
    ];
  }

  Future<void> addMedication({
    required String name,
    required String dose,
    required MedForm form,
    required List<String> times,
  }) =>
      _api.post<dynamic>('/medications', data: {
        'name': name,
        'dosage': dose,
        'form': form.name,
        'frequency': Medication.frequencyFor(times.length),
        'times': times,
      });

  Future<void> markDoseTaken(int medicationId, String scheduledTime) =>
      _api.post<dynamic>('/medications/$medicationId/doses', data: {
        'scheduled_time': scheduledTime,
        'status': 'taken',
      });

  Future<void> deleteMedication(int id) => _api.delete<dynamic>('/medications/$id');

  /// This week's (Mon–Sun) adherence per day as 0..1; days with nothing
  /// scheduled are 0.
  Future<WeekSeries> adherence() async {
    final res = await _api.get<dynamic>('/medications/adherence');
    final days = <DateTime>[];
    final values = <double>[];
    for (final d in jList(res, ['by_day'])) {
      final date = DateTime.tryParse(jStr(d, ['date']) ?? '');
      if (date == null) continue;
      days.add(date);
      values.add((jNum(d, ['adherence_percent']) ?? 0) / 100);
    }
    return WeekSeries(days, values);
  }
}

final trackingRepositoryProvider =
    Provider((ref) => TrackingRepository(ref.watch(apiClientProvider)));

// Providers screens watch. Invalidate after a successful add.
final glucoseReadingsProvider = FutureProvider.autoDispose(
    (ref) => ref.watch(trackingRepositoryProvider).glucose(days: 7));
final glucoseSummaryProvider = FutureProvider.autoDispose(
    (ref) => ref.watch(trackingRepositoryProvider).glucoseSummary(days: 7));
final mealsForDayProvider = FutureProvider.autoDispose.family<List<Meal>, DateTime>(
    (ref, day) => ref.watch(trackingRepositoryProvider).meals(date: day));
final workoutsProvider = FutureProvider.autoDispose(
    (ref) => ref.watch(trackingRepositoryProvider).workouts(days: 7));
final waterTodayProvider = FutureProvider.autoDispose(
    (ref) => ref.watch(trackingRepositoryProvider).water(days: 1));
final waterWeekProvider = FutureProvider.autoDispose(
    (ref) => ref.watch(trackingRepositoryProvider).water(days: 7));

/// Refresh every tracking list after a log is added.
void invalidateTracking(WidgetRef ref) => ref
  ..invalidate(glucoseReadingsProvider)
  ..invalidate(glucoseSummaryProvider)
  ..invalidate(mealsForDayProvider)
  ..invalidate(workoutsProvider)
  ..invalidate(waterTodayProvider)
  ..invalidate(waterWeekProvider)
  ..invalidate(medicationsProvider)
  ..invalidate(adherenceProvider);
final medicationsProvider = FutureProvider.autoDispose(
    (ref) => ref.watch(trackingRepositoryProvider).medications());
final adherenceProvider = FutureProvider.autoDispose(
    (ref) => ref.watch(trackingRepositoryProvider).adherence());

/// Daily goals; move to user preferences once the backend exposes them.
const waterGoalMl = 2000.0;
const exerciseGoalMinutes = 30.0;
