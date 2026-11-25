import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';

import '../../../core/router/routes.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/utils/format.dart';
import '../../../core/utils/json.dart';
import '../../../core/widgets/app_card.dart';
import '../../../core/widgets/async_view.dart';
import '../../../core/widgets/charts.dart';
import '../../../core/widgets/form_widgets.dart';
import '../../../core/widgets/state_views.dart';
import '../data/tracking_models.dart';
import '../data/tracking_repository.dart';
import 'log_tile.dart';

DateTime _today() {
  final n = DateTime.now();
  return DateTime(n.year, n.month, n.day);
}

/// Figma "07 · Meal Tracking": daily kcal + macros vs goals, meal list.
class MealsScreen extends ConsumerWidget {
  const MealsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final day = _today();
    final meals = ref.watch(mealsForDayProvider(day));
    const goals = NutritionGoals();

    return Scaffold(
      appBar: AppBar(
        title: const Text('Meals'),
        actions: [
          IconButton(
            tooltip: 'Scan a meal',
            icon: const Icon(Icons.photo_camera_outlined),
            onPressed: () => context.push(Routes.visionAi),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => context.push(Routes.addMeal),
        icon: const Icon(Icons.add_rounded),
        label: const Text('Add meal'),
      ),
      body: AsyncView(
        value: meals,
        onRetry: () => ref.invalidate(mealsForDayProvider(day)),
        data: (list) {
          double sum(double Function(Meal) f) =>
              list.fold<double>(0, (s, m) => s + f(m));
          final kcal = sum((m) => m.calories);
          return ListView(
            padding:
                const EdgeInsets.fromLTRB(AppSpacing.page, 0, AppSpacing.page, 100),
            children: [
              AppCard(
                child: Row(
                  children: [
                    ProgressRing(
                      value: kcal / goals.calories,
                      color: AppColors.warning,
                      center: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(fmtNum(kcal),
                              style: Theme.of(context).textTheme.titleLarge),
                          Text('of ${fmtNum(goals.calories)} kcal',
                              style: Theme.of(context).textTheme.bodySmall),
                        ],
                      ),
                    ),
                    const SizedBox(width: AppSpacing.xl),
                    Expanded(
                      child: Column(
                        children: [
                          GoalBar(
                              label: 'Carbs',
                              value: sum((m) => m.carbs),
                              goal: goals.carbs,
                              unit: 'g',
                              color: AppColors.warning),
                          const SizedBox(height: AppSpacing.md),
                          GoalBar(
                              label: 'Protein',
                              value: sum((m) => m.protein),
                              goal: goals.protein,
                              unit: 'g',
                              color: AppColors.info),
                          const SizedBox(height: AppSpacing.md),
                          GoalBar(
                              label: 'Fat',
                              value: sum((m) => m.fat),
                              goal: goals.fat,
                              unit: 'g',
                              color: AppColors.danger),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: AppSpacing.md),
              AppCard(
                onTap: () => context.push(Routes.visionAi),
                color: context.palette.primarySoft,
                child: const Row(
                  children: [
                    Icon(Icons.auto_awesome_rounded, color: AppColors.primary),
                    SizedBox(width: AppSpacing.md),
                    Expanded(
                      child: Text('Snap a photo — AI estimates carbs and calories'),
                    ),
                    Icon(Icons.chevron_right_rounded),
                  ],
                ),
              ),
              const SizedBox(height: AppSpacing.xl),
              const SectionHeader("Today's meals"),
              if (list.isEmpty)
                const EmptyStateView(
                  icon: Icons.restaurant_rounded,
                  title: 'No meals logged',
                  message: 'Log what you eat to see how it affects your glucose.',
                )
              else
                for (final m in list)
                  LogTile(
                    icon: Icons.restaurant_rounded,
                    color: AppColors.warning,
                    title: m.name,
                    subtitle: '${m.type.label} · ${fmtNum(m.calories)} kcal',
                    trailing: '${fmtNum(m.carbs)} g',
                    at: m.loggedAt,
                  ),
            ],
          );
        },
      ),
    );
  }
}

/// Values pre-filled into Add Meal from a Vision AI result.
class MealDraft {
  const MealDraft({this.name, this.carbs, this.calories, this.protein, this.fat});
  final String? name;
  final double? carbs, calories, protein, fat;
}

/// Figma "18 · Add Meal".
class AddMealScreen extends ConsumerStatefulWidget {
  const AddMealScreen({super.key, this.draft});
  final MealDraft? draft;

  @override
  ConsumerState<AddMealScreen> createState() => _AddMealScreenState();
}

class _AddMealScreenState extends ConsumerState<AddMealScreen> {
  final _form = GlobalKey<FormState>();
  late final _name = TextEditingController(text: widget.draft?.name);
  late final _carbs = TextEditingController(text: _n(widget.draft?.carbs));
  late final _kcal = TextEditingController(text: _n(widget.draft?.calories));
  late final _protein = TextEditingController(text: _n(widget.draft?.protein));
  late final _fat = TextEditingController(text: _n(widget.draft?.fat));
  MealType _type = _guessType();
  DateTime _at = DateTime.now();
  bool _busy = false;

  static String? _n(double? v) => v == null ? null : fmtNum(v);

  static MealType _guessType() {
    final h = DateTime.now().hour;
    if (h < 11) return MealType.breakfast;
    if (h < 16) return MealType.lunch;
    if (h < 21) return MealType.dinner;
    return MealType.snack;
  }

  @override
  void dispose() {
    for (final c in [_name, _carbs, _kcal, _protein, _fat]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    if (!_form.currentState!.validate()) return;
    setState(() => _busy = true);
    try {
      await ref.read(trackingRepositoryProvider).addMeal(
            type: _type,
            name: _name.text.trim(),
            carbs: double.parse(_carbs.text.trim()),
            calories: double.tryParse(_kcal.text.trim()),
            protein: double.tryParse(_protein.text.trim()),
            fat: double.tryParse(_fat.text.trim()),
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

  Widget _numField(TextEditingController c, String hint, {bool required = false}) =>
      TextFormField(
        controller: c,
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        decoration: InputDecoration(hintText: hint),
        validator: required
            ? (v) => requiredNumber(v, max: 1000)
            : (v) => (v ?? '').trim().isEmpty ? null : requiredNumber(v, max: 5000),
      );

  @override
  Widget build(BuildContext context) {
    return Form(
      key: _form,
      child: FormScaffold(
        title: 'Add Meal',
        submitLabel: 'Save meal',
        busy: _busy,
        onSubmit: _save,
        children: [
          OutlinedButton.icon(
            onPressed: () => context.pushReplacement(Routes.visionAi),
            icon: const Icon(Icons.photo_camera_outlined),
            label: const Text('Scan with camera'),
          ),
          const FieldLabel('Meal type'),
          ChoiceChips<MealType>(
            options: MealType.values,
            selected: _type,
            label: (m) => m.label,
            onSelected: (m) => setState(() => _type = m),
          ),
          const FieldLabel('Food'),
          TextFormField(
            controller: _name,
            textCapitalization: TextCapitalization.sentences,
            decoration: const InputDecoration(hintText: 'e.g. Oatmeal with berries'),
            validator: (v) => (v ?? '').trim().isEmpty ? 'Enter a food name' : null,
          ),
          const FieldLabel('Nutrition'),
          Row(
            children: [
              Expanded(child: _numField(_carbs, 'Carbs (g)', required: true)),
              const SizedBox(width: AppSpacing.md),
              Expanded(child: _numField(_kcal, 'Calories')),
            ],
          ),
          const SizedBox(height: AppSpacing.md),
          Row(
            children: [
              Expanded(child: _numField(_protein, 'Protein (g)')),
              const SizedBox(width: AppSpacing.md),
              Expanded(child: _numField(_fat, 'Fat (g)')),
            ],
          ),
          const FieldLabel('Time'),
          DateTimeField(value: _at, onChanged: (d) => setState(() => _at = d)),
        ],
      ),
    );
  }
}

/// Figma "11 · Vision AI": photo → food, confidence, nutrition → add to log.
class VisionAiScreen extends ConsumerStatefulWidget {
  const VisionAiScreen({super.key});

  @override
  ConsumerState<VisionAiScreen> createState() => _VisionAiScreenState();
}

class _VisionAiScreenState extends ConsumerState<VisionAiScreen> {
  Uint8List? _photo;
  Json? _result;
  bool _busy = false;

  Future<void> _pick(ImageSource source) async {
    final photo = await ImagePicker()
        .pickImage(source: source, maxWidth: 1280, imageQuality: 85);
    if (photo == null) return;
    final bytes = await photo.readAsBytes();
    setState(() {
      _photo = bytes;
      _result = null;
      _busy = true;
    });
    try {
      final res = await ref
          .read(trackingRepositoryProvider)
          .analyzeMealPhoto(bytes, filename: photo.name);
      if (mounted) setState(() => _result = res);
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final r = _result;
    return Scaffold(
      appBar: AppBar(title: const Text('Scan Meal')),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.page),
        children: [
          AspectRatio(
            aspectRatio: 1,
            child: ClipRRect(
              borderRadius: BorderRadius.circular(AppRadius.lg),
              child: _photo == null
                  ? Container(
                      color: context.palette.primarySoft,
                      child: const Icon(Icons.photo_camera_outlined,
                          size: 64, color: AppColors.primary),
                    )
                  : Image.memory(_photo!, fit: BoxFit.cover),
            ),
          ),
          const SizedBox(height: AppSpacing.lg),
          Row(
            children: [
              Expanded(
                child: FilledButton.icon(
                  onPressed: _busy ? null : () => _pick(ImageSource.camera),
                  icon: const Icon(Icons.photo_camera_rounded),
                  label: const Text('Camera'),
                ),
              ),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: _busy ? null : () => _pick(ImageSource.gallery),
                  icon: const Icon(Icons.photo_library_outlined),
                  label: const Text('Gallery'),
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.xl),
          if (_busy)
            const Center(
              child: Column(
                children: [
                  CircularProgressIndicator(),
                  SizedBox(height: AppSpacing.md),
                  Text('Analysing your meal…'),
                ],
              ),
            ),
          if (r != null) ...[
            AppCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(jStr(r, ['food', 'food_name', 'name']) ?? 'Meal',
                            style: t.titleLarge),
                      ),
                      if (jNum(r, ['confidence']) != null)
                        Chip(
                          label: Text(
                              '${fmtNum(_pct(jNum(r, ['confidence'])!))}% sure'),
                        ),
                    ],
                  ),
                  const SizedBox(height: AppSpacing.md),
                  Wrap(
                    spacing: AppSpacing.lg,
                    runSpacing: AppSpacing.sm,
                    children: [
                      _Nutrient('Carbs', jNum(r, ['carbs_g', 'carbs', 'carbs_grams']), 'g'),
                      _Nutrient('Calories', jNum(r, ['calories', 'kcal']), 'kcal'),
                      _Nutrient('Protein', jNum(r, ['protein_g', 'protein']), 'g'),
                      _Nutrient('Fat', jNum(r, ['fat_g', 'fat']), 'g'),
                      _Nutrient('Glycemic load', jNum(r, ['glycemic_load']), ''),
                    ],
                  ),
                  if (jStr(r, ['advice', 'notes']) case final advice?) ...[
                    const SizedBox(height: AppSpacing.md),
                    Text(advice, style: t.bodySmall),
                  ],
                ],
              ),
            ),
            const SizedBox(height: AppSpacing.lg),
            FilledButton(
              onPressed: () => context.pushReplacement(
                Routes.addMeal,
                extra: MealDraft(
                  name: jStr(r, ['food', 'food_name', 'name']),
                  carbs: jNum(r, ['carbs_g', 'carbs', 'carbs_grams']),
                  calories: jNum(r, ['calories', 'kcal']),
                  protein: jNum(r, ['protein_g', 'protein']),
                  fat: jNum(r, ['fat_g', 'fat']),
                ),
              ),
              child: const Text('Add to log'),
            ),
          ],
        ],
      ),
    );
  }

  static double _pct(double v) => v <= 1 ? v * 100 : v;
}

class _Nutrient extends StatelessWidget {
  const _Nutrient(this.label, this.value, this.unit);
  final String label;
  final double? value;
  final String unit;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('${fmtNum(value)} $unit'.trim(),
              style: Theme.of(context).textTheme.titleMedium),
          Text(label, style: Theme.of(context).textTheme.bodySmall),
        ],
      );
}
