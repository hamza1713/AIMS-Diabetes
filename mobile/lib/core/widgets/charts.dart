import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../utils/format.dart';

/// Circular progress (water %, adherence, time-in-range).
class ProgressRing extends StatelessWidget {
  const ProgressRing({
    super.key,
    required this.value,
    required this.center,
    this.size = 120,
    this.stroke = 12,
    this.color = AppColors.primary,
  });

  final double value; // 0..1
  final Widget center;
  final double size;
  final double stroke;
  final Color color;

  @override
  Widget build(BuildContext context) => SizedBox(
        width: size,
        height: size,
        child: Stack(
          fit: StackFit.expand,
          children: [
            CircularProgressIndicator(
              value: value.clamp(0, 1).toDouble(),
              strokeWidth: stroke,
              strokeCap: StrokeCap.round,
              color: color,
              backgroundColor: color.withValues(alpha: 0.12),
            ),
            Center(child: center),
          ],
        ),
      );
}

/// Horizontal progress bar with label (goals: water, exercise, macros).
class GoalBar extends StatelessWidget {
  const GoalBar({
    super.key,
    required this.label,
    required this.value,
    required this.goal,
    required this.unit,
    this.color = AppColors.primary,
  });

  final String label;
  final double value;
  final double goal;
  final String unit;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(child: Text(label, style: t.bodyMedium)),
            Text('${fmtNum(value)} / ${fmtNum(goal)} $unit', style: t.bodySmall),
          ],
        ),
        const SizedBox(height: AppSpacing.xs),
        ClipRRect(
          borderRadius: BorderRadius.circular(AppRadius.pill),
          child: LinearProgressIndicator(
            value: goal <= 0 ? 0 : (value / goal).clamp(0, 1).toDouble(),
            minHeight: 8,
            color: color,
            backgroundColor: color.withValues(alpha: 0.12),
          ),
        ),
      ],
    );
  }
}

/// Simple 7-day bar chart (exercise minutes, water, carbs).
class WeekBars extends StatelessWidget {
  const WeekBars({
    super.key,
    required this.days,
    required this.values,
    this.goal,
    this.color = AppColors.primary,
    this.height = 140,
  });

  final List<DateTime> days;
  final List<double> values;
  final double? goal;
  final Color color;
  final double height;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final maxV = [...values, goal ?? 0, 1].reduce(math.max).toDouble();
    return SizedBox(
      height: height,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          for (var i = 0; i < days.length; i++)
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    Flexible(
                      child: FractionallySizedBox(
                        heightFactor: (values[i] / maxV).clamp(0.03, 1).toDouble(),
                        child: Container(
                          decoration: BoxDecoration(
                            color: goal != null && values[i] >= goal!
                                ? color
                                : color.withValues(alpha: 0.45),
                            borderRadius: BorderRadius.circular(6),
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: AppSpacing.xs),
                    Text(
                      fmtWeekday(days[i]).substring(0, 1),
                      style: Theme.of(context)
                          .textTheme
                          .bodySmall
                          ?.copyWith(color: p.textSecondary),
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

/// Horizontal week selector used on Health Tracking (04).
class WeekStrip extends StatelessWidget {
  const WeekStrip({super.key, required this.selected, required this.onSelect});
  final DateTime selected;
  final ValueChanged<DateTime> onSelect;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final today = DateTime.now();
    final days = [
      for (var i = 6; i >= 0; i--)
        DateTime(today.year, today.month, today.day - i),
    ];
    return Row(
      children: [
        for (final d in days)
          Expanded(
            child: GestureDetector(
              onTap: () => onSelect(d),
              child: Container(
                margin: const EdgeInsets.symmetric(horizontal: 3),
                padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
                decoration: BoxDecoration(
                  color: isSameDay(d, selected) ? AppColors.primary : p.surface,
                  borderRadius: BorderRadius.circular(AppRadius.md),
                  border: Border.all(color: p.border),
                ),
                child: Column(
                  children: [
                    Text(
                      fmtWeekday(d),
                      style: TextStyle(
                        fontSize: 11,
                        color: isSameDay(d, selected)
                            ? Colors.white70
                            : p.textSecondary,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '${d.day}',
                      style: TextStyle(
                        fontWeight: FontWeight.w700,
                        color: isSameDay(d, selected)
                            ? Colors.white
                            : p.textPrimary,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
      ],
    );
  }
}
