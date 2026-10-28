import 'package:flutter/material.dart';

import 'app_dimensions.dart';
import 'color_schemes.dart';
import 'text_styles.dart';

class AppTheme {
  AppTheme._();

  // === Shared component themes (color-independent) ===

  static final _cardTheme = CardThemeData(
    elevation: AppDimensions.elevationLow,
    shape: RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(AppDimensions.radiusMd),
    ),
  );

  static const _buttonPadding = EdgeInsets.symmetric(
    horizontal: AppDimensions.lg,
    vertical: AppDimensions.md,
  );

  static final _buttonShape = RoundedRectangleBorder(
    borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
  );

  static final _elevatedButtonTheme = ElevatedButtonThemeData(
    style: ElevatedButton.styleFrom(
      padding: _buttonPadding,
      shape: _buttonShape,
    ),
  );

  static final _outlinedButtonTheme = OutlinedButtonThemeData(
    style: OutlinedButton.styleFrom(
      padding: _buttonPadding,
      shape: _buttonShape,
    ),
  );

  static final _inputBorder = OutlineInputBorder(
    borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
  );

  static const _inputContentPadding = EdgeInsets.symmetric(
    horizontal: AppDimensions.md,
    vertical: AppDimensions.sm,
  );

  // === Theme builders ===

  static ThemeData _buildTheme(ColorScheme colorScheme) => ThemeData(
        useMaterial3: true,
        colorScheme: colorScheme,
        scaffoldBackgroundColor: colorScheme.surface,
        textTheme: AppTextStyles.textTheme,

        // AppBar
        appBarTheme: AppBarTheme(
          elevation: 0,
          scrolledUnderElevation: 1,
          backgroundColor: colorScheme.surface,
          foregroundColor: colorScheme.onSurface,
        ),

        // Card
        cardTheme: _cardTheme,

        // Input
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor:
              colorScheme.surfaceContainerHighest.withValues(alpha: 0.3),
          border: _inputBorder,
          contentPadding: _inputContentPadding,
        ),

        // Buttons
        elevatedButtonTheme: _elevatedButtonTheme,
        outlinedButtonTheme: _outlinedButtonTheme,

        // Drawer
        drawerTheme: DrawerThemeData(
          backgroundColor: colorScheme.surface,
        ),

        // Divider
        dividerTheme: DividerThemeData(
          color: colorScheme.outlineVariant,
          thickness: 1,
        ),
      );

  static ThemeData get light => _buildTheme(AppColors.lightColorScheme);
  static ThemeData get dark => _buildTheme(AppColors.darkColorScheme);
}
