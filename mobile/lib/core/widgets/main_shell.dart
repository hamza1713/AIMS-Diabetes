import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../network/connectivity.dart';
import '../router/routes.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';

/// Bottom navigation (Home / Chat / Track / Profile) with a center "+" button
/// that opens the quick-add sheet.
class MainShell extends StatelessWidget {
  const MainShell({super.key, required this.shell});
  final StatefulNavigationShell shell;

  static const _tabs = [
    (Icons.home_outlined, Icons.home_rounded, 'Home'),
    (Icons.chat_bubble_outline_rounded, Icons.chat_bubble_rounded, 'Chat'),
    (Icons.monitor_heart_outlined, Icons.monitor_heart_rounded, 'Track'),
    (Icons.person_outline_rounded, Icons.person_rounded, 'Profile'),
  ];

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Scaffold(
      body: Column(
        children: [
          const _OfflineBanner(),
          Expanded(child: shell),
        ],
      ),
      floatingActionButtonLocation: FloatingActionButtonLocation.centerDocked,
      floatingActionButton: FloatingActionButton(
        shape: const CircleBorder(),
        backgroundColor: AppColors.primary,
        foregroundColor: Colors.white,
        elevation: 2,
        onPressed: () => showQuickAddSheet(context),
        child: const Icon(Icons.add_rounded, size: 30),
      ),
      bottomNavigationBar: BottomAppBar(
        color: p.surface,
        shape: const CircularNotchedRectangle(),
        notchMargin: 8,
        padding: EdgeInsets.zero,
        height: 68,
        child: Row(
          children: [
            for (var i = 0; i < _tabs.length; i++) ...[
              if (i == 2) const SizedBox(width: 64),
              Expanded(child: _tab(context, i)),
            ],
          ],
        ),
      ),
    );
  }

  Widget _tab(BuildContext context, int i) {
    final (icon, activeIcon, label) = _tabs[i];
    final selected = shell.currentIndex == i;
    final color = selected ? AppColors.primary : context.palette.textSecondary;
    return InkResponse(
      onTap: () => shell.goBranch(i, initialLocation: selected),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(selected ? activeIcon : icon, color: color),
          const SizedBox(height: 2),
          Text(label,
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(color: color, fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }
}

class _OfflineBanner extends ConsumerWidget {
  const _OfflineBanner();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final offline = ref.watch(offlineProvider).value ?? false;
    return AnimatedSize(
      duration: const Duration(milliseconds: 200),
      child: offline
          ? Material(
              color: AppColors.danger,
              child: SafeArea(
                bottom: false,
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const Icon(Icons.wifi_off_rounded, color: Colors.white, size: 16),
                      const SizedBox(width: 6),
                      Text('No connection',
                          style: Theme.of(context)
                              .textTheme
                              .bodySmall
                              ?.copyWith(color: Colors.white)),
                    ],
                  ),
                ),
              ),
            )
          : const SizedBox(width: double.infinity),
    );
  }
}

/// Quick-add actions behind the center "+" button.
void showQuickAddSheet(BuildContext context) {
  const items = [
    (Icons.bloodtype_outlined, 'Glucose', Routes.addGlucose, AppColors.danger),
    (Icons.restaurant_rounded, 'Meal', Routes.addMeal, AppColors.warning),
    (Icons.directions_run_rounded, 'Workout', Routes.logWorkout, AppColors.success),
    (Icons.water_drop_outlined, 'Water', Routes.addWater, AppColors.water),
    (Icons.medication_outlined, 'Medication', Routes.addMedication, AppColors.primary),
  ];
  showModalBottomSheet<void>(
    context: context,
    showDragHandle: true,
    builder: (sheet) => SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
            AppSpacing.page, 0, AppSpacing.page, AppSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Quick add', style: Theme.of(sheet).textTheme.titleLarge),
            const SizedBox(height: AppSpacing.lg),
            Wrap(
              spacing: AppSpacing.md,
              runSpacing: AppSpacing.md,
              children: [
                for (final (icon, label, route, color) in items)
                  SizedBox(
                    width: 96,
                    child: InkWell(
                      borderRadius: BorderRadius.circular(AppRadius.md),
                      onTap: () {
                        Navigator.of(sheet).pop();
                        context.push(route);
                      },
                      child: Padding(
                        padding: const EdgeInsets.all(AppSpacing.sm),
                        child: Column(
                          children: [
                            CircleAvatar(
                              radius: 26,
                              backgroundColor: color.withValues(alpha: 0.12),
                              child: Icon(icon, color: color),
                            ),
                            const SizedBox(height: AppSpacing.sm),
                            Text(label),
                          ],
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
    ),
  );
}
