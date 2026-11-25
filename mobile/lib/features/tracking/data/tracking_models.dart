import '../../../core/utils/json.dart';

/// "When" options on Add Reading (Figma 17). [api] is the backend's `when`
/// value; it derives the legacy `measurement_type` from it.
enum GlucoseWhen {
  fasting('Fasting', 'fasting'),
  beforeMeal('Before meal', 'before_meal'),
  afterMeal('After meal', 'after_meal'),
  bedtime('Bedtime', 'bedtime'),
  random('Random', 'random');

  const GlucoseWhen(this.label, this.api);
  final String label;
  final String api;

  static GlucoseWhen parse(String? when, String? measurementType) {
    for (final w in values) {
      if (w.api == when || w.name == when || w.label == when) return w;
    }
    return switch (measurementType) {
      'Fasting' => GlucoseWhen.fasting,
      'Postprandial' => GlucoseWhen.afterMeal,
      _ => GlucoseWhen.random,
    };
  }
}

/// Target band used for colouring readings (mg/dL).
enum GlucoseBand { low, inRange, high }

const glucoseTargetLow = 70.0;
const glucoseTargetHigh = 180.0;

GlucoseBand bandFor(double mgdl) => mgdl < glucoseTargetLow
    ? GlucoseBand.low
    : mgdl > glucoseTargetHigh
        ? GlucoseBand.high
        : GlucoseBand.inRange;

class GlucoseReading {
  GlucoseReading({
    required this.id,
    required this.value,
    required this.when,
    required this.recordedAt,
    this.notes,
  });

  final int? id;
  final double value;
  final GlucoseWhen when;
  final DateTime recordedAt;
  final String? notes;

  GlucoseBand get band => bandFor(value);

  factory GlucoseReading.fromJson(Json j) => GlucoseReading(
        id: jInt(j, ['id']),
        value: jNum(j, ['glucose_value', 'value']) ?? 0,
        when: GlucoseWhen.parse(
            jStr(j, ['when', 'context']), jStr(j, ['measurement_type'])),
        recordedAt: jDate(j, ['recorded_at', 'measured_at', 'created_at']) ??
            DateTime.now(),
        notes: jStr(j, ['notes']),
      );
}

class GlucoseSummary {
  GlucoseSummary({
    required this.average,
    required this.timeInRange,
    required this.totalReadings,
    this.estimatedA1c,
  });

  final double? average;
  final double? timeInRange; // percent 0..100
  final int totalReadings;
  final double? estimatedA1c;

  factory GlucoseSummary.fromJson(Json j) => GlucoseSummary(
        average: jNum(j, ['average_glucose', 'average']),
        timeInRange: jNum(j, ['time_in_range_percent', 'time_in_range']),
        totalReadings: jInt(j, ['total_readings', 'count']) ?? 0,
        estimatedA1c: jNum(j, ['estimated_hba1c', 'estimated_a1c', 'hba1c']),
      );
}

enum MealType {
  breakfast('Breakfast'),
  lunch('Lunch'),
  dinner('Dinner'),
  snack('Snack');

  const MealType(this.label);
  final String label;

  static MealType parse(String? v) => values.firstWhere(
        (m) => m.name == v?.toLowerCase() || m.label == v,
        orElse: () => MealType.snack,
      );
}

class Meal {
  Meal({
    required this.id,
    required this.type,
    required this.name,
    required this.carbs,
    required this.calories,
    required this.protein,
    required this.fat,
    required this.loggedAt,
  });

  final int? id;
  final MealType type;
  final String name;
  final double carbs;
  final double calories;
  final double protein;
  final double fat;
  final DateTime loggedAt;

  factory Meal.fromJson(Json j) => Meal(
        id: jInt(j, ['id']),
        type: MealType.parse(jStr(j, ['meal_type', 'type'])),
        name: jStr(j, ['name', 'description']) ?? 'Meal',
        carbs: jNum(j, ['carbs_grams', 'carbs_g', 'carbs']) ?? 0,
        calories: jNum(j, ['calories', 'kcal']) ?? 0,
        protein: jNum(j, ['protein_g', 'protein']) ?? 0,
        fat: jNum(j, ['fat_g', 'fat']) ?? 0,
        loggedAt:
            jDate(j, ['logged_at', 'recorded_at', 'created_at']) ?? DateTime.now(),
      );
}

/// Daily nutrition goals (from preferences later; sensible defaults now).
class NutritionGoals {
  const NutritionGoals({
    this.calories = 2000,
    this.carbs = 200,
    this.protein = 90,
    this.fat = 65,
  });
  final double calories, carbs, protein, fat;
}

