import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/router/routes.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/widgets/app_card.dart';
import '../../../core/widgets/async_view.dart';
import '../../../core/widgets/charts.dart';
import '../../../core/widgets/form_widgets.dart';
import '../../../core/widgets/state_views.dart';
import '../data/tracking_models.dart';
import '../data/tracking_repository.dart';

/// Figma "10 · Medication": weekly adherence, today's schedule with
/// checkboxes, my medications.
class MedicationsScreen extends ConsumerWidget {
  const MedicationsScreen({super.key});

  Future<void> _take(BuildContext context, WidgetRef ref, Medication m, String time) async {
    try {
      await ref.read(trackingRepositoryProvider).markDoseTaken(m.id, time);
      ref
        ..invalidate(medicationsProvider)
        ..invalidate(adherenceProvider);
    } catch (e) {
      if (context.mounted) showError(context, e);
    }
  }

  Future<void> _delete(BuildContext context, WidgetRef ref, Medication m) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (d) => AlertDialog(
        title: Text('Remove ${m.name}?'),
        content: const Text('Its schedule and reminders will be removed.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d, false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(d, true), child: const Text('Remove')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(trackingRepositoryProvider).deleteMedication(m.id);
      ref.invalidate(medicationsProvider);
    } catch (e) {
      if (context.mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final adherence = ref.watch(adherenceProvider).value;
    return Scaffold(
      appBar: AppBar(title: const Text('Medications')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => context.push(Routes.addMedication),
        icon: const Icon(Icons.add_rounded),
        label: const Text('Add medication'),
      ),
      body: AsyncView(
        value: ref.watch(medicationsProvider),
        onRetry: () => ref.invalidate(medicationsProvider),
        data: (meds) {
          if (meds.isEmpty) {
            return EmptyStateView(
              icon: Icons.medication_outlined,
              title: 'No medications',
              message: 'Add your medications to get reminders and track doses.',
              actionLabel: 'Add medication',
              onAction: () => context.push(Routes.addMedication),
            );
          }
          final schedule = [
            for (final m in meds)
              for (final t in m.times) (m, t),
          ]..sort((a, b) => a.$2.compareTo(b.$2));
          final week = adherence ?? WeekSeries.empty();

          return ListView(
            padding:
                const EdgeInsets.fromLTRB(AppSpacing.page, 0, AppSpacing.page, 100),
            children: [
              AppCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Weekly adherence',
                        style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: AppSpacing.md),
                    WeekBars(
                      days: week.days,
                      values: week.values,
                      goal: 1,
                      height: 110,
                    ),
                  ],
                ),
              ),
              const SizedBox(height: AppSpacing.xl),
              const SectionHeader("Today's schedule"),
              for (final (m, time) in schedule)
                Padding(
                  padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                  child: AppCard(
                    padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm),
                    child: CheckboxListTile(
                      value: m.takenToday.contains(time),
                      onChanged: m.takenToday.contains(time)
                          ? null
                          : (_) => _take(context, ref, m, time),
                      title: Text('${m.name} ${m.dose}'),
                      subtitle: Text('$time · ${m.form.label}'),
                      activeColor: AppColors.success,
                    ),
                  ),
                ),
              const SizedBox(height: AppSpacing.xl),
              const SectionHeader('My medications'),
              for (final m in meds)
                Padding(
                  padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                  child: AppCard(
                    child: Row(
                      children: [
                        const Icon(Icons.medication_rounded, color: AppColors.primary),
                        const SizedBox(width: AppSpacing.md),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(m.name,
                                  style: Theme.of(context).textTheme.titleMedium),
                              Text(
                                '${m.dose} · ${m.timesPerDay}× daily · ${m.times.join(', ')}',
                                style: Theme.of(context).textTheme.bodySmall,
                              ),
                            ],
                          ),
                        ),
                        IconButton(
                          tooltip: 'Remove',
                          icon: const Icon(Icons.delete_outline_rounded),
                          onPressed: () => _delete(context, ref, m),
                        ),
                      ],
                    ),
                  ),
                ),
            ],
          );
        },
      ),
    );
  }
}

/// Figma "21 · Add Medication".
class AddMedicationScreen extends ConsumerStatefulWidget {
  const AddMedicationScreen({super.key});

  @override
  ConsumerState<AddMedicationScreen> createState() => _AddMedicationScreenState();
}

class _AddMedicationScreenState extends ConsumerState<AddMedicationScreen> {
  static const _defaultTimes = {
    1: ['08:00'],
    2: ['08:00', '20:00'],
    3: ['08:00', '14:00', '20:00'],
  };

  final _form = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _dose = TextEditingController();
  MedForm _formType = MedForm.tablet;
  int _perDay = 1;
  List<String> _times = ['08:00'];
  bool _busy = false;

  @override
  void dispose() {
    _name.dispose();
    _dose.dispose();
    super.dispose();
  }

  Future<void> _pickTime(int i) async {
    final parts = _times[i].split(':');
    final t = await showTimePicker(
      context: context,
      initialTime: TimeOfDay(hour: int.parse(parts[0]), minute: int.parse(parts[1])),
    );
    if (t == null) return;
    setState(() => _times[i] =
        '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}');
  }

  Future<void> _save() async {
    if (!_form.currentState!.validate()) return;
    setState(() => _busy = true);
    try {
      await ref.read(trackingRepositoryProvider).addMedication(
            name: _name.text.trim(),
            dose: _dose.text.trim(),
            form: _formType,
            times: _times,
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
          title: 'Add Medication',
          submitLabel: 'Save medication',
          busy: _busy,
          onSubmit: _save,
          children: [
            const FieldLabel('Name'),
            TextFormField(
              controller: _name,
              textCapitalization: TextCapitalization.words,
              decoration: const InputDecoration(hintText: 'e.g. Metformin'),
              validator: (v) => (v ?? '').trim().isEmpty ? 'Enter a name' : null,
            ),
            const FieldLabel('Dose'),
            TextFormField(
              controller: _dose,
              decoration: const InputDecoration(hintText: 'e.g. 500 mg'),
              validator: (v) => (v ?? '').trim().isEmpty ? 'Enter the dose' : null,
            ),
            const FieldLabel('Form'),
            ChoiceChips<MedForm>(
              options: MedForm.values,
              selected: _formType,
              label: (f) => f.label,
              onSelected: (f) => setState(() => _formType = f),
            ),
            const FieldLabel('Times per day'),
            ChoiceChips<int>(
              options: const [1, 2, 3],
              selected: _perDay,
              label: (n) => '$n×',
              onSelected: (n) => setState(() {
                _perDay = n;
                _times = [..._defaultTimes[n]!];
              }),
            ),
            const FieldLabel('Times'),
            Wrap(
              spacing: AppSpacing.sm,
              children: [
                for (var i = 0; i < _times.length; i++)
                  ActionChip(
                    avatar: const Icon(Icons.schedule_rounded, size: 18),
                    label: Text(_times[i]),
                    onPressed: () => _pickTime(i),
                  ),
              ],
            ),
            const SizedBox(height: AppSpacing.md),
            Text(
              'Reminders follow "Medication reminders" in Settings.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
      );
}
