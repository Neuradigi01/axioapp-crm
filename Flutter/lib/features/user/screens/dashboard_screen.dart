import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/config/app_config.dart';
import '../../../core/theme/app_dimensions.dart';
import '../../../core/theme/color_schemes.dart';
import '../../../models/dashboard_data.dart';
import '../../../providers/user_provider.dart';
import '../../../shared/widgets/app_error_widget.dart';
import '../../../shared/widgets/app_loading_indicator.dart';
import '../widgets/dashboard_tile_widget.dart';

/// Dashboard screen with greeting, profile image, and metric tiles grid.
class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final dashboardAsync = ref.watch(dashboardProvider);

    return dashboardAsync.when(
      loading: () => const AppLoadingIndicator(message: 'Loading dashboard...'),
      error: (error, _) => AppErrorWidget(
        message: 'Failed to load dashboard data.',
        onRetry: () => ref.invalidate(dashboardProvider),
      ),
      data: (data) {
        if (data == null) {
          return AppErrorWidget(
            message: 'Failed to load dashboard data.',
            onRetry: () => ref.invalidate(dashboardProvider),
          );
        }

        return _DashboardContent(data: data);
      },
    );
  }
}

class _DashboardContent extends StatelessWidget {
  const _DashboardContent({required this.data});

  final DashboardData data;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;
    final screenWidth = MediaQuery.sizeOf(context).width;
    final crossAxisCount = screenWidth >= AppDimensions.breakpointTablet ? 4 : 2;

    return SingleChildScrollView(
      padding: const EdgeInsets.all(AppDimensions.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Greeting section
          _buildGreeting(theme, isDark),
          const SizedBox(height: AppDimensions.lg),

          // Dashboard tiles grid
          GridView.count(
            crossAxisCount: crossAxisCount,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            mainAxisSpacing: AppDimensions.md,
            crossAxisSpacing: AppDimensions.md,
            childAspectRatio: 2.2,
            children: _buildTiles(isDark),
          ),
        ],
      ),
    );
  }

  Widget _buildGreeting(ThemeData theme, bool isDark) {
    return Row(
      children: [
        // Profile image or initials
        _buildAvatar(theme),
        const SizedBox(width: AppDimensions.md),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Welcome, ${data.firstName}!',
                style: theme.textTheme.headlineSmall,
              ),
              const SizedBox(height: AppDimensions.xs),
              Text(
                data.email,
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildAvatar(ThemeData theme) {
    final initials = '${data.firstName[0]}${data.lastName[0]}'.toUpperCase();

    if (data.profileImage != null && data.profileImage!.isNotEmpty) {
      final imageUrl = '${AppConfig.apiBaseUrl}${data.profileImage}';
      return CircleAvatar(
        radius: AppDimensions.avatarSizeLg / 2,
        backgroundColor: theme.colorScheme.primaryContainer,
        child: ClipOval(
          child: CachedNetworkImage(
            imageUrl: imageUrl,
            width: AppDimensions.avatarSizeLg,
            height: AppDimensions.avatarSizeLg,
            fit: BoxFit.cover,
            placeholder: (_, __) => _InitialsAvatar(
              initials: initials,
              theme: theme,
            ),
            errorWidget: (_, __, ___) => _InitialsAvatar(
              initials: initials,
              theme: theme,
            ),
          ),
        ),
      );
    }

    return CircleAvatar(
      radius: AppDimensions.avatarSizeLg / 2,
      backgroundColor: theme.colorScheme.primary,
      child: Text(
        initials,
        style: theme.textTheme.headlineSmall?.copyWith(
          color: theme.colorScheme.onPrimary,
          fontWeight: FontWeight.bold,
        ),
      ),
    );
  }

  List<Widget> _buildTiles(bool isDark) {
    return [
      DashboardTileWidget(
        icon: Icons.people_outlined,
        label: 'Referral Count',
        value: data.referralCount.toString(),
        color: isDark ? AppColors.infoDark : AppColors.info,
      ),
      DashboardTileWidget(
        icon: Icons.support_agent_outlined,
        label: 'Open Tickets',
        value: data.openTickets.toString(),
        color: isDark ? AppColors.warningDark : AppColors.warning,
      ),
      DashboardTileWidget(
        icon: Icons.shield_outlined,
        label: '2FA Status',
        value: data.twoFactorEnabled ? 'Enabled' : 'Disabled',
        color: isDark ? AppColors.successDark : AppColors.success,
      ),
      DashboardTileWidget(
        icon: Icons.verified_user_outlined,
        label: 'Account Status',
        value: 'Active',
        color: isDark ? AppColors.successDark : AppColors.success,
      ),
    ];
  }
}

class _InitialsAvatar extends StatelessWidget {
  const _InitialsAvatar({
    required this.initials,
    required this.theme,
  });

  final String initials;
  final ThemeData theme;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: AppDimensions.avatarSizeLg,
      height: AppDimensions.avatarSizeLg,
      alignment: Alignment.center,
      color: theme.colorScheme.primary,
      child: Text(
        initials,
        style: theme.textTheme.headlineSmall?.copyWith(
          color: theme.colorScheme.onPrimary,
          fontWeight: FontWeight.bold,
        ),
      ),
    );
  }
}
