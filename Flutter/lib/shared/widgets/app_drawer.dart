import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/constants/app_constants.dart';
import '../../core/constants/app_routes.dart';
import '../../core/theme/app_dimensions.dart';
import '../../providers/auth_provider.dart';

/// Navigation menu item data.
///
/// The [children] field supports expandable parent-child menu hierarchy.
/// Currently unused — will be populated with dynamic routes in Phase 8.
class _NavMenuItem {
  const _NavMenuItem({
    required this.label,
    required this.icon,
    required this.routeName,
    List<_NavMenuItem>? children,
  }) : children = children ?? const [];

  final String label;
  final IconData icon;
  final String routeName;
  final List<_NavMenuItem> children;

  bool get hasChildren => children.isNotEmpty;
}

/// Navigation drawer for the user layout (mobile).
///
/// Wraps [AppDrawerContent] in a [Drawer] for use with [Scaffold.drawer].
class AppDrawer extends StatelessWidget {
  const AppDrawer({super.key});

  @override
  Widget build(BuildContext context) {
    return Drawer(
      width: AppDimensions.drawerWidth,
      child: AppDrawerContent(isInDrawer: true),
    );
  }
}

/// The actual navigation content — used both inside [AppDrawer] (mobile)
/// and directly in the desktop persistent sidebar.
class AppDrawerContent extends ConsumerStatefulWidget {
  const AppDrawerContent({super.key, this.isInDrawer = false});

  /// Whether this content is rendered inside a [Drawer] overlay.
  /// Controls status bar padding and auto-close behavior.
  final bool isInDrawer;

  @override
  ConsumerState<AppDrawerContent> createState() => _AppDrawerContentState();
}

class _AppDrawerContentState extends ConsumerState<AppDrawerContent> {
  final Set<String> _expandedItems = {};

  // Static menu items — replaced with dynamic routes from backend in Phase 8.
  static const List<_NavMenuItem> _menuItems = [
    _NavMenuItem(
      label: 'Dashboard',
      icon: Icons.dashboard_outlined,
      routeName: AppRoutes.userDashboard,
    ),
    _NavMenuItem(
      label: 'Security',
      icon: Icons.security_outlined,
      routeName: AppRoutes.userSecurity,
    ),
    _NavMenuItem(
      label: 'Login History',
      icon: Icons.history_outlined,
      routeName: AppRoutes.userLoginHistory,
    ),
    _NavMenuItem(
      label: 'Support',
      icon: Icons.support_agent_outlined,
      routeName: AppRoutes.userSupport,
    ),
  ];

  @override
  Widget build(BuildContext context) {
    final authState = ref.watch(authProvider);
    final theme = Theme.of(context);
    final currentRoute = GoRouterState.of(context).matchedLocation;

    return Column(
      children: [
        _buildHeader(theme, authState),
        const Divider(height: 1),
        Expanded(
          child: ListView.builder(
            padding: const EdgeInsets.symmetric(vertical: AppDimensions.sm),
            itemCount: _menuItems.length,
            itemBuilder: (_, index) =>
                _buildMenuItem(_menuItems[index], theme, currentRoute),
          ),
        ),
      ],
    );
  }

