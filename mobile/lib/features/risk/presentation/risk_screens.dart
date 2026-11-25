import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/router/routes.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/utils/format.dart';
import '../../../core/widgets/app_card.dart';
import '../../../core/widgets/charts.dart';
import '../../profile/data/profile_repository.dart';
import '../data/risk_repository.dart';
import '../domain/cdc_risk.dart';
import 'risk_widgets.dart';

/// Figma "RA0 · Risk Intro".
class RiskIntroScreen extends StatelessWidget {
  const RiskIntroScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.page),
        children: [
          Center(
            child: CircleAvatar(
              radius: 48,
              backgroundColor: context.palette.primarySoft,
              child: const Icon(Icons.assignment_turned_in_outlined,
                  size: 44, color: AppColors.primary),
            ),
          ),
          const SizedBox(height: AppSpacing.xxl),
          Text('Am I at risk for type 2 diabetes?',
              style: t.headlineMedium, textAlign: TextAlign.center),
          const SizedBox(height: AppSpacing.md),
          Text(
            'Answer 7 quick questions from the CDC prediabetes risk test.',
            style: t.bodySmall,
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: AppSpacing.xxl),
          for (final (icon, text) in const [
            (Icons.format_list_numbered_rounded, '7 questions'),
            (Icons.timer_outlined, 'About 1 minute'),
            (Icons.lock_outline_rounded, 'Private — saved only to your account'),
          ])
            ListTile(
              leading: Icon(icon, color: AppColors.primary),
              title: Text(text),
            ),
          const SizedBox(height: AppSpacing.md),
          Text(
            'This test is a screening tool, not a diagnosis. Talk to your doctor '
            'about any concerns.',
            style: t.bodySmall,
            textAlign: TextAlign.center,
          ),
        ],
      ),
      bottomNavigationBar: SafeArea(
        minimum: const EdgeInsets.all(AppSpacing.page),
        child: FilledButton(
          onPressed: () => context.pushReplacement(Routes.riskQuiz),
          child: const Text('Start test'),
        ),
      ),
    );
  }
}

/// Figma "RA1 … RA7": one question per page with a progress bar.
class RiskQuizScreen extends ConsumerStatefulWidget {
  const RiskQuizScreen({super.key});

  @override
  ConsumerState<RiskQuizScreen> createState() => _RiskQuizScreenState();
}

class _RiskQuizScreenState extends ConsumerState<RiskQuizScreen> {
  static const _total = 7;
  int _step = 0;
  bool _submitting = false;
  late CdcAnswers _a = _prefill();
  late final _height =
      TextEditingController(text: _a.heightCm == null ? '' : fmtNum(_a.heightCm));
  late final _weight =
      TextEditingController(text: _a.weightKg == null ? '' : fmtNum(_a.weightKg));

  CdcAnswers _prefill() {
    final p = ref.read(profileProvider).value;
    if (p == null) return const CdcAnswers();
    final age = p.age;
    return CdcAnswers(
      heightCm: p.heightCm,
      weightKg: p.weightKg,
      sex: switch (p.gender?.toLowerCase()) {
        'male' => Sex.male,
        'female' => Sex.female,
        _ => null,
      },
      age: age == null
          ? null
          : age >= 60
              ? AgeBand.over60
              : age >= 50
                  ? AgeBand.from50to59
                  : age >= 40
                      ? AgeBand.from40to49
                      : AgeBand.under40,
    );
  }

  @override
  void dispose() {
    _height.dispose();
    _weight.dispose();
    super.dispose();
  }

  bool get _answered => switch (_step) {
        0 => _a.age != null,
        1 => _a.sex != null,
        2 => _a.gestational != null || _a.sex == Sex.male,
        3 => _a.familyHistory != null,
        4 => _a.highBloodPressure != null,
        5 => _a.physicallyActive != null,
        _ => _a.bmi != null,
      };

  void _next() {
    if (_step == 1 && _a.sex == Sex.male) {
      _a = _a.copyWith(gestational: false);
    }
    if (_step < _total - 1) {
      setState(() => _step++);
    } else {
      _submit();
    }
  }

