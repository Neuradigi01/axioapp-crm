import 'package:flutter/material.dart';

import '../../core/theme/app_dimensions.dart';

class _BadgeColors {
  const _BadgeColors({required this.color, required this.background});
  final Color color;
  final Color background;
}

class AppStatusBadge extends StatelessWidget {
  const AppStatusBadge({
    super.key,
    required this.label,
  });

  final String label;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = _getBadgeColors(theme.brightness);

    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppDimensions.sm + AppDimensions.xs,
        vertical: AppDimensions.xs,
      ),
      decoration: BoxDecoration(
        color: colors.background,
        borderRadius: BorderRadius.circular(AppDimensions.radiusFull),
      ),
      child: Text(
        label,
        style: theme.textTheme.labelSmall?.copyWith(
          color: colors.color,
          fontWeight: FontWeight.w500,
        ),
      ),
    );
  }

  _BadgeColors _getBadgeColors(Brightness brightness) {
    final isDark = brightness == Brightness.dark;
    final key = label.toLowerCase();

    switch (key) {
      case 'active':
      case 'subscribed':
      case 'resolved':
        const color = Color(0xFF22C55E);
        return _BadgeColors(
          color: color,
          background: color.withValues(alpha: isDark ? 0.12 : 0.1),
        );
      case 'inactive':
      case 'unsubscribed':
        const color = Color(0xFFEF4444);
        return _BadgeColors(
          color: color,
          background: color.withValues(alpha: isDark ? 0.12 : 0.1),
        );
      case 'open':
      case 'general':
      case 'user':
        const color = Color(0xFF3B82F6);
        return _BadgeColors(
          color: color,
          background: color.withValues(alpha: isDark ? 0.12 : 0.1),
        );
      case 'in progress':
      case 'support':
      case 'admin':
        const color = Color(0xFFF59E0B);
        return _BadgeColors(
          color: color,
          background: color.withValues(alpha: isDark ? 0.12 : 0.1),
        );
      case 'closed':
        const color = Color(0xFF6B7280);
        return _BadgeColors(
          color: color,
          background: color.withValues(alpha: isDark ? 0.12 : 0.1),
        );
      default:
        const color = Color(0xFF6B7280);
        return _BadgeColors(
          color: color,
          background: color.withValues(alpha: isDark ? 0.12 : 0.1),
        );
    }
  }
}