  Widget _buildHeader(ThemeData theme, AuthState authState) {
    final userInitial = _getUserInitial(authState.userId);
    // Only add status bar padding when inside a Drawer overlay
    final topPadding = widget.isInDrawer
        ? MediaQuery.of(context).padding.top + AppDimensions.lg
        : AppDimensions.lg;

    return Container(
      padding: EdgeInsets.only(
        top: topPadding,
        left: AppDimensions.md,
        right: AppDimensions.md,
        bottom: AppDimensions.md,
      ),
      color: theme.colorScheme.primary,
      child: Row(
        children: [
          CircleAvatar(
            radius: AppDimensions.avatarSizeMd / 2,
            backgroundColor: theme.colorScheme.onPrimary.withValues(alpha: 0.2),
            child: Text(
              userInitial,
              style: TextStyle(
                color: theme.colorScheme.onPrimary,
                fontSize: 20,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
          const SizedBox(width: AppDimensions.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  authState.userId ?? 'User',
                  style: theme.textTheme.titleMedium?.copyWith(
                    color: theme.colorScheme.onPrimary,
                    fontWeight: FontWeight.bold,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: AppDimensions.xs),
                Text(
                  AppConstants.roleUser,
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onPrimary.withValues(alpha: 0.8),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMenuItem(
    _NavMenuItem item,
    ThemeData theme,
    String currentRoute,
  ) {
    final isActive = _isRouteActive(item.routeName, currentRoute);

    if (item.hasChildren) {
      return _buildExpandableItem(item, theme, currentRoute);
    }

    return _buildNavTile(
      item: item,
      theme: theme,
      isActive: isActive,
      indent: 0,
    );
  }

  Widget _buildExpandableItem(
    _NavMenuItem item,
    ThemeData theme,
    String currentRoute,
  ) {
    final isExpanded = _expandedItems.contains(item.routeName);
    final hasActiveChild = item.children.any(
      (child) => _isRouteActive(child.routeName, currentRoute),
    );

    return Column(
      children: [
        ListTile(
          leading: Icon(
            item.icon,
            color: hasActiveChild
                ? theme.colorScheme.primary
                : theme.colorScheme.onSurfaceVariant,
          ),
          title: Text(
            item.label,
            style: TextStyle(
              color: hasActiveChild
                  ? theme.colorScheme.primary
                  : theme.colorScheme.onSurface,
              fontWeight: hasActiveChild ? FontWeight.w600 : FontWeight.normal,
            ),
          ),
          trailing: Icon(
            isExpanded ? Icons.expand_less : Icons.expand_more,
            color: theme.colorScheme.onSurfaceVariant,
          ),
          onTap: () {
            setState(() {
              if (isExpanded) {
                _expandedItems.remove(item.routeName);
              } else {
                _expandedItems.add(item.routeName);
              }
            });
          },
        ),
        if (isExpanded)
          ...item.children.map(
            (child) => _buildNavTile(
              item: child,
              theme: theme,
              isActive: _isRouteActive(child.routeName, currentRoute),
              indent: 1,
            ),
          ),
      ],
    );
  }

  Widget _buildNavTile({
    required _NavMenuItem item,
    required ThemeData theme,
    required bool isActive,
    required int indent,
  }) {
    return ListTile(
      contentPadding: EdgeInsets.only(
        left: AppDimensions.md + (indent * AppDimensions.lg),
        right: AppDimensions.md,
      ),
      leading: Icon(
        item.icon,
        color: isActive
            ? theme.colorScheme.primary
            : theme.colorScheme.onSurfaceVariant,
      ),
      title: Text(
        item.label,
        style: TextStyle(
          color: isActive
              ? theme.colorScheme.primary
              : theme.colorScheme.onSurface,
          fontWeight: isActive ? FontWeight.w600 : FontWeight.normal,
        ),
      ),
      selected: isActive,
      selectedTileColor: theme.colorScheme.primary.withValues(alpha: 0.08),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
      ),
      onTap: () {
        context.goNamed(item.routeName);
        // Close drawer on mobile
        if (widget.isInDrawer) {
          Navigator.of(context).pop();
        }
      },
    );
  }

  bool _isRouteActive(String routeName, String currentRoute) {
    final routePaths = <String, String>{
      AppRoutes.userDashboard: AppRoutes.pathDashboard,
      AppRoutes.userProfile: AppRoutes.pathProfile,
      AppRoutes.userSecurity: AppRoutes.pathSecurity,
      AppRoutes.userChangePassword: AppRoutes.pathChangePassword,
      AppRoutes.userLoginHistory: AppRoutes.pathLoginHistory,
      AppRoutes.userSupport: AppRoutes.pathSupport,
    };

    final path = routePaths[routeName];
    if (path == null) return false;
    return currentRoute == path || currentRoute.startsWith('$path/');
  }

  String _getUserInitial(String? userId) {
    if (userId == null || userId.isEmpty) return 'U';
    return userId[0].toUpperCase();
  }
}
