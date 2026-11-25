import 'package:flutter/material.dart';
import 'package:shimmer/shimmer.dart';

import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';

/// Figma "23 · Empty State": icon, title, message, optional CTA.
class EmptyStateView extends StatelessWidget {
  const EmptyStateView({
    super.key,
    required this.icon,
    required this.title,
    required this.message,
    this.actionLabel,
    this.onAction,
  });

  final IconData icon;
  final String title;
  final String message;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xxxl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            CircleAvatar(
              radius: 40,
              backgroundColor: context.palette.primarySoft,
              child: Icon(icon, size: 36, color: AppColors.primary),
            ),
            const SizedBox(height: AppSpacing.xl),
            Text(title, style: t.titleLarge, textAlign: TextAlign.center),
            const SizedBox(height: AppSpacing.sm),
            Text(message, style: t.bodySmall, textAlign: TextAlign.center),
            if (actionLabel != null) ...[
              const SizedBox(height: AppSpacing.xxl),
              FilledButton(onPressed: onAction, child: Text(actionLabel!)),
            ],
          ],
        ),
      ),
    );
  }
}

/// Figma "24 · Error State" / no-connection: message + "Try again".
class ErrorStateView extends StatelessWidget {
  const ErrorStateView({super.key, required this.message, this.onRetry});
  final String message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) => EmptyStateView(
        icon: Icons.wifi_off_rounded,
        title: 'Something went wrong',
        message: message,
        actionLabel: onRetry == null ? null : 'Try again',
        onAction: onRetry,
      );
}

/// Figma "25 · Loading Skeleton": gray placeholder cards.
class SkeletonList extends StatelessWidget {
  const SkeletonList({super.key, this.count = 4, this.height = 96});
  final int count;
  final double height;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Shimmer.fromColors(
      baseColor: p.border,
      highlightColor: p.surface,
      child: ListView.separated(
        padding: const EdgeInsets.all(AppSpacing.page),
        physics: const NeverScrollableScrollPhysics(),
        itemCount: count,
        separatorBuilder: (_, _) => const SizedBox(height: AppSpacing.md),
        itemBuilder: (_, _) => Container(
          height: height,
          decoration: BoxDecoration(
            color: p.border,
            borderRadius: BorderRadius.circular(AppRadius.lg),
          ),
        ),
      ),
    );
  }
}
