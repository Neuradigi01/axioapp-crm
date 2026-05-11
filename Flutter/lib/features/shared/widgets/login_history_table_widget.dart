import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:url_launcher/url_launcher.dart';

import 'package:template_app/core/theme/app_dimensions.dart';
import 'package:template_app/models/login_history.dart';
import 'package:template_app/providers/login_history_provider.dart';
import 'package:template_app/shared/widgets/app_confirm_dialog.dart';
import 'package:template_app/shared/widgets/app_pagination.dart';
import 'package:template_app/shared/widgets/app_snackbar.dart';
import 'package:template_app/shared/widgets/app_status_badge.dart';

/// Reusable login history table with pagination and session logout.
class LoginHistoryTableWidget extends ConsumerStatefulWidget {
  const LoginHistoryTableWidget({super.key});

  @override
  ConsumerState<LoginHistoryTableWidget> createState() =>
      _LoginHistoryTableWidgetState();
}

class _LoginHistoryTableWidgetState
    extends ConsumerState<LoginHistoryTableWidget> {
  int? _logoutingTokenId;

  @override
  void initState() {
    super.initState();
    Future.microtask(() {
      ref.read(loginHistoryProvider.notifier).fetchPage();
    });
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(loginHistoryProvider);
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;

    if (state.isLoading && state.records.isEmpty) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(AppDimensions.xl),
          child: CircularProgressIndicator(),
        ),
      );
    }

    if (state.error != null && state.records.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(AppDimensions.xl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.error_outline,
                  size: 48, color: colorScheme.error),
              const SizedBox(height: AppDimensions.md),
              Text(
                state.error!,
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: colorScheme.error,
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: AppDimensions.md),
              TextButton.icon(
                onPressed: () =>
                    ref.read(loginHistoryProvider.notifier).fetchPage(),
                icon: const Icon(Icons.refresh),
                label: const Text('Retry'),
              ),
            ],
          ),
        ),
      );
    }

    if (state.records.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(AppDimensions.xl),
          child: Text(
            'No login history found.',
            style: theme.textTheme.bodyMedium?.copyWith(
              color: colorScheme.onSurfaceVariant,
            ),
          ),
        ),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (state.isLoading)
          const LinearProgressIndicator(),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: DataTable(
            headingRowColor: WidgetStateProperty.all(
              colorScheme.surfaceContainerHighest.withValues(alpha: 0.5),
            ),
            columns: const [
              DataColumn(label: Text('Date & Time')),
              DataColumn(label: Text('IP Address')),
              DataColumn(label: Text('Device')),
              DataColumn(label: Text('Browser')),
              DataColumn(label: Text('Location')),
              DataColumn(label: Text('Status')),
              DataColumn(label: Text('Actions')),
            ],
            rows: state.records.map((record) {
              return _buildRow(record, theme, colorScheme);
            }).toList(),
          ),
        ),
        AppPagination(
          currentPage: state.pageIndex,
          totalPages: state.totalPages,
          totalCount: state.totalCount,
          pageSize: state.pageSize,
          pageSizeOptions: const [10, 25, 50, 100],
          onPageChanged: (page) {
            ref.read(loginHistoryProvider.notifier).fetchPage(pageIndex: page);
          },
          onPageSizeChanged: (size) {
            ref
                .read(loginHistoryProvider.notifier)
                .fetchPage(pageIndex: 1, pageSize: size);
          },
        ),
      ],
    );
  }

  DataRow _buildRow(
    LoginHistoryRecord record,
    ThemeData theme,
    ColorScheme colorScheme,
  ) {
    final isCurrent = _isCurrentSession(record);
    final isActive = _isActiveSession(record);

    return DataRow(
      color: isCurrent
          ? WidgetStateProperty.all(
              colorScheme.primaryContainer.withValues(alpha: 0.3))
          : null,
      cells: [
        // Date & Time
        DataCell(Text(
          _formatDate(record.onDate),
          style: theme.textTheme.bodySmall,
        )),

        // IP Address
        DataCell(Text(
          record.ipAddress ?? '-',
          style: theme.textTheme.bodySmall,
        )),

        // Device
        DataCell(Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              _getDeviceIcon(record.deviceType),
              size: 16,
              color: colorScheme.onSurfaceVariant,
            ),
            const SizedBox(width: AppDimensions.xs),
            Text(
              _formatDevice(record),
              style: theme.textTheme.bodySmall,
            ),
          ],
        )),

        // Browser
        DataCell(Text(
          _formatBrowser(record),
          style: theme.textTheme.bodySmall,
        )),

        // Location
        DataCell(_buildLocationCell(record, theme, colorScheme)),

        // Status
        DataCell(_buildStatusCell(record, isCurrent)),

        // Actions
        DataCell(
          isCurrent
              ? Text(
                  'This device',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: colorScheme.primary,
                    fontWeight: FontWeight.w500,
                  ),
                )
              : isActive
                  ? _buildLogoutButton(record, colorScheme)
                  : const SizedBox.shrink(),
        ),
      ],
    );
  }

  Widget _buildLocationCell(
    LoginHistoryRecord record,
    ThemeData theme,
    ColorScheme colorScheme,
  ) {
    final location = _formatLocation(record);
    final hasCoordinates =
        record.latitude != null && record.longitude != null;

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(location, style: theme.textTheme.bodySmall),
        if (hasCoordinates) ...[
          const SizedBox(width: AppDimensions.xs),
          InkWell(
            onTap: () => _openMapsLink(record.latitude!, record.longitude!),
            borderRadius: BorderRadius.circular(AppDimensions.radiusXs),
            child: Icon(
              Icons.map_outlined,
              size: 16,
              color: colorScheme.primary,
            ),
          ),
        ],
      ],
    );
  }

  Widget _buildStatusCell(LoginHistoryRecord record, bool isCurrent) {
    if (isCurrent) {
      return const AppStatusBadge(label: 'Active');
    }

    final status = record.loginStatus.toLowerCase();
    String label;
    switch (status) {
      case 'active':
        label = 'Active';
      case '2fa_pending':
        label = 'In Progress';
      case 'failed':
        label = 'Inactive';
      default:
        label = record.logoutTimestamp != null ? 'Inactive' : 'Active';
    }

    return AppStatusBadge(label: label);
  }

  Widget _buildLogoutButton(
    LoginHistoryRecord record,
    ColorScheme colorScheme,
  ) {
    final isLogouting = _logoutingTokenId == record.tokenId;

    return SizedBox(
      height: 32,
      child: TextButton(
        onPressed: isLogouting ? null : () => _handleLogoutSession(record),
        style: TextButton.styleFrom(
          foregroundColor: colorScheme.error,
          padding: const EdgeInsets.symmetric(horizontal: AppDimensions.sm),
        ),
        child: isLogouting
            ? SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: colorScheme.error,
                ),
              )
            : const Text('Logout'),
      ),
    );
  }

  Future<void> _handleLogoutSession(LoginHistoryRecord record) async {
    final confirmed = await AppConfirmDialog.show(
      context,
      title: 'Logout Session',
      message:
          'Are you sure you want to logout this session? The user will be signed out from that device.',
      confirmLabel: 'Logout',
      isDestructive: true,
    );

    if (!confirmed || !mounted) return;

    setState(() => _logoutingTokenId = record.tokenId);

    final success = await ref
        .read(loginHistoryProvider.notifier)
        .logoutSession(record.tokenId);

    if (!mounted) return;
    setState(() => _logoutingTokenId = null);

    AppSnackbar.show(
      context,
      message: success
          ? 'Session logged out successfully.'
          : 'Failed to logout session.',
      type: success ? SnackbarType.success : SnackbarType.error,
    );
  }

  bool _isCurrentSession(LoginHistoryRecord record) {
    // Current session is the most recent active session without a logout timestamp
    return record.loginStatus.toLowerCase() == 'active' &&
        record.logoutTimestamp == null &&
        record.byAdminTokenId == null;
  }

  bool _isActiveSession(LoginHistoryRecord record) {
    return record.loginStatus.toLowerCase() == 'active' &&
        record.logoutTimestamp == null;
  }

  String _formatDate(String dateStr) {
    try {
      final date = DateTime.parse(dateStr);
      return DateFormat('MMM dd, yyyy HH:mm').format(date);
    } catch (_) {
      return dateStr;
    }
  }

  String _formatDevice(LoginHistoryRecord record) {
    final parts = <String>[];
    if (record.device != null && record.device!.isNotEmpty) {
      parts.add(record.device!);
    }
    if (record.os != null && record.os!.isNotEmpty) {
      parts.add(record.os!);
      if (record.osVersion != null && record.osVersion!.isNotEmpty) {
        parts.add(record.osVersion!);
      }
    }
    return parts.isEmpty ? '-' : parts.join(' ');
  }

  String _formatBrowser(LoginHistoryRecord record) {
    if (record.browser == null || record.browser!.isEmpty) return '-';
    if (record.browserVersion != null && record.browserVersion!.isNotEmpty) {
      return '${record.browser} ${record.browserVersion}';
    }
    return record.browser!;
  }

  String _formatLocation(LoginHistoryRecord record) {
    final parts = <String>[];
    if (record.city != null && record.city!.isNotEmpty) {
      parts.add(record.city!);
    }
    if (record.country != null && record.country!.isNotEmpty) {
      parts.add(record.country!);
    }
    return parts.isEmpty ? '-' : parts.join(', ');
  }

  IconData _getDeviceIcon(String? deviceType) {
    switch (deviceType?.toLowerCase()) {
      case 'mobile':
      case 'smartphone':
        return Icons.smartphone;
      case 'tablet':
        return Icons.tablet;
      case 'desktop':
      case 'pc':
        return Icons.desktop_windows;
      default:
        return Icons.devices;
    }
  }

  Future<void> _openMapsLink(double latitude, double longitude) async {
    final uri = Uri.parse(
      'https://www.google.com/maps?q=$latitude,$longitude',
    );
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
  }
}
