import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/router/routes.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/utils/format.dart';
import '../../../core/widgets/app_card.dart';
import '../../../core/widgets/charts.dart';
import '../../../core/widgets/state_views.dart';
import '../data/tracking_repository.dart';
import 'glucose_chart.dart';
import 'log_tile.dart';

/// Figma "04 · Health Tracking": week strip + combined log for the day.
class TrackingHubScreen extends ConsumerStatefulWidget {
  const TrackingHubScreen({super.key});

  @override
  ConsumerState<TrackingHubScreen> createState() => _TrackingHubScreenState();
}

class _TrackingHubScreenState extends ConsumerState<TrackingHubScreen> {
  late DateTime _day = _today();

  static DateTime _today() {
    final n = DateTime.now();
    return DateTime(n.year, n.month, n.day);
  }

  @override
  Widget build(BuildContext context) {
    final glucose = ref.watch(glucoseReadingsProvider).value ?? const [];
    final meals = ref.watch(mealsForDayProvider(_day)).value ?? const [];
    final workouts = ref.watch(workoutsProvider).value ?? const [];
    final water = ref.watch(waterWeekProvider).value ?? const [];

    final entries = <(DateTime, Widget)>[
      for (final r in glucose.where((r) => isSameDay(r.recordedAt, _day)))
        (
          r.recordedAt,
          LogTile(
            icon: Icons.bloodtype_outlined,
            color: bandColor(r.band),
            title: 'Glucose',
            subtitle: r.when.label,
            trailing: '${fmtNum(r.value)} mg/dL',
            at: r.recordedAt,
          )
        ),
      for (final m in meals)
        (
          m.loggedAt,
          LogTile(
            icon: Icons.restaurant_rounded,
            color: AppColors.warning,
            title: m.name,
            subtitle: m.type.label,
            trailing: '${fmtNum(m.carbs)} g carbs',
            at: m.loggedAt,
          )
        ),
      for (final w in workouts.where((w) => isSameDay(w.loggedAt, _day)))
        (
          w.loggedAt,
          LogTile(
            icon: Icons.directions_run_rounded,
            color: AppColors.success,
            title: w.activity,
            subtitle: w.intensity.label,
            trailing: '${fmtNum(w.minutes)} min',
            at: w.loggedAt,
          )
        ),
      for (final w in water.where((w) => isSameDay(w.loggedAt, _day)))
        (
          w.loggedAt,
          LogTile(
            icon: Icons.water_drop_outlined,
            color: AppColors.water,
            title: 'Water',
            subtitle: 'Intake',
            trailing: '${fmtNum(w.ml)} ml',
            at: w.loggedAt,
          )
        ),
    ]..sort((a, b) => b.$1.compareTo(a.$1));

    return Scaffold(
      appBar: AppBar(title: const Text('Health Tracking')),
      body: RefreshIndicator(
        onRefresh: () async => invalidateTracking(ref),
        child: ListView(
          padding: const EdgeInsets.fromLTRB(
              AppSpacing.page, 0, AppSpacing.page, 100),
          children: [
            WeekStrip(selected: _day, onSelect: (d) => setState(() => _day = d)),
            const SizedBox(height: AppSpacing.xl),
            const _TrackerGrid(),
            const SizedBox(height: AppSpacing.xl),
            SectionHeader(isSameDay(_day, _today()) ? "Today's log" : 'Log for ${fmtDayMonth(_day)}'),
            if (entries.isEmpty)
              const EmptyStateView(
                icon: Icons.event_note_rounded,
                title: 'Nothing logged',
                message: 'Use the + button to add a reading, meal or workout.',
              )
            else
              ...entries.map((e) => e.$2),
          ],
        ),
      ),
    );
  }
}

class _TrackerGrid extends StatelessWidget {
  const _TrackerGrid();

  @override
  Widget build(BuildContext context) {
    const items = [
      (Icons.bloodtype_outlined, 'Glucose', Routes.glucose, AppColors.danger),
      (Icons.restaurant_rounded, 'Meals', Routes.meals, AppColors.warning),
      (Icons.directions_run_rounded, 'Exercise', Routes.exercise, AppColors.success),
      (Icons.water_drop_outlined, 'Water', Routes.water, AppColors.water),
      (Icons.medication_outlined, 'Medications', Routes.medications, AppColors.primary),
      (Icons.assignment_outlined, 'Risk test', Routes.riskIntro, AppColors.info),
    ];
    return GridView.count(
      crossAxisCount: 3,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      mainAxisSpacing: AppSpacing.md,
      crossAxisSpacing: AppSpacing.md,
      childAspectRatio: 1.05,
      children: [
        for (final (icon, label, route, color) in items)
          AppCard(
            padding: const EdgeInsets.all(AppSpacing.sm),
            onTap: () => context.push(route),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                CircleAvatar(
                  radius: 22,
                  backgroundColor: color.withValues(alpha: 0.12),
                  child: Icon(icon, color: color),
                ),
                const SizedBox(height: AppSpacing.sm),
                Text(label,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: context.palette.textPrimary,
                        fontWeight: FontWeight.w600)),
              ],
            ),
          ),
      ],
    );
  }
}
