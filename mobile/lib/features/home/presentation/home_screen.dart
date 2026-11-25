import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/network/api_client.dart';
import '../../../core/router/routes.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/utils/format.dart';
import '../../../core/widgets/app_card.dart';
import '../../../core/widgets/state_views.dart';
import '../../notifications/data/notifications_repository.dart';
import '../../profile/data/profile_repository.dart';
import '../../risk/data/risk_repository.dart';
import '../../risk/presentation/risk_widgets.dart';
import '../../tracking/data/tracking_models.dart';
import '../../tracking/data/tracking_repository.dart';
import '../../tracking/presentation/glucose_chart.dart';

/// Figma "Home Dashboard" (+ DARK · Home, 25 · Loading Skeleton,
/// 24 · Error State).
class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  Future<void> _refresh(WidgetRef ref) async {
    ref
      ..invalidate(glucoseReadingsProvider)
      ..invalidate(waterTodayProvider)
      ..invalidate(workoutsProvider)
      ..invalidate(medicationsProvider)
      ..invalidate(latestRiskProvider)
      ..invalidate(notificationsProvider)
      ..invalidate(profileProvider);
    await ref.read(glucoseReadingsProvider.future);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final glucose = ref.watch(glucoseReadingsProvider);

    // The glucose list is the critical call: if it fails, show the full
    // error state (also covers "no connection").
    if (glucose.hasError && !glucose.hasValue) {
      return Scaffold(
        body: SafeArea(
          child: ErrorStateView(
            message: ApiException.from(glucose.error!).message,
            onRetry: () => _refresh(ref),
          ),
        ),
      );
    }
    if (!glucose.hasValue) {
      return const Scaffold(body: SafeArea(child: SkeletonList(count: 5, height: 120)));
    }

    return Scaffold(
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: () => _refresh(ref),
          child: ListView(
            padding: const EdgeInsets.fromLTRB(
                AppSpacing.page, AppSpacing.lg, AppSpacing.page, 100),
            children: [
              const _Header(),
              const SizedBox(height: AppSpacing.xl),
              _GlucoseCard(readings: glucose.value!),
              const SizedBox(height: AppSpacing.xl),
              const _QuickActions(),
              const SizedBox(height: AppSpacing.xl),
              const SectionHeader('Today'),
              const _TodaySummary(),
              const SizedBox(height: AppSpacing.xl),
              const _Reminders(),
              const _RiskCard(),
            ],
          ),
        ),
      ),
    );
  }
}

class _Header extends ConsumerWidget {
  const _Header();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = Theme.of(context).textTheme;
    final profile = ref.watch(profileProvider).value;
    final unread = ref.watch(unreadCountProvider);
    return Row(
      children: [
        CircleAvatar(
          radius: 24,
          backgroundColor: context.palette.primarySoft,
          child: Text(profile?.initials ?? '',
              style: const TextStyle(
                  color: AppColors.primary, fontWeight: FontWeight.w700)),
        ),
        const SizedBox(width: AppSpacing.md),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(greeting(), style: t.bodySmall),
              Text(profile?.firstName ?? 'there', style: t.titleLarge),
            ],
          ),
        ),
        IconButton.outlined(
          onPressed: () => context.push(Routes.notifications),
          icon: Badge(
            isLabelVisible: unread > 0,
            label: Text('$unread'),
            child: const Icon(Icons.notifications_none_rounded),
          ),
        ),
      ],
    );
  }
}

class _GlucoseCard extends StatelessWidget {
  const _GlucoseCard({required this.readings});
  final List<GlucoseReading> readings;

  @override
  Widget build(BuildContext context) {
    final latest = readings.isEmpty ? null : readings.first;
    return Container(
      padding: const EdgeInsets.all(AppSpacing.xl),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: [AppColors.primary, AppColors.primaryDark],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(AppRadius.lg),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Text('Latest glucose',
                  style: TextStyle(color: Colors.white70)),
              const Spacer(),
              if (latest != null)
                Text('${relativeDay(latest.recordedAt)}, ${fmtTime(latest.recordedAt)}',
                    style: const TextStyle(color: Colors.white70, fontSize: 12)),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          if (latest == null)
            const Text('No readings yet',
                style: TextStyle(
                    color: Colors.white, fontSize: 22, fontWeight: FontWeight.w700))
          else
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(fmtNum(latest.value),
                    style: const TextStyle(
                        color: Colors.white,
                        fontSize: 40,
                        fontWeight: FontWeight.w700,
                        height: 1)),
                const SizedBox(width: AppSpacing.sm),
                const Padding(
                  padding: EdgeInsets.only(bottom: 4),
                  child: Text('mg/dL', style: TextStyle(color: Colors.white70)),
                ),
                const Spacer(),
                _BandPill(latest.band),
              ],
            ),
          const SizedBox(height: AppSpacing.md),
          // Sparkline tinted white on the purple card.
          ColorFiltered(
            colorFilter: const ColorFilter.mode(Colors.white, BlendMode.srcIn),
            child: GlucoseChart(readings: readings, compact: true, height: 56),
          ),
        ],
      ),
    );
  }
}

