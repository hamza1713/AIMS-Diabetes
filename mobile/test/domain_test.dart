import 'package:aims_diabetes/core/theme/app_theme.dart';
import 'package:aims_diabetes/features/chat/data/chat_models.dart';
import 'package:aims_diabetes/features/risk/domain/cdc_risk.dart';
import 'package:aims_diabetes/features/risk/presentation/risk_screens.dart';
import 'package:aims_diabetes/features/tracking/data/tracking_models.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_fonts/google_fonts.dart';

void main() {
  setUpAll(() => GoogleFonts.config.allowRuntimeFetching = false);

  group('CDC risk score', () {
    test('lowest risk answers score 0', () {
      final r = scoreCdc(const CdcAnswers(
        age: AgeBand.under40,
        sex: Sex.female,
        gestational: false,
        familyHistory: false,
        highBloodPressure: false,
        physicallyActive: true,
        heightCm: 170,
        weightKg: 60, // BMI 20.8
      ));
      expect(r.score, 0);
      expect(r.band, RiskBand.low);
    });

    test('highest risk answers score the maximum 11', () {
      final r = scoreCdc(const CdcAnswers(
        age: AgeBand.over60,
        sex: Sex.male,
        gestational: true,
        familyHistory: true,
        highBloodPressure: true,
        physicallyActive: false,
        heightCm: 170,
        weightKg: 120, // BMI 41.5
      ));
      expect(r.score, CdcResult.maxScore);
      expect(r.band, RiskBand.high);
      expect(r.factors.fold<int>(0, (s, f) => s + f.maxPoints), CdcResult.maxScore);
    });

    test('score of 5 is the high-risk threshold', () {
      expect(RiskBand.fromScore(4), RiskBand.moderate);
      expect(RiskBand.fromScore(5), RiskBand.high);
      expect(RiskBand.fromScore(2), RiskBand.low);
    });

    test('BMI bands', () {
      expect(WeightBand.fromBmi(24.9), WeightBand.normal);
      expect(WeightBand.fromBmi(25), WeightBand.overweight);
      expect(WeightBand.fromBmi(30), WeightBand.obese);
      expect(WeightBand.fromBmi(40), WeightBand.severe);
    });
  });

  group('model parsing', () {
    test('glucose reading from current backend shape', () {
      final r = GlucoseReading.fromJson({
        'id': 3,
        'measurement_type': 'Postprandial',
        'glucose_value': 210,
        'recorded_at': '2026-11-25T08:30:00',
      });
      expect(r.value, 210);
      expect(r.when, GlucoseWhen.afterMeal);
      expect(r.band, GlucoseBand.high);
      expect(r.recordedAt.isUtc, isFalse);
    });

    test('backend `when` wins over measurement_type', () {
      final r = GlucoseReading.fromJson({
        'measurement_type': 'Random',
        'when': 'before_meal',
        'glucose_value': '95',
        'recorded_at': '2026-11-25T08:30:00Z',
      });
      expect(r.when, GlucoseWhen.beforeMeal);
      expect(r.value, 95);
    });

    test('CDC request matches the backend schema', () {
      final body = const CdcAnswers(
        age: AgeBand.from50to59,
        sex: Sex.male,
        gestational: true, // ignored for men
        familyHistory: true,
        highBloodPressure: false,
        physicallyActive: true,
      ).toJson();
      expect(body['age'], 55);
      expect(body['sex'], 'male');
      expect(body['gestational_diabetes'], isFalse);
      expect(body.containsKey('height_cm'), isFalse); // server uses profile
    });

    test('medication merges taken slots and derives frequency', () {
      final m = Medication.fromJson(
        {'id': 1, 'name': 'Metformin', 'dosage': '500 mg', 'times': ['08:00', '20:00']},
        takenToday: {'08:00'},
      );
      expect(m.dose, '500 mg');
      expect(m.timesPerDay, 2);
      expect(m.takenToday, {'08:00'});
      expect(Medication.frequencyFor(2), 'twice_daily');
    });

    test('meal falls back to description and carbs_grams', () {
      final m = Meal.fromJson({
        'meal_type': 'Lunch',
        'description': 'Rice and dal',
        'carbs_grams': 60,
      });
      expect(m.type, MealType.lunch);
      expect(m.name, 'Rice and dal');
      expect(m.carbs, 60);
      expect(m.calories, 0);
    });

    test('chat source builds absolute image url and citation', () {
      final s = ChatSource.fromJson({
        'title': 'Metformin trial',
        'journal': 'Diabetes Care',
        'publication_year': 2021,
        'page_number': 4,
        'image_url': '/rendered_pages/doc_4.png',
      });
      expect(s.citation, 'Diabetes Care · 2021 · p. 4');
      expect(s.absoluteImageUrl, endsWith('/rendered_pages/doc_4.png'));
      expect(s.absoluteImageUrl, startsWith('http'));
    });
  });

  test('WeekSeries sums values into the last 7 days', () {
    final now = DateTime.now();
    final items = [
      (now, 20.0),
      (now, 15.0),
      (now.subtract(const Duration(days: 1)), 10.0),
      (now.subtract(const Duration(days: 10)), 99.0), // outside the window
    ];
    final w = WeekSeries.fromDated(items, (e) => e.$1, (e) => e.$2);
    expect(w.days, hasLength(7));
    expect(w.values.last, 35);
    expect(w.values[5], 10);
    expect(w.values.reduce((a, b) => a + b), 45);
  });

  testWidgets('risk result shows score, band and offline note', (tester) async {
    final result = scoreCdc(const CdcAnswers(
      age: AgeBand.over60,
      sex: Sex.male,
      familyHistory: true,
      highBloodPressure: false,
      physicallyActive: false,
      heightCm: 175,
      weightKg: 70,
    ));
    await tester.pumpWidget(MaterialApp(
      theme: AppTheme.light(),
      home: RiskResultScreen(result: result),
    ));
    expect(find.text('${result.score}'), findsOneWidget);
    expect(find.text('High risk'), findsOneWidget);
    expect(find.textContaining('Not saved'), findsOneWidget);
  });
}
