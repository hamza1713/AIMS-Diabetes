import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/router/routes.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/theme_mode_controller.dart';
import '../../../core/utils/format.dart';
import '../../../core/widgets/app_card.dart';
import '../../../core/widgets/async_view.dart';
import '../../../core/widgets/form_widgets.dart';
import '../../auth/application/auth_controller.dart';
import '../../auth/presentation/auth_scaffold.dart';
import '../data/profile_repository.dart';

Future<void> _confirmLogout(BuildContext context, WidgetRef ref) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (d) => AlertDialog(
      title: const Text('Log out?'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(d, false), child: const Text('Cancel')),
        TextButton(onPressed: () => Navigator.pop(d, true), child: const Text('Log out')),
      ],
    ),
  );
  if (ok == true) await ref.read(authControllerProvider.notifier).logout();
}

/// Figma "05 · Profile" and "DARK · Profile".
class ProfileScreen extends ConsumerWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final t = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Profile')),
      body: AsyncView(
        value: ref.watch(profileProvider),
        onRetry: () => ref.invalidate(profileProvider),
        data: (p) => ListView(
          padding: const EdgeInsets.fromLTRB(AppSpacing.page, 0, AppSpacing.page, 100),
          children: [
            Center(
              child: CircleAvatar(
                radius: 44,
                backgroundColor: context.palette.primarySoft,
                child: Text(p.initials,
                    style: t.headlineMedium?.copyWith(color: AppColors.primary)),
              ),
            ),
            const SizedBox(height: AppSpacing.md),
            Text(p.name, style: t.titleLarge, textAlign: TextAlign.center),
            Text(p.email, style: t.bodySmall, textAlign: TextAlign.center),
            const SizedBox(height: AppSpacing.xl),
            Row(
              children: [
                for (final (label, value) in [
                  ('Age', p.age?.toString() ?? '—'),
                  ('Height', p.heightCm == null ? '—' : '${fmtNum(p.heightCm)} cm'),
                  ('Weight', p.weightKg == null ? '—' : '${fmtNum(p.weightKg)} kg'),
                  ('BMI', p.bmi == null ? '—' : p.bmi!.toStringAsFixed(1)),
                ])
                  Expanded(
                    child: Column(
                      children: [
                        Text(value, style: t.titleMedium),
                        Text(label, style: t.bodySmall),
                      ],
                    ),
                  ),
              ],
            ),
            const SizedBox(height: AppSpacing.xl),
            AppCard(
              padding: EdgeInsets.zero,
              child: Column(
                children: [
                  _MenuItem(Icons.person_outline_rounded, 'Edit profile',
                      () => context.push(Routes.editProfile)),
                  _MenuItem(Icons.insights_rounded, 'Analytics & reports',
                      () => context.go(Routes.analytics)),
                  _MenuItem(Icons.assignment_outlined, 'Risk assessment',
                      () => context.push(Routes.riskIntro)),
                  _MenuItem(Icons.notifications_none_rounded, 'Notifications',
                      () => context.go(Routes.notifications)),
                  _MenuItem(Icons.settings_outlined, 'Settings',
                      () => context.push(Routes.settings)),
                ],
              ),
            ),
            const SizedBox(height: AppSpacing.lg),
            AppCard(
              padding: EdgeInsets.zero,
              child: _MenuItem(Icons.logout_rounded, 'Log out',
                  () => _confirmLogout(context, ref),
                  color: AppColors.danger),
            ),
          ],
        ),
      ),
    );
  }
}

class _MenuItem extends StatelessWidget {
  const _MenuItem(this.icon, this.label, this.onTap, {this.color});
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final Color? color;

  @override
  Widget build(BuildContext context) => ListTile(
        leading: Icon(icon, color: color ?? AppColors.primary),
        title: Text(label, style: TextStyle(color: color)),
        trailing: color == null ? const Icon(Icons.chevron_right_rounded) : null,
        onTap: onTap,
      );
}

/// Figma "14 · Edit Profile".
class EditProfileScreen extends ConsumerStatefulWidget {
  const EditProfileScreen({super.key});

  @override
  ConsumerState<EditProfileScreen> createState() => _EditProfileScreenState();
}

class _EditProfileScreenState extends ConsumerState<EditProfileScreen> {
  /// Backend codes → labels.
  static const _types = {
    'type1': 'Type 1',
    'type2': 'Type 2',
    'prediabetes': 'Prediabetes',
    'gestational': 'Gestational',
    'none': 'None',
  };
  static const _genders = ['Female', 'Male', 'Other'];

