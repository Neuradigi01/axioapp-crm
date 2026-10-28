import 'package:flutter/material.dart';

import '../../../core/theme/app_dimensions.dart';

/// A metric tile card for the dashboard grid.
///
/// Displays an icon in a tinted circle on the left, with a label and value
/// on the right. Uses a subtle background tint derived from [color].
class DashboardTileWidget extends StatelessWidget {
  const DashboardTileWidget({
    super.key,
    required this.icon,
    required this.label,
    required this.value,
    this.color,
  });

  final IconData icon;
  final String label;
  final String value;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final tileColor = color ?? theme.colorScheme.primary;
    final isDark = theme.brightness == Brightness.dark;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppDimensions.md),
        child: Row(
          children: [
            // Icon circle
            Container(
              width: AppDimensions.avatarSizeMd,
              height: AppDimensions.avatarSizeMd,
              decoration: BoxDecoration(
                color: tileColor.withValues(alpha: isDark ? 0.15 : 0.1),
                shape: BoxShape.circle,
              ),
              child: Icon(
                icon,
                color: tileColor,
                size: AppDimensions.iconSize,
              ),
            ),
            const SizedBox(width: AppDimensions.md),
            // Label + value
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    label,
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  const SizedBox(height: AppDimensions.xs),
                  Text(
                    value,
                    style: theme.textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
