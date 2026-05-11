import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/constants/app_constants.dart';
import '../../core/theme/app_dimensions.dart';
import '../widgets/app_drawer.dart';
import '../widgets/theme_toggle_widget.dart';
import '../widgets/user_menu_widget.dart';

/// Main user panel layout shell with AppBar, Drawer, and content area.
///
/// Features:
/// - AppBar with hamburger menu, app name, notification bell (Phase 8),
///   profile dropdown, and theme toggle
/// - Navigation drawer with dynamic menu items
/// - Responsive: overlay drawer on mobile, persistent on desktop
class UserLayout extends ConsumerWidget {
  const UserLayout({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final screenWidth = MediaQuery.sizeOf(context).width;
    final isDesktop = screenWidth >= AppDimensions.breakpointDesktop;

    if (isDesktop) {
      return _buildDesktopLayout(context);
    }

    return _buildMobileLayout(context);
  }

  Widget _buildMobileLayout(BuildContext context) {
    return Scaffold(
      appBar: _buildAppBar(context),
      drawer: const AppDrawer(),
      body: child,
    );
  }

  Widget _buildDesktopLayout(BuildContext context) {
    return Scaffold(
      appBar: _buildAppBar(context, showMenuButton: false),
      body: Row(
        children: [
          const SizedBox(
            width: AppDimensions.drawerWidth,
            child: AppDrawerContent(),
          ),
          const VerticalDivider(width: 1, thickness: 1),
          Expanded(child: child),
        ],
      ),
    );
  }

  AppBar _buildAppBar(BuildContext context, {bool showMenuButton = true}) {
    return AppBar(
      leading: showMenuButton
          ? IconButton(
              icon: const Icon(Icons.menu),
              tooltip: 'Open navigation menu',
              onPressed: () => Scaffold.of(context).openDrawer(),
            )
          : null,
      automaticallyImplyLeading: false,
      title: const Text(AppConstants.appName),
      actions: const [
        // Notification bell — added in Phase 8
        UserMenuWidget(),
        ThemeToggleWidget(),
        SizedBox(width: AppDimensions.sm),
      ],
    );
  }
}
