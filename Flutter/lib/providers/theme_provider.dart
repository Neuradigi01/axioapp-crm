import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/services/theme_service.dart';

final sharedPreferencesProvider = Provider<SharedPreferences>((ref) {
  throw UnimplementedError('Must be overridden in ProviderScope');
});

final themeServiceProvider = Provider<ThemeService>((ref) {
  final prefs = ref.read(sharedPreferencesProvider);
  return ThemeService(prefs);
});

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
