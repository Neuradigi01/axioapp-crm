import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/constants/messages.dart';
import '../../../core/theme/app_dimensions.dart';
import '../../../providers/service_providers.dart';
import '../../../schemas/change_password_schema.dart';
import '../../../shared/widgets/app_button.dart';
import '../../../shared/widgets/app_snackbar.dart';
import '../../../shared/widgets/password_field.dart';
import '../../../utils/validators.dart';

/// Reusable change password form widget.
///
/// Contains old password, new password, and confirm password fields
/// with validation and API submission. Used by both user and admin
/// change password screens.
class ChangePasswordFormWidget extends ConsumerStatefulWidget {
  const ChangePasswordFormWidget({super.key});

  @override
  ConsumerState<ChangePasswordFormWidget> createState() =>
      _ChangePasswordFormWidgetState();
}

class _ChangePasswordFormWidgetState
    extends ConsumerState<ChangePasswordFormWidget> {
  final _formKey = GlobalKey<FormState>();
  final _oldPasswordController = TextEditingController();
  final _newPasswordController = TextEditingController();
  final _confirmPasswordController = TextEditingController();

  bool _isLoading = false;

  @override
  void dispose() {
    _oldPasswordController.dispose();
    _newPasswordController.dispose();
    _confirmPasswordController.dispose();
    super.dispose();
  }

  Future<void> _onSubmit() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() => _isLoading = true);

    try {
      final api = ref.read(changePasswordApiServiceProvider);
      final request = ChangePasswordRequest(
        oldPassword: _oldPasswordController.text,
        newPassword: _newPasswordController.text,
      );
      final response = await api.changePassword(request);

      if (!mounted) return;

      if (response.success) {
        _oldPasswordController.clear();
        _newPasswordController.clear();
        _confirmPasswordController.clear();
        _formKey.currentState!.reset();
        AppSnackbar.show(
          context,
          message: Messages.passwordChanged,
          type: SnackbarType.success,
        );
      } else {
        AppSnackbar.show(
          context,
          message: response.message.isNotEmpty
              ? response.message
              : Messages.passwordChangeFailed,
          type: SnackbarType.error,
        );
      }
    } catch (_) {
      if (!mounted) return;
      AppSnackbar.show(
        context,
        message: Messages.errorGeneric,
        type: SnackbarType.error,
      );
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Form(
      key: _formKey,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          PasswordField(
            controller: _oldPasswordController,
            label: 'Current Password',
            validator: Validators.required,
            textInputAction: TextInputAction.next,
          ),
          const SizedBox(height: AppDimensions.md),
          PasswordField(
            controller: _newPasswordController,
            label: 'New Password',
            validator: Validators.password,
            textInputAction: TextInputAction.next,
          ),
          const SizedBox(height: AppDimensions.md),
          PasswordField(
            controller: _confirmPasswordController,
            label: 'Confirm New Password',
            validator: Validators.confirmPassword(_newPasswordController),
            textInputAction: TextInputAction.done,
          ),
          const SizedBox(height: AppDimensions.lg),
          AppButton(
            label: 'Change Password',
            onPressed: _isLoading ? null : _onSubmit,
            isLoading: _isLoading,
            icon: Icons.lock_outline,
          ),
        ],
      ),
    );
  }
}