  void _back() {
    if (_step == 0) {
      context.pop();
    } else {
      setState(() => _step--);
    }
  }

  Future<void> _submit() async {
    setState(() => _submitting = true);
    CdcResult result;
    try {
      result = await ref.read(riskRepositoryProvider).submit(_a);
      ref.invalidate(latestRiskProvider);
    } catch (_) {
      // Offline or server error: still show the locally scored result.
      result = scoreCdc(_a);
    }
    if (mounted) context.pushReplacement(Routes.riskResult, extra: result);
  }

  Widget _yesNo(bool? value, ValueChanged<bool> onChanged) => Column(
        children: [
          _Option(label: 'Yes', selected: value == true, onTap: () => onChanged(true)),
          _Option(label: 'No', selected: value == false, onTap: () => onChanged(false)),
        ],
      );

  Widget _question() => switch (_step) {
        0 => _Question(
            title: 'How old are you?',
            child: Column(children: [
              for (final b in AgeBand.values)
                _Option(
                  label: b.label,
                  selected: _a.age == b,
                  onTap: () => setState(() => _a = _a.copyWith(age: b)),
                ),
            ]),
          ),
        1 => _Question(
            title: 'Are you a man or a woman?',
            child: Column(children: [
              for (final s in Sex.values)
                _Option(
                  label: s.label,
                  selected: _a.sex == s,
                  onTap: () => setState(() => _a = _a.copyWith(sex: s)),
                ),
            ]),
          ),
        2 => _Question(
            title: 'Have you ever been diagnosed with gestational diabetes?',
            hint: _a.sex == Sex.male ? 'Not applicable — tap Next.' : null,
            child: _a.sex == Sex.male
                ? const SizedBox.shrink()
                : _yesNo(_a.gestational,
                    (v) => setState(() => _a = _a.copyWith(gestational: v))),
          ),
        3 => _Question(
            title: 'Do you have a mother, father, sister or brother with diabetes?',
            child: _yesNo(_a.familyHistory,
                (v) => setState(() => _a = _a.copyWith(familyHistory: v))),
          ),
        4 => _Question(
            title: 'Have you ever been diagnosed with high blood pressure?',
            child: _yesNo(_a.highBloodPressure,
                (v) => setState(() => _a = _a.copyWith(highBloodPressure: v))),
          ),
        5 => _Question(
            title: 'Are you physically active?',
            hint: 'At least 150 minutes of activity a week.',
            child: _yesNo(_a.physicallyActive,
                (v) => setState(() => _a = _a.copyWith(physicallyActive: v))),
          ),
        _ => _Question(
            title: 'What is your height and weight?',
            hint: _a.bmi == null ? null : 'BMI ${_a.bmi!.toStringAsFixed(1)}',
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _height,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                        hintText: 'Height', suffixText: 'cm'),
                    onChanged: (v) => setState(() =>
                        _a = _a.copyWith(heightCm: double.tryParse(v))),
                  ),
                ),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: TextField(
                    controller: _weight,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                        hintText: 'Weight', suffixText: 'kg'),
                    onChanged: (v) => setState(() =>
                        _a = _a.copyWith(weightKg: double.tryParse(v))),
                  ),
                ),
              ],
            ),
          ),
      };

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: _step == 0,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _back();
      },
      child: Scaffold(
        appBar: AppBar(
          leading: IconButton(
              icon: const Icon(Icons.arrow_back_rounded), onPressed: _back),
          title: Text('Question ${_step + 1} of $_total'),
        ),
        body: Column(
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.page),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(AppRadius.pill),
                child: LinearProgressIndicator(
                  value: (_step + 1) / _total,
                  minHeight: 6,
                  backgroundColor: context.palette.primarySoft,
                ),
              ),
            ),
            Expanded(
              child: AnimatedSwitcher(
                duration: const Duration(milliseconds: 200),
                child: KeyedSubtree(key: ValueKey(_step), child: _question()),
              ),
            ),
          ],
        ),
        bottomNavigationBar: SafeArea(
          minimum: const EdgeInsets.all(AppSpacing.page),
          child: FilledButton(
            onPressed: _answered && !_submitting ? _next : null,
            child: Text(_step == _total - 1
                ? (_submitting ? 'Calculating…' : 'See my result')
                : 'Next'),
          ),
        ),
      ),
    );
  }
}

