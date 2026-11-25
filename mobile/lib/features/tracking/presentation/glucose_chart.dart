import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/utils/format.dart';
import '../data/tracking_models.dart';

Color bandColor(GlucoseBand b) => switch (b) {
      GlucoseBand.low => AppColors.warning,
      GlucoseBand.inRange => AppColors.success,
      GlucoseBand.high => AppColors.danger,
    };

/// 7-day glucose line chart with the 70–180 mg/dL target band (Figma 06).
/// With [compact] it renders as a sparkline (Home card).
class GlucoseChart extends StatelessWidget {
  const GlucoseChart({
    super.key,
    required this.readings,
    this.compact = false,
    this.height = 200,
  });

  final List<GlucoseReading> readings;
  final bool compact;
  final double height;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final now = DateTime.now();
    final start = DateTime(now.year, now.month, now.day - 6);
    final points = readings
        .where((r) => !r.recordedAt.isBefore(start))
        .map((r) => FlSpot(
              r.recordedAt.difference(start).inMinutes / (60 * 24),
              r.value,
            ))
        .toList()
      ..sort((a, b) => a.x.compareTo(b.x));

    final maxY = [
      250.0,
      ...points.map((s) => s.y + 20),
    ].reduce((a, b) => a > b ? a : b);

    return SizedBox(
      height: height,
      child: LineChart(
        LineChartData(
          minX: 0,
          maxX: 7,
          minY: 40,
          maxY: maxY,
          gridData: FlGridData(
            show: !compact,
            drawVerticalLine: false,
            horizontalInterval: 50,
            getDrawingHorizontalLine: (_) =>
                FlLine(color: p.border, strokeWidth: 1),
          ),
          borderData: FlBorderData(show: false),
          rangeAnnotations: RangeAnnotations(horizontalRangeAnnotations: [
            HorizontalRangeAnnotation(
              y1: glucoseTargetLow,
              y2: glucoseTargetHigh,
              color: AppColors.success.withValues(alpha: 0.08),
            ),
          ]),
          titlesData: FlTitlesData(
            show: !compact,
            topTitles: const AxisTitles(),
            rightTitles: const AxisTitles(),
            leftTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 36,
                interval: 50,
                getTitlesWidget: (v, _) => Text(v.toInt().toString(),
                    style: TextStyle(fontSize: 10, color: p.textSecondary)),
              ),
            ),
            bottomTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                interval: 1,
                getTitlesWidget: (v, _) {
                  if (v >= 7) return const SizedBox.shrink();
                  final d = start.add(Duration(days: v.toInt()));
                  return Text(fmtWeekday(d),
                      style: TextStyle(fontSize: 10, color: p.textSecondary));
                },
              ),
            ),
          ),
          lineTouchData: LineTouchData(enabled: !compact),
          lineBarsData: [
            LineChartBarData(
              spots: points,
              isCurved: true,
              preventCurveOverShooting: true,
              color: AppColors.primary,
              barWidth: compact ? 2.5 : 3,
              dotData: FlDotData(
                show: !compact,
                getDotPainter: (s, _, _, _) => FlDotCirclePainter(
                  radius: 3.5,
                  color: bandColor(bandFor(s.y)),
                  strokeWidth: 1.5,
                  strokeColor: p.surface,
                ),
              ),
              belowBarData: BarAreaData(
                show: true,
                gradient: LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [
                    AppColors.primary.withValues(alpha: 0.18),
                    AppColors.primary.withValues(alpha: 0),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
