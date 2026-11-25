import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';

/// Shared layout for Login / Sign Up / Forgot Password (Figma 01, 01b, 01c).
class AuthScaffold extends StatelessWidget {
  const AuthScaffold({
    super.key,
    required this.title,
    required this.subtitle,
    required this.children,
    this.showBack = false,
  });

  final String title;
  final String subtitle;
  final List<Widget> children;
  final bool showBack;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Scaffold(
      appBar: showBack ? AppBar() : null,
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.page, vertical: AppSpacing.xxl),
          children: [
            Center(
              child: Container(
                width: 72,
                height: 72,
                decoration: BoxDecoration(
                  color: AppColors.primary,
                  borderRadius: BorderRadius.circular(AppRadius.lg),
                ),
                child: const Icon(Icons.water_drop_rounded,
                    color: Colors.white, size: 36),
              ),
            ),
            const SizedBox(height: AppSpacing.xxl),
            Text(title, style: t.headlineMedium, textAlign: TextAlign.center),
            const SizedBox(height: AppSpacing.sm),
            Text(subtitle, style: t.bodySmall, textAlign: TextAlign.center),
            const SizedBox(height: AppSpacing.xxxl),
            ...children,
          ],
        ),
      ),
    );
  }
}

String? validateEmail(String? v) {
  final value = v?.trim() ?? '';
  if (value.isEmpty) return 'Enter your email';
  if (!RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(value)) {
    return 'Enter a valid email';
  }
  return null;
}

String? validatePassword(String? v) {
  if ((v ?? '').length < 8) return 'Use at least 8 characters';
  return null;
}
