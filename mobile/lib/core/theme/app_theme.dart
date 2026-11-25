import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import 'app_colors.dart';
import 'app_spacing.dart';

abstract final class AppTheme {
  static ThemeData light() => _build(Brightness.light, AppPalette.light);
  static ThemeData dark() => _build(Brightness.dark, AppPalette.dark);

  static ThemeData _build(Brightness brightness, AppPalette p) {
    final scheme = ColorScheme.fromSeed(
      seedColor: AppColors.primary,
      brightness: brightness,
    ).copyWith(
      primary: AppColors.primary,
      onPrimary: Colors.white,
      surface: p.surface,
      onSurface: p.textPrimary,
      error: AppColors.danger,
      outline: p.border,
    );

    // Only the family name comes from google_fonts; the TextTheme stays
    // Flutter's own so it type-checks against this SDK.
    final baseText = (brightness == Brightness.light
            ? ThemeData.light().textTheme
            : ThemeData.dark().textTheme)
        .apply(
      fontFamily: GoogleFonts.inter().fontFamily,
      bodyColor: p.textPrimary,
      displayColor: p.textPrimary,
    );

    final textTheme = baseText.copyWith(
      headlineMedium: baseText.headlineMedium
          ?.copyWith(fontSize: 26, fontWeight: FontWeight.w700),
      titleLarge:
          baseText.titleLarge?.copyWith(fontSize: 20, fontWeight: FontWeight.w700),
      titleMedium:
          baseText.titleMedium?.copyWith(fontSize: 16, fontWeight: FontWeight.w600),
      bodyMedium: baseText.bodyMedium?.copyWith(fontSize: 14),
      bodySmall: baseText.bodySmall
          ?.copyWith(fontSize: 12, color: p.textSecondary),
      labelLarge:
          baseText.labelLarge?.copyWith(fontSize: 15, fontWeight: FontWeight.w600),
    );

    final inputBorder = OutlineInputBorder(
      borderRadius: BorderRadius.circular(AppRadius.md),
      borderSide: BorderSide(color: p.border),
    );

    return ThemeData(
      useMaterial3: true,
      brightness: brightness,
      colorScheme: scheme,
      scaffoldBackgroundColor: p.background,
      textTheme: textTheme,
      extensions: [p],
      appBarTheme: AppBarTheme(
        backgroundColor: p.background,
        foregroundColor: p.textPrimary,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        titleTextStyle: textTheme.titleLarge,
      ),
      cardTheme: CardThemeData(
        color: p.surface,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.lg),
          side: BorderSide(color: p.border),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: p.surface,
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        border: inputBorder,
        enabledBorder: inputBorder,
        focusedBorder: inputBorder.copyWith(
          borderSide: const BorderSide(color: AppColors.primary, width: 1.5),
        ),
        errorBorder: inputBorder.copyWith(
          borderSide: const BorderSide(color: AppColors.danger),
        ),
        hintStyle: TextStyle(color: p.textSecondary),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: AppColors.primary,
          foregroundColor: Colors.white,
          minimumSize: const Size.fromHeight(52),
          shape: const StadiumBorder(),
          textStyle: textTheme.labelLarge,
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: p.textPrimary,
          minimumSize: const Size.fromHeight(52),
          shape: const StadiumBorder(),
          side: BorderSide(color: p.border),
          textStyle: textTheme.labelLarge,
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(foregroundColor: AppColors.primary),
      ),
      chipTheme: ChipThemeData(
        backgroundColor: p.surface,
        selectedColor: AppColors.primary,
        side: BorderSide(color: p.border),
        shape: const StadiumBorder(),
        labelStyle: textTheme.bodyMedium,
      ),
      dividerTheme: DividerThemeData(color: p.border, space: 1),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: p.surface,
        indicatorColor: p.primarySoft,
        elevation: 0,
        labelTextStyle: WidgetStateProperty.resolveWith(
          (s) => textTheme.bodySmall?.copyWith(
            color: s.contains(WidgetState.selected)
                ? AppColors.primary
                : p.textSecondary,
            fontWeight: FontWeight.w600,
          ),
        ),
        iconTheme: WidgetStateProperty.resolveWith(
          (s) => IconThemeData(
            color: s.contains(WidgetState.selected)
                ? AppColors.primary
                : p.textSecondary,
          ),
        ),
      ),
    );
  }
}
