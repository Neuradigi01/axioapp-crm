# Flutter App — Theming Reference

Theme system architecture, design tokens, dark/light mode, and styling rules.

---

## Theme Architecture Overview

This app uses **Material 3** theming with a custom `ColorScheme` and `ThemeData` for both light and dark modes. The theme is managed via a `ThemeService` and exposed through Riverpod.

```
ThemeService (manages preference)
    ↓
ThemeProvider (Riverpod StateNotifier)
    ↓
MaterialApp.router(theme: lightTheme, darkTheme: darkTheme, themeMode: ...)
    ↓
Theme.of(context) — accessed in widgets
```

---

## File Structure

```
lib/
├── core/
│   ├── theme/
│   │   ├── app_theme.dart          # ThemeData definitions (light + dark)
│   │   ├── color_schemes.dart      # ColorScheme for light + dark
│   │   ├── text_styles.dart        # TextTheme customization
│   │   └── app_dimensions.dart     # Spacing, radius, elevation constants
│   └── services/
│       └── theme_service.dart      # Theme persistence + toggle
├── providers/
│   └── theme_provider.dart         # Riverpod provider for theme state
```

---

## Color Scheme Definition

```dart
// lib/core/theme/color_schemes.dart

import 'package:flutter/material.dart';

class AppColors {
  // === Brand Colors (shared between themes) ===
  static const Color primaryBrand = Color(0xFF1976D2);    // Blue 700
  static const Color secondaryBrand = Color(0xFF424242);  // Grey 800

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
```

---

## ThemeData Definitions

```dart
// lib/core/theme/app_theme.dart

import 'package:flutter/material.dart';
import 'color_schemes.dart';
import 'text_styles.dart';
import 'app_dimensions.dart';

class AppTheme {
  static ThemeData get light => ThemeData(
    useMaterial3: true,
    colorScheme: AppColors.lightColorScheme,
    scaffoldBackgroundColor: AppColors.lightColorScheme.surface,
    textTheme: AppTextStyles.textTheme,
    
    // AppBar
    appBarTheme: AppBarTheme(
      elevation: 0,
      scrolledUnderElevation: 1,
      backgroundColor: AppColors.lightColorScheme.surface,
      foregroundColor: AppColors.lightColorScheme.onSurface,
    ),
    
    // Card
    cardTheme: CardTheme(
      elevation: AppDimensions.elevationLow,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppDimensions.radiusMd),
      ),
    ),
    
    // Input
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AppColors.lightColorScheme.surfaceContainerHighest.withOpacity(0.3),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
      ),
      contentPadding: const EdgeInsets.symmetric(
        horizontal: AppDimensions.md,
        vertical: AppDimensions.sm,
      ),
    ),
    
    // Elevated Button
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        padding: const EdgeInsets.symmetric(
          horizontal: AppDimensions.lg,
          vertical: AppDimensions.md,
        ),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
        ),
      ),
    ),
    
    // Outlined Button
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        padding: const EdgeInsets.symmetric(
          horizontal: AppDimensions.lg,
          vertical: AppDimensions.md,
        ),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
        ),
      ),
    ),
    
    // Drawer
    drawerTheme: DrawerThemeData(
      backgroundColor: AppColors.lightColorScheme.surface,
    ),
    
    // Divider
    dividerTheme: DividerThemeData(
      color: AppColors.lightColorScheme.outlineVariant,
      thickness: 1,
    ),
  );

  static ThemeData get dark => ThemeData(
    useMaterial3: true,
    colorScheme: AppColors.darkColorScheme,
    scaffoldBackgroundColor: AppColors.darkColorScheme.surface,
    textTheme: AppTextStyles.textTheme,
    
    // Mirror all component themes with dark color scheme
    appBarTheme: AppBarTheme(
      elevation: 0,
      scrolledUnderElevation: 1,
      backgroundColor: AppColors.darkColorScheme.surface,
      foregroundColor: AppColors.darkColorScheme.onSurface,
    ),
    
    cardTheme: CardTheme(
      elevation: AppDimensions.elevationLow,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppDimensions.radiusMd),
      ),
    ),
    
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AppColors.darkColorScheme.surfaceContainerHighest.withOpacity(0.3),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
      ),
      contentPadding: const EdgeInsets.symmetric(
        horizontal: AppDimensions.md,
        vertical: AppDimensions.sm,
      ),
    ),
    
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        padding: const EdgeInsets.symmetric(
          horizontal: AppDimensions.lg,
          vertical: AppDimensions.md,
        ),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
        ),
      ),
    ),
    
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        padding: const EdgeInsets.symmetric(
          horizontal: AppDimensions.lg,
          vertical: AppDimensions.md,
        ),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
        ),
      ),
    ),
    
    drawerTheme: DrawerThemeData(
      backgroundColor: AppColors.darkColorScheme.surface,
    ),
    
    dividerTheme: DividerThemeData(
      color: AppColors.darkColorScheme.outlineVariant,
      thickness: 1,
    ),
  );
}
```

