import 'package:flutter/material.dart';

class AppColors {
  AppColors._();

  // === Brand Colors (shared between themes) ===
  static const Color primaryBrand = Color(0xFF1976D2); // Blue 700
  static const Color secondaryBrand = Color(0xFF424242); // Grey 800

  // === Light Theme Colors ===
  static const lightColorScheme = ColorScheme(
    brightness: Brightness.light,
    primary: Color(0xFF1976D2),
    onPrimary: Colors.white,
    primaryContainer: Color(0xFFBBDEFB),
    onPrimaryContainer: Color(0xFF0D47A1),
    secondary: Color(0xFF424242),
    onSecondary: Colors.white,
    secondaryContainer: Color(0xFFE0E0E0),
    onSecondaryContainer: Color(0xFF212121),
    surface: Color(0xFFFAFAFA),
    onSurface: Color(0xFF212121),
    surfaceContainerHighest: Color(0xFFE0E0E0),
    error: Color(0xFFD32F2F),
    onError: Colors.white,
    errorContainer: Color(0xFFFFCDD2),
    onErrorContainer: Color(0xFFB71C1C),
    outline: Color(0xFFBDBDBD),
    outlineVariant: Color(0xFFE0E0E0),
    shadow: Colors.black26,
  );

  // === Dark Theme Colors ===
  static const darkColorScheme = ColorScheme(
    brightness: Brightness.dark,
    primary: Color(0xFF90CAF9),
    onPrimary: Color(0xFF0D47A1),
    primaryContainer: Color(0xFF1565C0),
    onPrimaryContainer: Color(0xFFBBDEFB),
    secondary: Color(0xFFBDBDBD),
    onSecondary: Color(0xFF212121),
    secondaryContainer: Color(0xFF424242),
    onSecondaryContainer: Color(0xFFE0E0E0),
    surface: Color(0xFF121212),
    onSurface: Color(0xFFE0E0E0),
    surfaceContainerHighest: Color(0xFF2C2C2C),
    error: Color(0xFFEF5350),
    onError: Color(0xFF690005),
    errorContainer: Color(0xFF93000A),
    onErrorContainer: Color(0xFFFFDAD6),
    outline: Color(0xFF616161),
    outlineVariant: Color(0xFF424242),
    shadow: Colors.black54,
  );

  // === Status Colors (semantic) ===
  static const Color success = Color(0xFF4CAF50);
  static const Color successDark = Color(0xFF81C784);
  static const Color warning = Color(0xFFFFC107);
  static const Color warningDark = Color(0xFFFFD54F);
  static const Color info = Color(0xFF2196F3);
  static const Color infoDark = Color(0xFF64B5F6);
}