class _Question extends StatelessWidget {
  const _Question({required this.title, required this.child, this.hint});
  final String title;
  final String? hint;
  final Widget child;

  @override
  Widget build(BuildContext context) => ListView(
        padding: const EdgeInsets.all(AppSpacing.page),
        children: [
          Text(title, style: Theme.of(context).textTheme.titleLarge),
          if (hint != null) ...[
            const SizedBox(height: AppSpacing.sm),
            Text(hint!, style: Theme.of(context).textTheme.bodySmall),
          ],
          const SizedBox(height: AppSpacing.xxl),
          child,
        ],
      );
}

class _Option extends StatelessWidget {
  const _Option({required this.label, required this.selected, required this.onTap});
  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: AppSpacing.md),
        child: AppCard(
          onTap: onTap,
          color: selected ? context.palette.primarySoft : null,
          child: Row(
            children: [
              Expanded(
                child: Text(label, style: Theme.of(context).textTheme.titleMedium),
              ),
              Icon(
                selected
                    ? Icons.radio_button_checked_rounded
                    : Icons.radio_button_off_rounded,
                color: selected ? AppColors.primary : context.palette.textSecondary,
              ),
            ],
          ),
        ),
      );
}

/// Figma "12 · Risk Results": band, score /11, per-factor breakdown,
/// recommendations, Retake / Save.
class RiskResultScreen extends StatelessWidget {
  const RiskResultScreen({super.key, required this.result});
  final CdcResult result;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final color = riskColor(result.band);
    return Scaffold(
      appBar: AppBar(title: const Text('Your Result')),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.page),
        children: [
          AppCard(
            child: Column(
              children: [
                ProgressRing(
                  size: 150,
                  value: result.score / CdcResult.maxScore,
                  color: color,
                  center: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text('${result.score}',
                          style: t.headlineMedium?.copyWith(color: color)),
                      Text('out of ${CdcResult.maxScore}', style: t.bodySmall),
                    ],
                  ),
                ),
                const SizedBox(height: AppSpacing.lg),
                Text(result.band.label, style: t.titleLarge?.copyWith(color: color)),
                const SizedBox(height: AppSpacing.xs),
                Text(
                  result.band == RiskBand.high
                      ? 'A score of 5 or more means you may have prediabetes or be at high risk.'
                      : 'Keep up healthy habits and retake this test yearly.',
                  style: t.bodySmall,
                  textAlign: TextAlign.center,
                ),
                if (!result.saved) ...[
                  const SizedBox(height: AppSpacing.sm),
                  Text('Not saved — you appear to be offline.',
                      style: t.bodySmall?.copyWith(color: AppColors.warning)),
                ],
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.xl),
          const SectionHeader('What contributed'),
          AppCard(
            child: Column(
              children: [
                for (final f in result.factors)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs),
                    child: GoalBar(
                      label: f.label,
                      value: f.points.toDouble(),
                      goal: f.maxPoints.toDouble(),
                      unit: 'pts',
                      color: f.points == 0 ? AppColors.success : color,
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.xl),
          const SectionHeader('Recommendations'),
          for (final r in result.recommendations)
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.check_circle_outline_rounded,
                  color: AppColors.primary),
              title: Text(r),
            ),
        ],
      ),
      bottomNavigationBar: SafeArea(
        minimum: const EdgeInsets.all(AppSpacing.page),
        child: Row(
          children: [
            Expanded(
              child: OutlinedButton(
                onPressed: () => context.pushReplacement(Routes.riskQuiz),
                child: const Text('Retake'),
              ),
            ),
            const SizedBox(width: AppSpacing.md),
            Expanded(
              child: FilledButton(
                onPressed: () => context.pop(),
                child: Text(result.saved ? 'Done' : 'Close'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
