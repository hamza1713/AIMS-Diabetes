import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../../core/utils/json.dart';
import '../domain/cdc_risk.dart';

class RiskHistoryEntry {
  RiskHistoryEntry({required this.score, required this.band, required this.at});
  final int score;
  final RiskBand band;
  final DateTime at;

  factory RiskHistoryEntry.fromJson(Json j) {
    final score = jInt(j, ['risk_score', 'score']) ?? 0;
    return RiskHistoryEntry(
      score: score,
      band: RiskBand.parse(jStr(j, ['risk_level', 'band']), score),
      at: jDate(j, ['created_at', 'assessed_at']) ?? DateTime.now(),
    );
  }
}

class RiskRepository {
  RiskRepository(this._api);
  final ApiClient _api;

  /// Saves on the server; the server's score wins if it differs.
  Future<CdcResult> submit(CdcAnswers answers) async {
    final local = scoreCdc(answers);
    final res = await _api.post<Json>('/risk-assessment/cdc', data: answers.toJson());
    final score = jInt(res, ['score', 'risk_score']) ?? local.score;
    final recs = res['recommendations'];
    final serverFactors = [
      for (final f in jList(res, ['factors']))
        RiskFactor(
          jStr(f, ['question', 'key']) ?? '',
          jInt(f, ['points']) ?? 0,
          jInt(f, ['max_points']) ?? 1,
        ),
    ];
    return CdcResult(
      score: score,
      band: RiskBand.parse(jStr(res, ['risk_level', 'band']), score),
      factors: serverFactors.isEmpty ? local.factors : serverFactors,
      recommendations: recs is List && recs.isNotEmpty
          ? recs.map((e) => '$e').toList()
          : local.recommendations,
      saved: true,
    );
  }

  Future<RiskHistoryEntry?> latest() async {
    final res = await _api.get<dynamic>('/risk-assessment/history');
    final items = jList(res, ['items']);
    return items.isEmpty ? null : RiskHistoryEntry.fromJson(items.first);
  }
}

final riskRepositoryProvider =
    Provider((ref) => RiskRepository(ref.watch(apiClientProvider)));

final latestRiskProvider = FutureProvider.autoDispose(
    (ref) => ref.watch(riskRepositoryProvider).latest());
