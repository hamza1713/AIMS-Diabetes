import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/utils/format.dart';
import '../../core/widgets/async_view.dart';
import '../../core/widgets/state_views.dart';
import 'data/notifications_repository.dart';

/// Figma "16 · Notifications": grouped Today / Earlier with unread dots.
class NotificationsScreen extends ConsumerWidget {
  const NotificationsScreen({super.key});

  Future<void> _markAll(BuildContext context, WidgetRef ref) async {
    try {
      await ref.read(notificationsRepositoryProvider).markAllRead();
      ref.invalidate(notificationsProvider);
    } catch (e) {
      if (context.mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final unread = ref.watch(unreadCountProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Notifications'),
        actions: [
          if (unread > 0)
            TextButton(
              onPressed: () => _markAll(context, ref),
              child: const Text('Mark all read'),
            ),
        ],
      ),
      body: AsyncView(
        value: ref.watch(notificationsProvider),
        onRetry: () => ref.invalidate(notificationsProvider),
        data: (items) {
          if (items.isEmpty) {
            return const EmptyStateView(
              icon: Icons.notifications_none_rounded,
              title: "You're all caught up",
              message: 'Reminders and glucose alerts will show up here.',
            );
          }
          final now = DateTime.now();
          final today = items.where((n) => isSameDay(n.createdAt, now)).toList();
          final earlier = items.where((n) => !isSameDay(n.createdAt, now)).toList();
          return RefreshIndicator(
            onRefresh: () async => ref.invalidate(notificationsProvider),
            child: ListView(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.page, 0, AppSpacing.page, AppSpacing.xxl),
              children: [
                if (today.isNotEmpty) ...[
                  _GroupLabel('Today'),
                  ...today.map((n) => _Tile(n)),
                ],
                if (earlier.isNotEmpty) ...[
                  _GroupLabel('Earlier'),
                  ...earlier.map((n) => _Tile(n)),
                ],
              ],
            ),
          );
        },
      ),
    );
  }
}

class _GroupLabel extends StatelessWidget {
  const _GroupLabel(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: AppSpacing.lg, bottom: AppSpacing.sm),
        child: Text(text, style: Theme.of(context).textTheme.titleMedium),
      );
}

class _Tile extends StatelessWidget {
  const _Tile(this.n);
  final AppNotification n;

  (IconData, Color) get _style => switch (n.kind) {
        'medication' => (Icons.medication_outlined, AppColors.primary),
        'glucose' => (Icons.bloodtype_outlined, AppColors.danger),
        'tip' => (Icons.lightbulb_outline_rounded, AppColors.warning),
        _ => (Icons.notifications_none_rounded, AppColors.info),
      };

  @override
  Widget build(BuildContext context) {
    final (icon, color) = _style;
    final t = Theme.of(context).textTheme;
    return Container(
      margin: const EdgeInsets.only(bottom: AppSpacing.sm),
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: n.read ? context.palette.surface : context.palette.primarySoft,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: context.palette.border),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          CircleAvatar(
            radius: 20,
            backgroundColor: color.withValues(alpha: 0.12),
            child: Icon(icon, color: color, size: 20),
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(n.title, style: t.titleMedium),
                if (n.body.isNotEmpty) Text(n.body, style: t.bodyMedium),
                const SizedBox(height: 2),
                Text(fmtTime(n.createdAt), style: t.bodySmall),
              ],
            ),
          ),
          if (!n.read)
            const Padding(
              padding: EdgeInsets.only(top: 6),
              child: CircleAvatar(radius: 4, backgroundColor: AppColors.primary),
            ),
        ],
      ),
    );
  }
}