enum Intensity {
  low('Low'),
  moderate('Moderate'),
  high('High');

  const Intensity(this.label);
  final String label;
  static Intensity parse(String? v) => values.firstWhere(
      (i) => i.name == v?.toLowerCase(),
      orElse: () => Intensity.moderate);
}

class Workout {
  Workout({
    required this.id,
    required this.activity,
    required this.minutes,
    required this.calories,
    required this.intensity,
    required this.loggedAt,
  });

  final int? id;
  final String activity;
  final double minutes;
  final double calories;
  final Intensity intensity;
  final DateTime loggedAt;

  factory Workout.fromJson(Json j) => Workout(
        id: jInt(j, ['id']),
        activity: jStr(j, ['activity', 'activity_type', 'name']) ?? 'Workout',
        minutes: jNum(j, ['duration_min', 'duration_minutes', 'duration']) ?? 0,
        calories: jNum(j, ['calories', 'calories_burned']) ?? 0,
        intensity: Intensity.parse(jStr(j, ['intensity'])),
        loggedAt: jDate(j, ['logged_at', 'performed_at', 'recorded_at', 'created_at']) ??
            DateTime.now(),
      );
}

class WaterLog {
  WaterLog({required this.id, required this.ml, required this.loggedAt});
  final int? id;
  final double ml;
  final DateTime loggedAt;

  factory WaterLog.fromJson(Json j) => WaterLog(
        id: jInt(j, ['id']),
        ml: jNum(j, ['amount_ml', 'ml', 'amount']) ?? 0,
        loggedAt: jDate(j, ['logged_at', 'recorded_at', 'created_at']) ??
            DateTime.now(),
      );
}

enum MedForm {
  tablet('Tablet'),
  capsule('Capsule'),
  injection('Injection'),
  liquid('Liquid');

  const MedForm(this.label);
  final String label;
  static MedForm parse(String? v) => values.firstWhere(
      (f) => f.name == v?.toLowerCase(),
      orElse: () => MedForm.tablet);
}

class Medication {
  Medication({
    required this.id,
    required this.name,
    required this.dose,
    required this.form,
    required this.timesPerDay,
    required this.times,
    required this.reminders,
    required this.takenToday,
  });

  final int id;
  final String name;
  final String dose;
  final MedForm form;
  final int timesPerDay;
  final List<String> times; // "08:00"
  final bool reminders;

  /// Scheduled times already marked as taken today.
  final Set<String> takenToday;

  /// [takenToday] comes from `/medications/today` (slots with
  /// `status == 'taken'`), merged in by the repository.
  factory Medication.fromJson(Json j, {Set<String> takenToday = const {}}) {
    final times = j['times'];
    final list = times is List ? times.map((e) => '$e').toList() : <String>[];
    return Medication(
      id: jInt(j, ['id']) ?? 0,
      name: jStr(j, ['name']) ?? 'Medication',
      dose: jStr(j, ['dosage', 'dose']) ?? '',
      form: MedForm.parse(jStr(j, ['form'])),
      timesPerDay: list.isEmpty ? 1 : list.length,
      times: list,
      // The backend has no per-medication reminder flag; the global
      // "Medication reminders" preference controls notifications.
      reminders: jBool(j, ['active'], fallback: true),
      takenToday: takenToday,
    );
  }

  /// Backend `frequency` label for a number of daily doses.
  static String frequencyFor(int perDay) => switch (perDay) {
        1 => 'once_daily',
        2 => 'twice_daily',
        3 => 'three_times_daily',
        _ => '${perDay}_times_daily',
      };
}

/// Seven daily totals ending today, for weekly bar charts.
class WeekSeries {
  WeekSeries(this.days, this.values);
  final List<DateTime> days;
  final List<double> values;

  static List<DateTime> lastSevenDays() {
    final now = DateTime.now();
    return [
      for (var i = 6; i >= 0; i--) DateTime(now.year, now.month, now.day - i),
    ];
  }

  factory WeekSeries.empty() =>
      WeekSeries(lastSevenDays(), List<double>.filled(7, 0));

  static WeekSeries fromDated<T>(
    Iterable<T> items,
    DateTime Function(T) at,
    double Function(T) value,
  ) {
    final days = lastSevenDays();
    final values = List<double>.filled(7, 0);
    for (final item in items) {
      final d = at(item);
      final idx = days.indexWhere(
          (day) => day.year == d.year && day.month == d.month && day.day == d.day);
      if (idx >= 0) values[idx] += value(item);
    }
    return WeekSeries(days, values);
  }
}
