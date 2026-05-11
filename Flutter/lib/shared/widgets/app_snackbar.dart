import 'package:flutter/material.dart';

import 'package:template_app/core/theme/app_dimensions.dart';
import 'package:template_app/core/theme/color_schemes.dart';

enum SnackbarType { success, error, info }

class AppSnackbar {
  AppSnackbar._();

  static void show(
    BuildContext context, {
    required String message,
    SnackbarType type = SnackbarType.info,
    Duration duration = const Duration(seconds: 3),
  }) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final colorScheme = Theme.of(context).colorScheme;

    final Color backgroundColor;
    final Color foregroundColor;
    final IconData icon;

    switch (type) {
      case SnackbarType.success:
        backgroundColor = isDark ? AppColors.successDark : AppColors.success;
        foregroundColor = Colors.white;
        icon = Icons.check_circle_outline;
      case SnackbarType.error:
        backgroundColor = colorScheme.error;
        foregroundColor = colorScheme.onError;
        icon = Icons.error_outline;
      case SnackbarType.info:
        backgroundColor = isDark ? AppColors.infoDark : AppColors.info;
        foregroundColor = Colors.white;
        icon = Icons.info_outline;
    }

    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Row(
            children: [
              Icon(icon, color: foregroundColor, size: AppDimensions.iconSize),
              const SizedBox(width: AppDimensions.sm),
              Expanded(
                child: Text(
                  message,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: foregroundColor,
                      ),
                ),
              ),
            ],
          ),
          backgroundColor: backgroundColor,
          behavior: SnackBarBehavior.floating,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
          ),
          duration: duration,
        ),
      );
  }
}