---

## Spacing & Dimensions

```dart
// lib/core/theme/app_dimensions.dart

class AppDimensions {
  // === Spacing Scale ===
  static const double xs = 4.0;
  static const double sm = 8.0;
  static const double md = 16.0;
  static const double lg = 24.0;
  static const double xl = 32.0;
  static const double xxl = 48.0;

  // === Border Radius ===
  static const double radiusXs = 4.0;
  static const double radiusSm = 8.0;
  static const double radiusMd = 12.0;
  static const double radiusLg = 16.0;
  static const double radiusXl = 24.0;
  static const double radiusFull = 999.0;

  // === Elevation ===
  static const double elevationNone = 0.0;
  static const double elevationLow = 1.0;
  static const double elevationMedium = 4.0;
  static const double elevationHigh = 8.0;

  // === Component Sizes ===
  static const double appBarHeight = 56.0;
  static const double drawerWidth = 280.0;
  static const double authCardMaxWidth = 480.0;
  static const double formMaxWidth = 600.0;
  static const double buttonHeight = 48.0;
  static const double iconSize = 24.0;
  static const double avatarSizeSm = 32.0;
  static const double avatarSizeMd = 48.0;
  static const double avatarSizeLg = 80.0;
  static const double avatarSizeXl = 120.0;

  // === Breakpoints ===
  static const double breakpointMobile = 600.0;
  static const double breakpointTablet = 960.0;
  static const double breakpointDesktop = 1280.0;

  // === Touch Target ===
  static const double minTouchTarget = 48.0;
}
```

---

## Text Styles

```dart
// lib/core/theme/text_styles.dart

import 'package:flutter/material.dart';

class AppTextStyles {
  static const textTheme = TextTheme(
    // Display
    displayLarge: TextStyle(fontSize: 57, fontWeight: FontWeight.w400, letterSpacing: -0.25),
    displayMedium: TextStyle(fontSize: 45, fontWeight: FontWeight.w400),
    displaySmall: TextStyle(fontSize: 36, fontWeight: FontWeight.w400),
    
    // Headline
    headlineLarge: TextStyle(fontSize: 32, fontWeight: FontWeight.w600),
    headlineMedium: TextStyle(fontSize: 28, fontWeight: FontWeight.w600),
    headlineSmall: TextStyle(fontSize: 24, fontWeight: FontWeight.w600),
    
    // Title
    titleLarge: TextStyle(fontSize: 22, fontWeight: FontWeight.w500),
    titleMedium: TextStyle(fontSize: 16, fontWeight: FontWeight.w500, letterSpacing: 0.15),
    titleSmall: TextStyle(fontSize: 14, fontWeight: FontWeight.w500, letterSpacing: 0.1),
    
    // Body
    bodyLarge: TextStyle(fontSize: 16, fontWeight: FontWeight.w400, letterSpacing: 0.5),
    bodyMedium: TextStyle(fontSize: 14, fontWeight: FontWeight.w400, letterSpacing: 0.25),
    bodySmall: TextStyle(fontSize: 12, fontWeight: FontWeight.w400, letterSpacing: 0.4),
    
    // Label
    labelLarge: TextStyle(fontSize: 14, fontWeight: FontWeight.w500, letterSpacing: 0.1),
    labelMedium: TextStyle(fontSize: 12, fontWeight: FontWeight.w500, letterSpacing: 0.5),
    labelSmall: TextStyle(fontSize: 11, fontWeight: FontWeight.w500, letterSpacing: 0.5),
  );
}
```

---

## ThemeService & Provider