class _BandPill extends StatelessWidget {
  const _BandPill(this.band);
  final GlucoseBand band;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: 0.2),
          borderRadius: BorderRadius.circular(AppRadius.pill),
        ),
        child: Text(
          switch (band) {
            GlucoseBand.low => 'Low',
            GlucoseBand.inRange => 'In range',
            GlucoseBand.high => 'High',
          },
          style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600),
        ),
      );
}

class _QuickActions extends StatelessWidget {
  const _QuickActions();

  @override
  Widget build(BuildContext context) {
    const actions = [
      (Icons.bloodtype_outlined, 'Glucose', Routes.addGlucose, AppColors.danger),
      (Icons.restaurant_rounded, 'Meal', Routes.addMeal, AppColors.warning),
      (Icons.water_drop_outlined, 'Water', Routes.addWater, AppColors.water),
      (Icons.insights_rounded, 'Reports', Routes.analytics, AppColors.primary),
    ];
    return Row(
      children: [
        for (final (icon, label, route, color) in actions)
          Expanded(
            child: InkWell(
              borderRadius: BorderRadius.circular(AppRadius.md),
              onTap: () => context.push(route),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
                child: Column(
                  children: [
                    Container(
                      width: 52,
                      height: 52,
                      decoration: BoxDecoration(
                        color: color.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(AppRadius.md),
                      ),
                      child: Icon(icon, color: color),
                    ),
                    const SizedBox(height: AppSpacing.xs),
                    Text(label, style: Theme.of(context).textTheme.bodySmall),
                  ],
                ),
              ),
            ),
          ),
      ],
    );
  }
}

class _TodaySummary extends ConsumerWidget {
  const _TodaySummary();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final water = ref.watch(waterTodayProvider).value ?? const [];
    final workouts = ref.watch(workoutsProvider).value ?? const [];
    final meds = ref.watch(medicationsProvider).value ?? const [];

    final now = DateTime.now();
    final waterMl = water
        .where((w) => isSameDay(w.loggedAt, now))
        .fold<double>(0, (s, w) => s + w.ml);
    final minutes = workouts
        .where((w) => isSameDay(w.loggedAt, now))
        .fold<double>(0, (s, w) => s + w.minutes);
    final dosesDue = meds.fold<int>(0, (s, m) => s + m.timesPerDay);
    final dosesTaken = meds.fold<int>(0, (s, m) => s + m.takenToday.length);

    return Row(
      children: [
        Expanded(
          child: StatTile(
            icon: Icons.water_drop_outlined,
            value: '${(waterMl / 1000).toStringAsFixed(1)} L',
            label: 'of ${(waterGoalMl / 1000).toStringAsFixed(1)} L',
            color: AppColors.water,
            onTap: () => context.go(Routes.water),
          ),
        ),
        const SizedBox(width: AppSpacing.md),
        Expanded(
          child: StatTile(
            icon: Icons.directions_run_rounded,
            value: '${fmtNum(minutes)} min',
            label: 'of ${fmtNum(exerciseGoalMinutes)} min',
            color: AppColors.success,
            onTap: () => context.go(Routes.exercise),
          ),
        ),
        const SizedBox(width: AppSpacing.md),
        Expanded(
          child: StatTile(
            icon: Icons.medication_outlined,
            value: '$dosesTaken/$dosesDue',
            label: 'doses',
            onTap: () => context.go(Routes.medications),
          ),
        ),
      ],
    );
  }
}

/// Upcoming medication doses not yet taken today.
class _Reminders extends ConsumerWidget {
  const _Reminders();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final meds = ref.watch(medicationsProvider).value ?? const [];
    final due = [
      for (final m in meds)
        for (final t in m.times)
          if (!m.takenToday.contains(t)) (m, t),
    ]..sort((a, b) => a.$2.compareTo(b.$2));
    if (due.isEmpty) return const SizedBox.shrink();

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.xl),
      child: Column(
        children: [
          SectionHeader('Reminders',
              action: 'See all', onAction: () => context.go(Routes.medications)),
          for (final (m, time) in due.take(3))
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.sm),
              child: AppCard(
                padding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.lg, vertical: AppSpacing.md),
                child: Row(
                  children: [
                    const Icon(Icons.alarm_rounded, color: AppColors.primary),
                    const SizedBox(width: AppSpacing.md),
                    Expanded(child: Text('${m.name} ${m.dose}')),
                    Text(time, style: Theme.of(context).textTheme.bodySmall),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _RiskCard extends ConsumerWidget {
  const _RiskCard();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final latest = ref.watch(latestRiskProvider).value;
    final t = Theme.of(context).textTheme;
    return AppCard(
      onTap: () => context.push(Routes.riskIntro),
      child: Row(
        children: [
          if (latest != null)
            RiskBadge(band: latest.band, score: latest.score)
          else
            CircleAvatar(
              radius: 26,
              backgroundColor: context.palette.primarySoft,
              child: const Icon(Icons.assignment_outlined, color: AppColors.primary),
            ),
          const SizedBox(width: AppSpacing.lg),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Diabetes risk', style: t.titleMedium),
                Text(
                  latest == null
                      ? 'Take the 1-minute CDC risk test'
                      : '${latest.band.label} · ${relativeDay(latest.at)}',
                  style: t.bodySmall,
                ),
              ],
            ),
          ),
          const Icon(Icons.chevron_right_rounded),
        ],
      ),
    );
  }
}
