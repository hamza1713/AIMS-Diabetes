import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/router/routes.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/utils/format.dart';
import '../../../core/widgets/app_card.dart';
import '../../../core/widgets/async_view.dart';
import '../../../core/widgets/charts.dart';
import '../../../core/widgets/form_widgets.dart';
import '../../../core/widgets/state_views.dart';
import '../data/tracking_models.dart';
import '../data/tracking_repository.dart';
import 'log_tile.dart';

/// Figma "08 · Exercise Tracking": active minutes vs goal, week bars, today.
class ExerciseScreen extends ConsumerWidget {
  const ExerciseScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      appBar: AppBar(title: const Text('Exercise')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => context.push(Routes.logWorkout),
        icon: const Icon(Icons.add_rounded),
        label: const Text('Log workout'),
      ),
      body: AsyncView(
        value: ref.watch(workoutsProvider),
        onRetry: () => ref.invalidate(workoutsProvider),
        data: (list) {
          final week = WeekSeries.fromDated(list, (w) => w.loggedAt, (w) => w.minutes);
          final todayMin = week.values.last;
          final today = list.where((w) => isSameDay(w.loggedAt, DateTime.now()));
          return ListView(
            padding:
                const EdgeInsets.fromLTRB(AppSpacing.page, 0, AppSpacing.page, 100),
            children: [
              AppCard(
                child: Row(
                  children: [
                    ProgressRing(
                      value: todayMin / exerciseGoalMinutes,
                      color: AppColors.success,
                      center: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(fmtNum(todayMin),
                              style: Theme.of(context).textTheme.titleLarge),
                          Text('of ${fmtNum(exerciseGoalMinutes)} min',
                              style: Theme.of(context).textTheme.bodySmall),
                        ],
                      ),
                    ),
                    const SizedBox(width: AppSpacing.xl),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('Active minutes',
                              style: Theme.of(context).textTheme.titleMedium),
                          Text(
                            '${fmtNum(week.values.reduce((a, b) => a + b))} min this week · '
                            '${week.values.where((v) => v > 0).length}/7 active days',
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: AppSpacing.md),
              AppCard(
                child: WeekBars(
                  days: week.days,
                  values: week.values,
                  goal: exerciseGoalMinutes,
                  color: AppColors.success,
                ),
              ),
              const SizedBox(height: AppSpacing.xl),
              const SectionHeader('Today'),
              if (today.isEmpty)
                const EmptyStateView(
                  icon: Icons.directions_run_rounded,
                  title: 'No activity yet',
                  message: 'A 30-minute walk helps keep glucose steady.',
                )
              else
                for (final w in today)
                  LogTile(
                    icon: Icons.directions_run_rounded,
                    color: AppColors.success,
                    title: w.activity,
                    subtitle: '${w.intensity.label} · ${fmtNum(w.calories)} kcal',
                    trailing: '${fmtNum(w.minutes)} min',
                    at: w.loggedAt,
                  ),
            ],
          );
        },
      ),
    );
  }
}

/// Figma "19 · Log Workout".
class LogWorkoutScreen extends ConsumerStatefulWidget {
  const LogWorkoutScreen({super.key});

  @override
  ConsumerState<LogWorkoutScreen> createState() => _LogWorkoutScreenState();
}

class _LogWorkoutScreenState extends ConsumerState<LogWorkoutScreen> {
  static const _activities = [
    'Walking', 'Running', 'Cycling', 'Swimming', 'Yoga', 'Strength', 'Other',
  ];

  final _form = GlobalKey<FormState>();
  final _minutes = TextEditingController(text: '30');
  final _kcal = TextEditingController();
  String _activity = _activities.first;
  Intensity _intensity = Intensity.moderate;
  DateTime _at = DateTime.now();
  bool _busy = false;

  @override
  void dispose() {
    _minutes.dispose();
    _kcal.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (!_form.currentState!.validate()) return;
    setState(() => _busy = true);
    try {
      await ref.read(trackingRepositoryProvider).addWorkout(
            activity: _activity,
            minutes: double.parse(_minutes.text.trim()),
            calories: double.tryParse(_kcal.text.trim()),
            intensity: _intensity,
            at: _at,
          );
      invalidateTracking(ref);
      if (mounted) context.pop();
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Form(
        key: _form,
        child: FormScaffold(
          title: 'Log Workout',
          submitLabel: 'Save workout',
          busy: _busy,
          onSubmit: _save,
          children: [
            const FieldLabel('Activity'),
            ChoiceChips<String>(
              options: _activities,
              selected: _activity,
              label: (a) => a,
              onSelected: (a) => setState(() => _activity = a),
            ),
            const FieldLabel('Duration & calories'),
            Row(
              children: [
                Expanded(
                  child: TextFormField(
                    controller: _minutes,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                        hintText: 'Minutes', suffixText: 'min'),
                    validator: (v) => requiredNumber(v, min: 1, max: 600),
                  ),
                ),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: TextFormField(
                    controller: _kcal,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                        hintText: 'Calories', suffixText: 'kcal'),
                  ),
                ),
              ],
            ),
            const FieldLabel('Intensity'),
            ChoiceChips<Intensity>(
              options: Intensity.values,
              selected: _intensity,
              label: (i) => i.label,
              onSelected: (i) => setState(() => _intensity = i),
            ),
            const FieldLabel('Time'),
            DateTimeField(value: _at, onChanged: (d) => setState(() => _at = d)),
          ],
        ),
      );
}

