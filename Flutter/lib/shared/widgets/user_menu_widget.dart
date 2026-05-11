import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/constants/app_routes.dart';
import '../../core/theme/app_dimensions.dart';
import '../../providers/auth_provider.dart';

/// Profile dropdown menu in the AppBar.
///
/// Shows a circle avatar with user initial, and a popup menu with
/// Profile, Change Password, Security, and Logout options.
class UserMenuWidget extends ConsumerWidget {
  const UserMenuWidget({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authState = ref.watch(authProvider);
    final theme = Theme.of(context);
    final userInitial = _getUserInitial(authState.userId);

    return PopupMenuButton<String>(
      offset: const Offset(0, AppDimensions.appBarHeight),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppDimensions.radiusMd),
      ),
      onSelected: (value) => _onMenuSelected(context, ref, value),
      itemBuilder: (_) => [
        // Header — user info
        PopupMenuItem<String>(
          enabled: false,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  CircleAvatar(
                    radius: AppDimensions.avatarSizeSm / 2,
                    backgroundColor: theme.colorScheme.primary,
                    child: Text(
                      userInitial,
                      style: TextStyle(
                        color: theme.colorScheme.onPrimary,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                  const SizedBox(width: AppDimensions.sm),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          authState.userId ?? 'User',
                          style: theme.textTheme.titleSmall,
                          overflow: TextOverflow.ellipsis,
                        ),
                        Text(
                          'User Account',
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
        const PopupMenuDivider(),
        _buildMenuItem(
          icon: Icons.person_outlined,
          label: 'Profile',
          value: 'profile',
        ),
        _buildMenuItem(
          icon: Icons.lock_outlined,
          label: 'Change Password',
          value: 'change_password',
        ),
        _buildMenuItem(
          icon: Icons.security_outlined,
          label: 'Security',
          value: 'security',
        ),
        const PopupMenuDivider(),
        _buildMenuItem(
          icon: Icons.logout,
          label: 'Logout',
          value: 'logout',
          isDanger: true,
        ),
      ],
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: AppDimensions.sm),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            CircleAvatar(
              radius: AppDimensions.avatarSizeSm / 2,
              backgroundColor: theme.colorScheme.primary,
              child: Text(
                userInitial,
                style: TextStyle(
                  color: theme.colorScheme.onPrimary,
                  fontSize: 14,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
            const SizedBox(width: AppDimensions.xs),
            const Icon(Icons.arrow_drop_down),
          ],
        ),
      ),
    );
  }

  PopupMenuItem<String> _buildMenuItem({
    required IconData icon,
    required String label,
    required String value,
    bool isDanger = false,
  }) {
    return PopupMenuItem<String>(
      value: value,
      child: Builder(
        builder: (context) {
          final theme = Theme.of(context);
          final color =
              isDanger ? theme.colorScheme.error : theme.colorScheme.onSurface;
          return Row(
            children: [
              Icon(icon, size: 20, color: color),
              const SizedBox(width: AppDimensions.sm),
              Text(label, style: TextStyle(color: color)),
            ],
          );
        },
      ),
    );
  }

  String _getUserInitial(String? userId) {
    if (userId == null || userId.isEmpty) return 'U';
    return userId[0].toUpperCase();
  }

  void _onMenuSelected(BuildContext context, WidgetRef ref, String value) {
    switch (value) {
      case 'profile':
        context.goNamed(AppRoutes.userProfile);
      case 'change_password':
        context.goNamed(AppRoutes.userChangePassword);
      case 'security':
        context.goNamed(AppRoutes.userSecurity);
      case 'logout':
        ref.read(authProvider.notifier).logout();
        context.goNamed(AppRoutes.login);
    }
  }
}
