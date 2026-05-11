import 'package:flutter/material.dart';

import '../../../core/theme/app_dimensions.dart';
import '../../../shared/widgets/app_card.dart';
import '../../shared/widgets/login_history_table_widget.dart';

/// Standalone login history screen with full paginated table.
class LoginHistoryScreen extends StatelessWidget {
  const LoginHistoryScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(AppDimensions.md),
      child: Center(
        child: AppCard(
          title: 'Login History',
          subtitle: 'View your account login activity',
          maxWidth: AppDimensions.formMaxWidth,
          child: const LoginHistoryTableWidget(),
        ),
      ),
    );
  }
}