/// Figma "09 · Water Intake": progress vs 2.0 L goal, quick add, today's logs.
class WaterScreen extends ConsumerWidget {
  const WaterScreen({super.key});

  Future<void> _quickAdd(BuildContext context, WidgetRef ref, double ml) async {
    try {
      await ref
          .read(trackingRepositoryProvider)
          .addWater(ml: ml, at: DateTime.now());
      invalidateTracking(ref);
    } catch (e) {
      if (context.mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      appBar: AppBar(title: const Text('Water Intake')),
      body: AsyncView(
        value: ref.watch(waterTodayProvider),
        onRetry: () => ref.invalidate(waterTodayProvider),
        data: (list) {
          final today = list.where((w) => isSameDay(w.loggedAt, DateTime.now()));
          final total = today.fold<double>(0, (s, w) => s + w.ml);
          return ListView(
            padding:
                const EdgeInsets.fromLTRB(AppSpacing.page, 0, AppSpacing.page, 100),
            children: [
              AppCard(
                child: Column(
                  children: [
                    ProgressRing(
                      size: 170,
                      stroke: 14,
                      value: total / waterGoalMl,
                      color: AppColors.water,
                      center: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const Icon(Icons.water_drop_rounded,
                              color: AppColors.water),
                          Text('${(total / 1000).toStringAsFixed(2)} L',
                              style: Theme.of(context).textTheme.headlineMedium),
                          Text('of ${(waterGoalMl / 1000).toStringAsFixed(1)} L',
                              style: Theme.of(context).textTheme.bodySmall),
                        ],
                      ),
                    ),
                    const SizedBox(height: AppSpacing.xl),
                    Row(
                      children: [
                        for (final ml in [250.0, 500.0, 750.0]) ...[
                          Expanded(
                            child: OutlinedButton(
                              onPressed: () => _quickAdd(context, ref, ml),
                              child: Text('+${fmtNum(ml)} ml'),
                            ),
                          ),
                          if (ml != 750) const SizedBox(width: AppSpacing.sm),
                        ],
                      ],
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    TextButton(
                      onPressed: () => context.push(Routes.addWater),
                      child: const Text('Custom amount'),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: AppSpacing.xl),
              const SectionHeader("Today's logs"),
              if (today.isEmpty)
                const EmptyStateView(
                  icon: Icons.water_drop_outlined,
                  title: 'No water logged',
                  message: 'Staying hydrated helps your kidneys clear excess glucose.',
                )
              else
                for (final w in today)
                  LogTile(
                    icon: Icons.water_drop_outlined,
                    color: AppColors.water,
                    title: 'Water',
                    subtitle: 'Intake',
                    trailing: '${fmtNum(w.ml)} ml',
                    at: w.loggedAt,
                  ),
            ],
          );
        },
      ),
    );
  }
}

/// Figma "20 · Add Water": 250 / 500 / 750 ml or custom, time.
class AddWaterScreen extends ConsumerStatefulWidget {
  const AddWaterScreen({super.key});

  @override
  ConsumerState<AddWaterScreen> createState() => _AddWaterScreenState();
}

class _AddWaterScreenState extends ConsumerState<AddWaterScreen> {
  final _form = GlobalKey<FormState>();
  final _amount = TextEditingController(text: '250');
  DateTime _at = DateTime.now();
  bool _busy = false;

  @override
  void dispose() {
    _amount.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (!_form.currentState!.validate()) return;
    setState(() => _busy = true);
    try {
      await ref
          .read(trackingRepositoryProvider)
          .addWater(ml: double.parse(_amount.text.trim()), at: _at);
      invalidateTracking(ref);
      if (mounted) context.pop();
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Form(
        key: _form,
        child: FormScaffold(
          title: 'Add Water',
          submitLabel: 'Add water',
          busy: _busy,
          onSubmit: _save,
          children: [
            BigNumberField(
              controller: _amount,
              unit: 'ml',
              validator: (v) => requiredNumber(v, min: 10, max: 3000),
            ),
            const FieldLabel('Quick amounts'),
            ChoiceChips<String>(
              options: const ['250', '500', '750'],
              selected: _amount.text,
              label: (v) => '$v ml',
              onSelected: (v) => setState(() => _amount.text = v),
            ),
            const FieldLabel('Time'),
            DateTimeField(value: _at, onChanged: (d) => setState(() => _at = d)),
          ],
        ),
      );
}
