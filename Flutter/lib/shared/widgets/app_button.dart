import 'package:flutter/material.dart';

import '../../core/theme/app_dimensions.dart';

class AppButton extends StatelessWidget {
  const AppButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.isLoading = false,
    this.isOutlined = false,
    this.isFullWidth = true,
    this.icon,
    this.color,
  });

  final String label;
  final VoidCallback? onPressed;
  final bool isLoading;
  final bool isOutlined;
  final bool isFullWidth;
  final IconData? icon;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final button = isOutlined
        ? OutlinedButton(
            onPressed: isLoading ? null : onPressed,
            style: color != null
                ? OutlinedButton.styleFrom(
                    foregroundColor: color,
                    side: BorderSide(color: color!),
                  )
                : null,
            child: _buildChild(context),
          )
        : ElevatedButton(
            onPressed: isLoading ? null : onPressed,
            style: color != null
                ? ElevatedButton.styleFrom(
                    backgroundColor: color,
                    foregroundColor:
                        ThemeData.estimateBrightnessForColor(color!) ==
                                Brightness.dark
                            ? Colors.white
                            : Colors.black,
                  )
                : null,
            child: _buildChild(context),
          );

    return isFullWidth
        ? SizedBox(
            width: double.infinity,
            height: AppDimensions.buttonHeight,
            child: button,
          )
        : button;
  }

  Widget _buildChild(BuildContext context) {
    if (isLoading) {
      return SizedBox(
        height: 20,
        width: 20,
        child: CircularProgressIndicator(
          strokeWidth: 2,
          color: isOutlined
              ? Theme.of(context).colorScheme.primary
              : Theme.of(context).colorScheme.onPrimary,
        ),
      );
    }

    if (icon != null) {
      return Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: AppDimensions.iconSize),
          const SizedBox(width: AppDimensions.sm),
          Text(label),
        ],
      );
    }

    return Text(label);
  }
}
