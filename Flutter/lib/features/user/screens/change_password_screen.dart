import 'package:flutter/material.dart';

import '../../../core/theme/app_dimensions.dart';
import '../../../shared/widgets/app_card.dart';
import '../../shared/widgets/change_password_form_widget.dart';

/// User's change password screen.
///
/// Wraps the reusable [ChangePasswordFormWidget] in an [AppCard]
/// with a constrained max width for a clean centered layout.
class ChangePasswordScreen extends StatelessWidget {
  const ChangePasswordScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(AppDimensions.md),
      child: Center(
        child: AppCard(
          title: 'Change Password',
          subtitle: 'Update your account password',
          maxWidth: AppDimensions.formMaxWidth,
          child: const ChangePasswordFormWidget(),
        ),
      ),
    );
  }
}
