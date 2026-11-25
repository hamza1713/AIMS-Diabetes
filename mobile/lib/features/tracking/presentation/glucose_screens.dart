import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/router/routes.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/utils/format.dart';
import '../../../core/widgets/app_card.dart';
import '../../../core/widgets/async_view.dart';
import '../../../core/widgets/form_widgets.dart';
import '../../../core/widgets/state_views.dart';
import '../data/tracking_models.dart';
import '../data/tracking_repository.dart';
import 'glucose_chart.dart';
import 'log_tile.dart';

/// Figma "06 · Glucose Tracking" and "23 · Empty State".
class GlucoseScreen extends ConsumerWidget {
  const GlucoseScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final readings = ref.watch(glucoseReadingsProvider);
    final summary = ref.watch(glucoseSummaryProvider).value;

    return Scaffold(
      appBar: AppBar(title: const Text('Glucose')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => context.push(Routes.addGlucose),
        icon: const Icon(Icons.add_rounded),
        label: const Text('Add reading'),
      ),
      body: AsyncView(
        value: readings,
        onRetry: () => ref.invalidate(glucoseReadingsProvider),
        data: (list) {
          if (list.isEmpty) {
            return EmptyStateView(
              icon: Icons.bloodtype_outlined,
              title: 'No readings yet',
              message: 'Add your first glucose reading to see trends.',
              actionLabel: 'Add first reading',
              onAction: () => context.push(Routes.addGlucose),
            );
          }
          final latest = list.first;
          final perDay = list.length / 7;
          return RefreshIndicator(
            onRefresh: () async => invalidateTracking(ref),
            child: ListView(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.page, 0, AppSpacing.page, 100),
              children: [
                AppCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Current', style: Theme.of(context).textTheme.bodySmall),
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          Text(fmtNum(latest.value),
                              style: Theme.of(context)
                                  .textTheme
                                  .headlineMedium
                                  ?.copyWith(color: bandColor(latest.band))),
                          const SizedBox(width: AppSpacing.xs),
                          const Padding(
                            padding: EdgeInsets.only(bottom: 4),
                            child: Text('mg/dL'),
                          ),
                          const Spacer(),
                          Text('${latest.when.label} · ${fmtTime(latest.recordedAt)}',
                              style: Theme.of(context).textTheme.bodySmall),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.lg),
                      GlucoseChart(readings: list),
                      const SizedBox(height: AppSpacing.sm),
                      Text('Target ${fmtNum(glucoseTargetLow)}–${fmtNum(glucoseTargetHigh)} mg/dL',
                          style: Theme.of(context).textTheme.bodySmall),
                    ],
                  ),
                ),
                const SizedBox(height: AppSpacing.md),
                Row(
                  children: [
                    Expanded(
                      child: StatTile(
                        icon: Icons.show_chart_rounded,
                        value: fmtNum(summary?.average),
                        label: '7-day average',
                      ),
                    ),
                    const SizedBox(width: AppSpacing.md),
                    Expanded(
                      child: StatTile(
                        icon: Icons.check_circle_outline_rounded,
                        value: '${fmtNum(summary?.timeInRange)}%',
                        label: 'In range',
                        color: AppColors.success,
                      ),
                    ),
                    const SizedBox(width: AppSpacing.md),
                    Expanded(
                      child: StatTile(
                        icon: Icons.repeat_rounded,
                        value: perDay.toStringAsFixed(1),
                        label: 'Readings/day',
                        color: AppColors.info,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: AppSpacing.xl),
                const SectionHeader('Recent readings'),
                for (final r in list.take(30))
                  LogTile(
                    icon: Icons.bloodtype_outlined,
                    color: bandColor(r.band),
                    title: '${fmtNum(r.value)} mg/dL',
                    subtitle: '${relativeDay(r.recordedAt)} · ${r.when.label}',
                    trailing: switch (r.band) {
                      GlucoseBand.low => 'Low',
                      GlucoseBand.inRange => 'Normal',
                      GlucoseBand.high => 'High',
                    },
                    at: r.recordedAt,
                  ),
              ],
            ),
          );
        },
      ),
    );
  }
}

/// Figma "17 · Add Glucose Reading".
class AddGlucoseScreen extends ConsumerStatefulWidget {
  const AddGlucoseScreen({super.key});

  @override
  ConsumerState<AddGlucoseScreen> createState() => _AddGlucoseScreenState();
}

class _AddGlucoseScreenState extends ConsumerState<AddGlucoseScreen> {
  final _form = GlobalKey<FormState>();
  final _value = TextEditingController();
  final _notes = TextEditingController();
  GlucoseWhen _when = GlucoseWhen.fasting;
  DateTime _at = DateTime.now();
  bool _busy = false;

  @override
  void dispose() {
    _value.dispose();
    _notes.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (!_form.currentState!.validate()) return;
    setState(() => _busy = true);
    try {
      await ref.read(trackingRepositoryProvider).addGlucose(
            value: double.parse(_value.text.trim()),
            when: _when,
            at: _at,
            notes: _notes.text.trim(),
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
  Widget build(BuildContext context) {
    return Form(
      key: _form,
      child: FormScaffold(
        title: 'Add Reading',
        submitLabel: 'Save reading',
        busy: _busy,
        onSubmit: _save,
        children: [
          BigNumberField(
            controller: _value,
            unit: 'mg/dL',
            validator: (v) => requiredNumber(v, min: 20, max: 600),
          ),
          const FieldLabel('When'),
          ChoiceChips<GlucoseWhen>(
            options: GlucoseWhen.values,
            selected: _when,
            label: (w) => w.label,
            onSelected: (w) => setState(() => _when = w),
          ),
          const FieldLabel('Date & time'),
          DateTimeField(value: _at, onChanged: (d) => setState(() => _at = d)),
          const FieldLabel('Note'),
          TextField(
            controller: _notes,
            maxLines: 3,
            decoration: const InputDecoration(hintText: 'Optional'),
          ),
        ],
      ),
    );
  }
}
