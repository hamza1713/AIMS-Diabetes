// CDC / ADA prediabetes risk test (7 questions, max 11 points).
// Mirrors the backend's `/risk-assessment/cdc` so results can be shown
// instantly and still work offline.

enum AgeBand {
  under40('Under 40', 0, 35),
  from40to49('40 – 49', 1, 45),
  from50to59('50 – 59', 2, 55),
  over60('60 or older', 3, 65);

  const AgeBand(this.label, this.points, this.representativeAge);
  final String label;
  final int points;

  /// The backend takes an integer age; any age inside the band scores the same.
  final int representativeAge;
}

enum Sex {
  female('Female', 0),
  male('Male', 1);

  const Sex(this.label, this.points);
  final String label;
  final int points;
}

/// Weight band from BMI (approximates the CDC height/weight table).
enum WeightBand {
  normal('Below 25', 0),
  overweight('25 – 29.9', 1),
  obese('30 – 39.9', 2),
  severe('40 or higher', 3);

  const WeightBand(this.label, this.points);
  final String label;
  final int points;

  static WeightBand fromBmi(double bmi) => bmi >= 40
      ? severe
      : bmi >= 30
          ? obese
          : bmi >= 25
              ? overweight
              : normal;
}

class CdcAnswers {
  const CdcAnswers({
    this.age,
    this.sex,
    this.gestational,
    this.familyHistory,
    this.highBloodPressure,
    this.physicallyActive,
    this.heightCm,
    this.weightKg,
  });

  final AgeBand? age;
  final Sex? sex;
  final bool? gestational;
  final bool? familyHistory;
  final bool? highBloodPressure;
  final bool? physicallyActive;
  final double? heightCm;
  final double? weightKg;

  double? get bmi {
    if (heightCm == null || weightKg == null || heightCm! <= 0) return null;
    final m = heightCm! / 100;
    return weightKg! / (m * m);
  }

  CdcAnswers copyWith({
    AgeBand? age,
    Sex? sex,
    bool? gestational,
    bool? familyHistory,
    bool? highBloodPressure,
    bool? physicallyActive,
    double? heightCm,
    double? weightKg,
  }) =>
      CdcAnswers(
        age: age ?? this.age,
        sex: sex ?? this.sex,
        gestational: gestational ?? this.gestational,
        familyHistory: familyHistory ?? this.familyHistory,
        highBloodPressure: highBloodPressure ?? this.highBloodPressure,
        physicallyActive: physicallyActive ?? this.physicallyActive,
        heightCm: heightCm ?? this.heightCm,
        weightKg: weightKg ?? this.weightKg,
      );

  /// Body for `POST /risk-assessment/cdc`.
  Map<String, dynamic> toJson() => {
        'age': (age ?? AgeBand.under40).representativeAge,
        'sex': (sex ?? Sex.female).name,
        'gestational_diabetes': sex == Sex.female && (gestational ?? false),
        'family_history': familyHistory ?? false,
        'high_blood_pressure': highBloodPressure ?? false,
        'physically_active': physicallyActive ?? false,
        'height_cm': ?heightCm,
        'weight_kg': ?weightKg,
      };
}

enum RiskBand {
  low('Low risk'),
  moderate('Moderate risk'),
  high('High risk');

  const RiskBand(this.label);
  final String label;

  static RiskBand fromScore(int score) =>
      score >= 5 ? high : score >= 3 ? moderate : low;

  static RiskBand parse(String? v, int score) {
    final s = v?.toLowerCase() ?? '';
    if (s.contains('high')) return high;
    if (s.contains('moderate') || s.contains('medium')) return moderate;
    if (s.contains('low')) return low;
    return fromScore(score);
  }
}

class RiskFactor {
  const RiskFactor(this.label, this.points, this.maxPoints);
  final String label;
  final int points;
  final int maxPoints;
}

class CdcResult {
  const CdcResult({
    required this.score,
    required this.band,
    required this.factors,
    required this.recommendations,
    this.saved = false,
  });

  static const maxScore = 11;

  final int score;
  final RiskBand band;
  final List<RiskFactor> factors;
  final List<String> recommendations;
  final bool saved;
}

CdcResult scoreCdc(CdcAnswers a) {
  final weight = a.bmi == null ? null : WeightBand.fromBmi(a.bmi!);
  final factors = [
    RiskFactor('Age', a.age?.points ?? 0, 3),
    RiskFactor('Sex', a.sex?.points ?? 0, 1),
    RiskFactor('Gestational diabetes', a.gestational == true ? 1 : 0, 1),
    RiskFactor('Family history', a.familyHistory == true ? 1 : 0, 1),
    RiskFactor('High blood pressure', a.highBloodPressure == true ? 1 : 0, 1),
    RiskFactor('Physical activity', a.physicallyActive == false ? 1 : 0, 1),
    RiskFactor('Weight', weight?.points ?? 0, 3),
  ];
  final score = factors.fold<int>(0, (s, f) => s + f.points);
  final band = RiskBand.fromScore(score);
  return CdcResult(
    score: score,
    band: band,
    factors: factors,
    recommendations: _recommendations(band, a, weight),
  );
}

List<String> _recommendations(RiskBand band, CdcAnswers a, WeightBand? w) => [
      if (band == RiskBand.high)
        'Talk to your doctor about an HbA1c or fasting glucose test.',
      if (a.physicallyActive == false)
        'Aim for 150 minutes of moderate activity each week.',
      if (w != null && w.points > 0)
        'Losing 5–7% of body weight can lower your risk significantly.',
      if (a.highBloodPressure == true)
        'Keep your blood pressure under regular review.',
      'Choose whole grains, vegetables and lean protein; limit sugary drinks.',
      if (band != RiskBand.high) 'Retake this test once a year.',
    ];
