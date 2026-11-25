import 'package:flutter/material.dart';

/// Design tokens for AIMS-Diabetes.
///
/// Values are approximated from the Figma "📱 Screens" page. Once Figma MCP
/// access is granted, replace them with the exact variables from
/// `get_variable_defs` — every widget reads colors from here or from
/// [AppPalette], so a token change propagates everywhere.
abstract final class AppColors {
  // Brand
  static const primary = Color(0xFF6C4CE0);
  static const primaryDark = Color(0xFF5235C4);
  static const primarySoft = Color(0xFFEFEAFF);

  // Semantic (glucose bands, statuses)
  static const success = Color(0xFF22B07D);
  static const warning = Color(0xFFF5A524);
  static const danger = Color(0xFFE5484D);
  static const info = Color(0xFF3B82F6);
  static const water = Color(0xFF38BDF8);

  // Light surfaces
  static const lightBackground = Color(0xFFF6F5FB);
  static const lightSurface = Color(0xFFFFFFFF);
  static const lightBorder = Color(0xFFE7E4F2);
  static const lightTextPrimary = Color(0xFF1B1530);
  static const lightTextSecondary = Color(0xFF6E6A80);

  // Dark surfaces (DARK · Home / AI Chat / Profile frames)
  static const darkBackground = Color(0xFF12101C);
  static const darkSurface = Color(0xFF1D1A2B);
  static const darkBorder = Color(0xFF2E2A42);
  static const darkTextPrimary = Color(0xFFF4F2FB);
  static const darkTextSecondary = Color(0xFFA7A3B8);
}

/// Theme-aware palette available via `context.palette`.
@immutable
class AppPalette extends ThemeExtension<AppPalette> {
  const AppPalette({
    required this.background,
    required this.surface,
    required this.border,
    required this.textPrimary,
    required this.textSecondary,
    required this.primarySoft,
  });

  final Color background;
  final Color surface;
  final Color border;
  final Color textPrimary;
  final Color textSecondary;
  final Color primarySoft;

  static const light = AppPalette(
    background: AppColors.lightBackground,
    surface: AppColors.lightSurface,
    border: AppColors.lightBorder,
    textPrimary: AppColors.lightTextPrimary,
    textSecondary: AppColors.lightTextSecondary,
    primarySoft: AppColors.primarySoft,
  );

  static const dark = AppPalette(
    background: AppColors.darkBackground,
    surface: AppColors.darkSurface,
    border: AppColors.darkBorder,
    textPrimary: AppColors.darkTextPrimary,
    textSecondary: AppColors.darkTextSecondary,
    primarySoft: Color(0xFF2A2245),
  );

  @override
  AppPalette copyWith({
    Color? background,
    Color? surface,
    Color? border,
    Color? textPrimary,
    Color? textSecondary,
    Color? primarySoft,
  }) =>
      AppPalette(
        background: background ?? this.background,
        surface: surface ?? this.surface,
        border: border ?? this.border,
        textPrimary: textPrimary ?? this.textPrimary,
        textSecondary: textSecondary ?? this.textSecondary,
        primarySoft: primarySoft ?? this.primarySoft,
      );

  @override
  AppPalette lerp(AppPalette? other, double t) {
    if (other == null) return this;
    return AppPalette(
      background: Color.lerp(background, other.background, t)!,
      surface: Color.lerp(surface, other.surface, t)!,
      border: Color.lerp(border, other.border, t)!,
      textPrimary: Color.lerp(textPrimary, other.textPrimary, t)!,
      textSecondary: Color.lerp(textSecondary, other.textSecondary, t)!,
      primarySoft: Color.lerp(primarySoft, other.primarySoft, t)!,
    );
  }
}

extension PaletteX on BuildContext {
  AppPalette get palette => Theme.of(this).extension<AppPalette>()!;
}