  final _form = GlobalKey<FormState>();
  late final UserProfile _p = ref.read(profileProvider).requireValue;
  late final _name = TextEditingController(text: _p.name);
  late final _age = TextEditingController(text: _p.age?.toString());
  late final _height =
      TextEditingController(text: _p.heightCm == null ? null : fmtNum(_p.heightCm));
  late final _weight =
      TextEditingController(text: _p.weightKg == null ? null : fmtNum(_p.weightKg));
  late String? _gender = _genders.firstWhere(
      (g) => g.toLowerCase() == _p.gender?.toLowerCase(),
      orElse: () => '');
  late String? _type =
      _types.containsKey(_p.diabetesType) ? _p.diabetesType : null;
  bool _busy = false;

  @override
  void dispose() {
    for (final c in [_name, _age, _height, _weight]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    if (!_form.currentState!.validate()) return;
    setState(() => _busy = true);
    try {
      await ref.read(profileRepositoryProvider).update(UserProfile(
            name: _name.text.trim(),
            email: _p.email,
            age: int.tryParse(_age.text.trim()),
            gender: (_gender ?? '').isEmpty ? null : _gender!.toLowerCase(),
            heightCm: double.tryParse(_height.text.trim()),
            weightKg: double.tryParse(_weight.text.trim()),
            diabetesType: _type,
          ));
      ref.invalidate(profileProvider);
      if (mounted) context.pop();
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String? _optionalNumber(String? v, double min, double max) =>
      (v ?? '').trim().isEmpty ? null : requiredNumber(v, min: min, max: max);

  @override
  Widget build(BuildContext context) => Form(
        key: _form,
        child: FormScaffold(
          title: 'Edit Profile',
          submitLabel: 'Save changes',
          busy: _busy,
          onSubmit: _save,
          children: [
            const FieldLabel('Name'),
            TextFormField(
              controller: _name,
              textCapitalization: TextCapitalization.words,
              validator: (v) => (v ?? '').trim().isEmpty ? 'Enter your name' : null,
            ),
            const FieldLabel('Email'),
            TextFormField(initialValue: _p.email, enabled: false),
            const FieldLabel('Gender'),
            ChoiceChips<String>(
              options: _genders,
              selected: _gender,
              label: (g) => g,
              onSelected: (g) => setState(() => _gender = g),
            ),
            const FieldLabel('Age, height & weight'),
            Row(
              children: [
                Expanded(
                  child: TextFormField(
                    controller: _age,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(hintText: 'Age'),
                    validator: (v) => _optionalNumber(v, 1, 120),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: TextFormField(
                    controller: _height,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(hintText: 'Height', suffixText: 'cm'),
                    validator: (v) => _optionalNumber(v, 50, 250),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: TextFormField(
                    controller: _weight,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(hintText: 'Weight', suffixText: 'kg'),
                    validator: (v) => _optionalNumber(v, 20, 400),
                  ),
                ),
              ],
            ),
            const FieldLabel('Diabetes type'),
            ChoiceChips<String>(
              options: _types.keys.toList(),
              selected: _type,
              label: (code) => _types[code]!,
              onSelected: (code) => setState(() => _type = code),
            ),
          ],
        ),
      );
}

/// Figma "15 · Settings".
class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key});

  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends ConsumerState<SettingsScreen> {
  Preferences? _prefs;

  Future<void> _update(Preferences next) async {
    final previous = _prefs;
    setState(() => _prefs = next);
    try {
      await ref.read(profileRepositoryProvider).savePreferences(next);
    } catch (e) {
      if (mounted) {
        setState(() => _prefs = previous);
        showError(context, e);
      }
    }
  }

  Future<void> _changePassword() async {
    final current = TextEditingController();
    final next = TextEditingController();
    final key = GlobalKey<FormState>();
    final ok = await showDialog<bool>(
      context: context,
      builder: (d) => AlertDialog(
        title: const Text('Change password'),
        content: Form(
          key: key,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(
                controller: current,
                obscureText: true,
                decoration: const InputDecoration(hintText: 'Current password'),
                validator: (v) => (v ?? '').isEmpty ? 'Required' : null,
              ),
              const SizedBox(height: AppSpacing.md),
              TextFormField(
                controller: next,
                obscureText: true,
                decoration: const InputDecoration(hintText: 'New password'),
                validator: validatePassword,
              ),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d, false), child: const Text('Cancel')),
          TextButton(
            onPressed: () {
              if (key.currentState!.validate()) Navigator.pop(d, true);
            },
            child: const Text('Change'),
          ),
        ],
      ),
    );
    if (ok == true) {
      try {
        await ref
            .read(profileRepositoryProvider)
            .changePassword(current.text, next.text);
        if (mounted) {
          ScaffoldMessenger.of(context)
              .showSnackBar(const SnackBar(content: Text('Password changed')));
        }
      } catch (e) {
        if (mounted) showError(context, e);
      }
    }
    current.dispose();
    next.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final loaded = ref.watch(preferencesProvider);
    final p = _prefs ?? loaded.value ?? Preferences();
    final mode = ref.watch(themeModeProvider);

    Widget section(String title, List<Widget> children) => Padding(
          padding: const EdgeInsets.only(bottom: AppSpacing.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                child: Text(title, style: Theme.of(context).textTheme.titleMedium),
              ),
              AppCard(padding: EdgeInsets.zero, child: Column(children: children)),
            ],
          ),
        );

    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.page),
        children: [
          section('Account', [
            ListTile(
              leading: const Icon(Icons.person_outline_rounded),
              title: const Text('Edit profile'),
              trailing: const Icon(Icons.chevron_right_rounded),
              onTap: () => context.push(Routes.editProfile),
            ),
            ListTile(
              leading: const Icon(Icons.lock_outline_rounded),
              title: const Text('Change password'),
              trailing: const Icon(Icons.chevron_right_rounded),
              onTap: _changePassword,
            ),
          ]),
          section('Preferences', [
            ListTile(
              leading: const Icon(Icons.straighten_rounded),
              title: const Text('Glucose units'),
              trailing: DropdownButton<String>(
                value: const {'mg/dL', 'mmol/L'}.contains(p.glucoseUnit)
                    ? p.glucoseUnit
                    : null,
                underline: const SizedBox.shrink(),
                items: const [
                  DropdownMenuItem(value: 'mg/dL', child: Text('mg/dL')),
                  DropdownMenuItem(value: 'mmol/L', child: Text('mmol/L')),
                ],
                onChanged: (v) => _update(p.copyWith(glucoseUnit: v)),
              ),
            ),
            ListTile(
              leading: const Icon(Icons.language_rounded),
              title: const Text('Language'),
              trailing: DropdownButton<String>(
                // DropdownButton asserts on values that aren't in items.
                value: const {'en', 'ur'}.contains(p.language) ? p.language : null,
                underline: const SizedBox.shrink(),
                items: const [
                  DropdownMenuItem(value: 'en', child: Text('English')),
                  DropdownMenuItem(value: 'ur', child: Text('Urdu')),
                ],
                onChanged: (v) => _update(p.copyWith(language: v)),
              ),
            ),
            ListTile(
              leading: const Icon(Icons.dark_mode_outlined),
              title: const Text('Theme'),
              trailing: DropdownButton<ThemeMode>(
                value: mode,
                underline: const SizedBox.shrink(),
                items: const [
                  DropdownMenuItem(value: ThemeMode.system, child: Text('System')),
                  DropdownMenuItem(value: ThemeMode.light, child: Text('Light')),
                  DropdownMenuItem(value: ThemeMode.dark, child: Text('Dark')),
                ],
                onChanged: (m) =>
                    ref.read(themeModeProvider.notifier).set(m ?? ThemeMode.system),
              ),
            ),
          ]),
          section('Notifications', [
            SwitchListTile(
              secondary: const Icon(Icons.medication_outlined),
              title: const Text('Medication reminders'),
              value: p.medicationReminders,
              onChanged: (v) => _update(p.copyWith(medicationReminders: v)),
            ),
            SwitchListTile(
              secondary: const Icon(Icons.bloodtype_outlined),
              title: const Text('High / low glucose alerts'),
              value: p.glucoseAlerts,
              onChanged: (v) => _update(p.copyWith(glucoseAlerts: v)),
            ),
            SwitchListTile(
              secondary: const Icon(Icons.lightbulb_outline_rounded),
              title: const Text('Daily health tips'),
              value: p.dailyTips,
              onChanged: (v) => _update(p.copyWith(dailyTips: v)),
            ),
          ]),
          section('Support', [
            ListTile(
              leading: const Icon(Icons.help_outline_rounded),
              title: const Text('Help & support'),
              onTap: () => showAboutDialog(
                context: context,
                applicationName: 'AIMS Diabetes',
                applicationVersion: '1.0.0',
              ),
            ),
            const ListTile(
              leading: Icon(Icons.privacy_tip_outlined),
              title: Text('Privacy'),
              subtitle: Text('Your health data is stored only on your account.'),
            ),
          ]),
          OutlinedButton.icon(
            style: OutlinedButton.styleFrom(foregroundColor: AppColors.danger),
            onPressed: () => _confirmLogout(context, ref),
            icon: const Icon(Icons.logout_rounded),
            label: const Text('Log out'),
          ),
        ],
      ),
    );
  }
}
