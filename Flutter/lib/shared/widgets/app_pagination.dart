import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../core/theme/app_dimensions.dart';

class AppPagination extends StatelessWidget {
  const AppPagination({
    super.key,
    required this.currentPage,
    required this.totalPages,
    required this.totalCount,
    required this.pageSize,
    required this.onPageChanged,
    required this.onPageSizeChanged,
    this.pageSizeOptions = const [5, 10, 25, 50],
  });

  final int currentPage;
  final int totalPages;
  final int totalCount;
  final int pageSize;
  final ValueChanged<int> onPageChanged;
  final ValueChanged<int> onPageSizeChanged;
  final List<int> pageSizeOptions;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;

    final startItem = totalCount == 0 ? 0 : (currentPage - 1) * pageSize + 1;
    final endItem = math.min(currentPage * pageSize, totalCount);

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppDimensions.sm),
      child: Wrap(
        alignment: WrapAlignment.spaceBetween,
        crossAxisAlignment: WrapCrossAlignment.center,
        spacing: AppDimensions.md,
        runSpacing: AppDimensions.sm,
        children: [
          // Showing count + page size
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                'Showing $startItem-$endItem of $totalCount',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: colorScheme.onSurface.withValues(alpha: 0.7),
                ),
              ),
              const SizedBox(width: AppDimensions.sm),
              SizedBox(
                height: 32,
                child: DropdownButtonHideUnderline(
                  child: DropdownButton<int>(
                    value: pageSize,
                    isDense: true,
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: colorScheme.onSurface,
                    ),
                    items: pageSizeOptions
                        .map((size) => DropdownMenuItem<int>(
                              value: size,
                              child: Text('$size / page'),
                            ))
                        .toList(),
                    onChanged: (value) {
                      if (value != null) {
                        onPageSizeChanged(value);
                      }
                    },
                  ),
                ),
              ),
            ],
          ),

          // Page navigation
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              _NavButton(
                icon: Icons.chevron_left,
                onPressed: currentPage > 1
                    ? () => onPageChanged(currentPage - 1)
                    : null,
              ),
              ..._buildPageButtons(theme, colorScheme),
              _NavButton(
                icon: Icons.chevron_right,
                onPressed: currentPage < totalPages
                    ? () => onPageChanged(currentPage + 1)
                    : null,
              ),
            ],
          ),
        ],
      ),
    );
  }

  List<Widget> _buildPageButtons(ThemeData theme, ColorScheme colorScheme) {
    final pages = _getVisiblePages();
    final widgets = <Widget>[];

    for (int i = 0; i < pages.length; i++) {
      final page = pages[i];

      // Add ellipsis if gap between consecutive pages
      if (i > 0 && page > pages[i - 1] + 1) {
        widgets.add(
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppDimensions.xs),
            child: Text(
              '...',
              style: theme.textTheme.bodySmall?.copyWith(
                color: colorScheme.onSurface.withValues(alpha: 0.5),
              ),
            ),
          ),
        );
      }

      final isActive = page == currentPage;
      widgets.add(
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 2),
          child: SizedBox(
            width: 32,
            height: 32,
            child: Material(
              color: isActive ? colorScheme.primary : Colors.transparent,
              borderRadius: BorderRadius.circular(AppDimensions.radiusXs),
              child: InkWell(
                borderRadius: BorderRadius.circular(AppDimensions.radiusXs),
                onTap: isActive ? null : () => onPageChanged(page),
                child: Center(
                  child: Text(
                    '$page',
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: isActive
                          ? colorScheme.onPrimary
                          : colorScheme.onSurface,
                      fontWeight: isActive ? FontWeight.w600 : FontWeight.w400,
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      );
    }

    return widgets;
  }

  List<int> _getVisiblePages() {
    if (totalPages <= 7) {
      return List.generate(totalPages, (i) => i + 1);
    }

    final pages = <int>{1, totalPages};

    // Add pages around current
    for (int i = currentPage - 1; i <= currentPage + 1; i++) {
      if (i >= 1 && i <= totalPages) {
        pages.add(i);
      }
    }

    final sorted = pages.toList()..sort();
    return sorted;
  }
}

class _NavButton extends StatelessWidget {
  const _NavButton({
    required this.icon,
    required this.onPressed,
  });

  final IconData icon;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;

    return SizedBox(
      width: 32,
      height: 32,
      child: IconButton(
        padding: EdgeInsets.zero,
        iconSize: 20,
        onPressed: onPressed,
        icon: Icon(icon),
        color: colorScheme.onSurface,
        disabledColor: colorScheme.onSurface.withValues(alpha: 0.3),
      ),
    );
  }
}
