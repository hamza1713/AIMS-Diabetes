import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/network/api_client.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/utils/format.dart';
import '../../core/utils/json.dart';
import '../../core/widgets/app_card.dart';
import '../../core/widgets/async_view.dart';

class MonthlySummary {
  MonthlySummary({
    this.avgGlucose,
    this.timeInRange,
    this.avgCarbs,
    this.activeDays,
    this.estimatedA1c,
    this.trend = const [],
  });

  final double? avgGlucose;
  final double? timeInRange;
  final double? avgCarbs;
  final int? activeDays;
  final double? estimatedA1c;
  final List<(DateTime, double)> trend; // daily average glucose

  /// Backend shape: `{glucose{average, time_in_range_percent,
  /// estimated_hba1c, daily[{date, average}]}, nutrition{avg_carbs_per_day},
  /// exercise{active_days}, …}`.
  factory MonthlySummary.fromJson(Json j) {
    final g = jObj(j, ['glucose']);
    return MonthlySummary(
      avgGlucose: jNum(g, ['average']),
      timeInRange: jNum(g, ['time_in_range_percent']),
      estimatedA1c: jNum(g, ['estimated_hba1c']),
      avgCarbs: jNum(jObj(j, ['nutrition']), ['avg_carbs_per_day']),
      activeDays: jInt(jObj(j, ['exercise']), ['active_days']),
      trend: [
        for (final p in jList(g, ['daily']))
          // Days without readings have a null average: leave a gap.
          if ((DateTime.tryParse(jStr(p, ['date']) ?? ''), jNum(p, ['average']))
              case (final d?, final v?))
            (d, v),
      ],
    );
  }
}

final _monthFmt = DateFormat('yyyy-MM');

final monthlySummaryProvider =
    FutureProvider.autoDispose.family<MonthlySummary, DateTime>((ref, month) async {
  final res = await ref
      .watch(apiClientProvider)
      .get<Json>('/analytics/summary', query: {'month': _monthFmt.format(month)});
  return MonthlySummary.fromJson(res);
});

/// Figma "13 · Analytics & Reports".
class AnalyticsScreen extends ConsumerStatefulWidget {
  const AnalyticsScreen({super.key});

  @override
  ConsumerState<AnalyticsScreen> createState() => _AnalyticsScreenState();
}

class _AnalyticsScreenState extends ConsumerState<AnalyticsScreen> {
  DateTime _month = DateTime(DateTime.now().year, DateTime.now().month);

  void _shift(int delta) =>
      setState(() => _month = DateTime(_month.year, _month.month + delta));

  bool get _isCurrent {
    final n = DateTime.now();
    return _month.year == n.year && _month.month == n.month;
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Analytics & Reports')),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.page),
            child: Row(
              children: [
                IconButton(
                    onPressed: () => _shift(-1),
                    icon: const Icon(Icons.chevron_left_rounded)),
                Expanded(
                  child: Text(DateFormat.yMMMM().format(_month),
                      style: t.titleMedium, textAlign: TextAlign.center),
                ),
                IconButton(
                    onPressed: _isCurrent ? null : () => _shift(1),
                    icon: const Icon(Icons.chevron_right_rounded)),
              ],
            ),
          ),
          Expanded(
            child: AsyncView(
              value: ref.watch(monthlySummaryProvider(_month)),
              onRetry: () => ref.invalidate(monthlySummaryProvider(_month)),
              data: (s) => ListView(
                padding: const EdgeInsets.fromLTRB(
                    AppSpacing.page, AppSpacing.sm, AppSpacing.page, 100),
                children: [
                  GridView.count(
                    crossAxisCount: 2,
                    shrinkWrap: true,
                    physics: const NeverScrollableScrollPhysics(),
                    mainAxisSpacing: AppSpacing.md,
                    crossAxisSpacing: AppSpacing.md,
                    childAspectRatio: 1.45,
                    children: [
                      StatTile(
                        icon: Icons.bloodtype_outlined,
                        value: '${fmtNum(s.avgGlucose)} mg/dL',
                        label: 'Avg glucose',
                        color: AppColors.danger,
                      ),
                      StatTile(
                        icon: Icons.check_circle_outline_rounded,
                        value: '${fmtNum(s.timeInRange)}%',
                        label: 'Time in range',
                        color: AppColors.success,
                      ),
                      StatTile(
                        icon: Icons.restaurant_rounded,
                        value: '${fmtNum(s.avgCarbs)} g',
                        label: 'Avg carbs / day',
                        color: AppColors.warning,
                      ),
                      StatTile(
                        icon: Icons.directions_run_rounded,
                        value: '${s.activeDays ?? '—'}',
                        label: 'Active days',
                        color: AppColors.info,
                      ),
                    ],
                  ),
                  if (s.estimatedA1c != null) ...[
                    const SizedBox(height: AppSpacing.md),
                    AppCard(
                      child: Row(
                        children: [
                          Expanded(child: Text('Estimated HbA1c', style: t.titleMedium)),
                          Text('${s.estimatedA1c!.toStringAsFixed(1)}%',
                              style: t.titleLarge),
                        ],
                      ),
                    ),
                  ],
                  const SizedBox(height: AppSpacing.xl),
                  const SectionHeader('Glucose trend'),
                  AppCard(child: _TrendChart(points: s.trend)),
                  const SizedBox(height: AppSpacing.xl),
                  OutlinedButton.icon(
                    // PDF export endpoint is not built yet (guide: "PDF report GAP").
                    onPressed: () => ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('PDF reports are coming soon.')),
                    ),
                    icon: const Icon(Icons.picture_as_pdf_outlined),
                    label: const Text('Download PDF report'),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _TrendChart extends StatelessWidget {
  const _TrendChart({required this.points});
  final List<(DateTime, double)> points;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    if (points.isEmpty) {
      return const SizedBox(
        height: 160,
        child: Center(child: Text('No readings this month')),
      );
    }
    final sorted = [...points]..sort((a, b) => a.$1.compareTo(b.$1));
    return SizedBox(
      height: 180,
      child: LineChart(
        LineChartData(
          minY: 40,
          gridData: FlGridData(
            drawVerticalLine: false,
            getDrawingHorizontalLine: (_) => FlLine(color: p.border, strokeWidth: 1),
          ),
          borderData: FlBorderData(show: false),
          titlesData: FlTitlesData(
            topTitles: const AxisTitles(),
            rightTitles: const AxisTitles(),
            leftTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 36,
                getTitlesWidget: (v, _) => Text(v.toInt().toString(),
                    style: TextStyle(fontSize: 10, color: p.textSecondary)),
              ),
            ),
            bottomTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                interval: 7,
                getTitlesWidget: (v, _) => Text('${v.toInt()}',
                    style: TextStyle(fontSize: 10, color: p.textSecondary)),
              ),
            ),
          ),
          rangeAnnotations: RangeAnnotations(horizontalRangeAnnotations: [
            HorizontalRangeAnnotation(
              y1: 70,
              y2: 180,
              color: AppColors.success.withValues(alpha: 0.08),
            ),
          ]),
          lineBarsData: [
            LineChartBarData(
              spots: [for (final (d, v) in sorted) FlSpot(d.day.toDouble(), v)],
              isCurved: true,
              preventCurveOverShooting: true,
              color: AppColors.primary,
              barWidth: 3,
              dotData: const FlDotData(show: false),
            ),
          ],
        ),
      ),
    );
  }
}
