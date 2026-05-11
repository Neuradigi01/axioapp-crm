import 'package:flutter/material.dart';

import '../../core/theme/app_dimensions.dart';

class AppCard extends StatelessWidget {
  const AppCard({
    super.key,
    this.title,
    this.subtitle,
    required this.child,
    this.padding,
    this.maxWidth,
  });

  final String? title;
  final String? subtitle;
  final Widget child;
  final EdgeInsetsGeometry? padding;
  final double? maxWidth;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    final Widget content = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        if (title != null) ...[
          Text(
            title!,
            style: theme.textTheme.titleLarge,
          ),
          if (subtitle != null) ...[
            const SizedBox(height: AppDimensions.xs),
            Text(
              subtitle!,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ],
          const SizedBox(height: AppDimensions.md),
        ],
        child,
      ],
    );

    Widget card = Card(
      child: Padding(
        padding: padding ?? const EdgeInsets.all(AppDimensions.lg),
        child: content,
      ),
    );

    if (maxWidth != null) {
      card = ConstrainedBox(
        constraints: BoxConstraints(maxWidth: maxWidth!),
        child: card,
      );
    }

    return card;
  }
}