```dart
// lib/core/services/theme_service.dart
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

class ThemeService {
  static const _key = 'theme_mode';
  final SharedPreferences _prefs;

  ThemeService(this._prefs);

  ThemeMode get themeMode {
    final value = _prefs.getString(_key);
    if (value == 'dark') return ThemeMode.dark;
    if (value == 'light') return ThemeMode.light;
    return ThemeMode.system;
  }

  Future<void> setThemeMode(ThemeMode mode) async {
    await _prefs.setString(_key, mode.name);
  }

  Future<void> toggle() async {
    final current = themeMode;
    final next = current == ThemeMode.dark ? ThemeMode.light : ThemeMode.dark;
    await setThemeMode(next);
  }
}
```

```dart
// lib/providers/theme_provider.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class ThemeNotifier extends StateNotifier<ThemeMode> {
  ThemeNotifier(this._themeService) : super(_themeService.themeMode);
  final ThemeService _themeService;

  Future<void> toggle() async {
    await _themeService.toggle();
    state = _themeService.themeMode;
  }

  Future<void> setTheme(ThemeMode mode) async {
    await _themeService.setThemeMode(mode);
    state = mode;
  }
}

final themeProvider = StateNotifierProvider<ThemeNotifier, ThemeMode>((ref) {
  final themeService = ref.read(themeServiceProvider);
  return ThemeNotifier(themeService);
});
```

---

## Usage in MaterialApp

```dart
// lib/app.dart
class App extends ConsumerWidget {
  const App({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final themeMode = ref.watch(themeProvider);

    return MaterialApp.router(
      title: AppConstants.appName,
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      themeMode: themeMode,
      routerConfig: appRouter,
    );
  }
}
```

---

## Styling Rules

### MANDATORY — Use Theme Tokens
```dart
// GOOD — use Theme.of(context) for all styling
final theme = Theme.of(context);
final colorScheme = theme.colorScheme;

Container(
  color: colorScheme.surface,
  child: Text(
    'Hello',
    style: theme.textTheme.titleMedium?.copyWith(
      color: colorScheme.onSurface,
    ),
  ),
)

// BAD — hardcoded colors
Container(
  color: Colors.white,          // FORBIDDEN
  child: Text(
    'Hello',
    style: TextStyle(
      color: Color(0xFF212121),  // FORBIDDEN
      fontSize: 16,              // Use theme.textTheme instead
    ),
  ),
)
```

### MANDATORY — Use AppDimensions
```dart
// GOOD
Padding(padding: const EdgeInsets.all(AppDimensions.md))
BorderRadius.circular(AppDimensions.radiusSm)
SizedBox(height: AppDimensions.lg)

// BAD — magic numbers
Padding(padding: const EdgeInsets.all(16))   // FORBIDDEN
BorderRadius.circular(8)                      // FORBIDDEN
```

### FORBIDDEN Practices
- Hardcoded colors (`Colors.white`, `Color(0xFF...)` in widgets)
- Hardcoded spacing/radius values in widgets
- Inline `TextStyle` without deriving from theme
- Using `Theme.of(context).primaryColor` (deprecated pattern)
- Defining colors in widget files

### REQUIRED Practices
- All colors from `colorScheme`
- All spacing from `AppDimensions`
- All text styles from `theme.textTheme`
- Status colors from `AppColors.success/warning/info` (with theme-aware selection)
- Consistent transitions/animations using Material defaults

---

## Status Color Helper

```dart
// For status-dependent colors that differ between light/dark
Color getStatusColor(BuildContext context, String status) {
  final isDark = Theme.of(context).brightness == Brightness.dark;
  switch (status.toLowerCase()) {
    case 'active':
    case 'open':
    case 'enabled':
      return isDark ? AppColors.successDark : AppColors.success;
    case 'warning':
    case 'in progress':
      return isDark ? AppColors.warningDark : AppColors.warning;
    case 'error':
    case 'closed':
    case 'blocked':
      return Theme.of(context).colorScheme.error;
    default:
      return Theme.of(context).colorScheme.outline;
  }
}
```

---

## Adding a New Color

Before adding any color:
1. Check if `colorScheme` already has a suitable semantic role
2. If truly new (e.g., a brand accent), add to `AppColors` as a named constant
3. Add both light and dark variants
4. Use in widgets via helper function, not directly

---

## Quality Checklist

- [ ] No hardcoded colors in widgets
- [ ] No hardcoded spacing/radius in widgets
- [ ] All text styles derive from `theme.textTheme`
- [ ] Light and dark themes both look correct
- [ ] Status colors use theme-aware helper
- [ ] Cards, buttons, inputs use themed component styles
- [ ] Sufficient contrast in both themes
- [ ] Theme toggle works and persists
