import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/constants/app_routes.dart';
import '../../../core/constants/messages.dart';
import '../../../core/theme/app_dimensions.dart';
import '../../../providers/service_providers.dart';
import '../../../schemas/auth_schema.dart';
import '../../../shared/widgets/app_button.dart';
import '../../../shared/widgets/app_snackbar.dart';
import '../../../shared/widgets/password_field.dart';
import '../../../utils/validators.dart';
import '../widgets/auth_card_widget.dart';

class ResetPasswordScreen extends ConsumerStatefulWidget {
  const ResetPasswordScreen({super.key, this.token});

  final String? token;

  @override
  ConsumerState<ResetPasswordScreen> createState() =>
      _ResetPasswordScreenState();
}

class _ResetPasswordScreenState extends ConsumerState<ResetPasswordScreen> {
  final _formKey = GlobalKey<FormState>();
  final _passwordController = TextEditingController();
  final _confirmPasswordController = TextEditingController();

  bool _isLoading = false;
  bool _isSuccess = false;

  @override
  void initState() {
    super.initState();
    // Redirect to login if no token provided
    if (widget.token == null || widget.token!.isEmpty) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) context.goNamed(AppRoutes.login);
      });
    }
  }

  @override
  void dispose() {
    _passwordController.dispose();
    _confirmPasswordController.dispose();
    super.dispose();
  }

  Future<void> _onSubmit() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() => _isLoading = true);

    try {
      final authApiService = ref.read(authApiServiceProvider);
      final response = await authApiService.resetPassword(
        ResetPasswordRequest(
          token: widget.token!,
          newPassword: _passwordController.text,
        ),
      );

      if (!mounted) return;

      if (response.success) {
        setState(() => _isSuccess = true);
        AppSnackbar.show(
          context,
          message: Messages.passwordResetSuccess,
          type: SnackbarType.success,
        );
      } else {
        setState(() => _isLoading = false);
        AppSnackbar.show(
          context,
          message: response.message,
          type: SnackbarType.error,
        );
      }
    } catch (_) {
      if (!mounted) return;
      setState(() => _isLoading = false);
      AppSnackbar.show(
        context,
        message: Messages.passwordResetFailed,
        type: SnackbarType.error,
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    // Don't render if no token (will redirect)
    if (widget.token == null || widget.token!.isEmpty) {
      return const SizedBox.shrink();
    }

    return AuthCardWidget(
      title: 'Reset Password',
      subtitle: _isSuccess ? null : 'Enter your new password',
      child: _isSuccess ? _buildSuccessView(theme) : _buildFormView(theme),
    );
  }

  Widget _buildFormView(ThemeData theme) {
    return Form(
      key: _formKey,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          // New Password field
          PasswordField(
            controller: _passwordController,
            label: 'New Password',
            validator: Validators.password,
            textInputAction: TextInputAction.next,
          ),
          const SizedBox(height: AppDimensions.md),

          // Confirm Password field
          PasswordField(
            controller: _confirmPasswordController,
            label: 'Confirm Password',
            validator: Validators.confirmPassword(_passwordController),
            textInputAction: TextInputAction.done,
          ),
          const SizedBox(height: AppDimensions.lg),

          // Reset Password button
          AppButton(
            label: 'Reset Password',
            onPressed: _isLoading ? null : _onSubmit,
            isLoading: _isLoading,
          ),
          const SizedBox(height: AppDimensions.md),

          // Back to Login link
          Center(
            child: TextButton(
              onPressed: () => context.goNamed(AppRoutes.login),
              child: const Text('Back to Login'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSuccessView(ThemeData theme) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        // Success icon
        Icon(
          Icons.check_circle_outline,
          size: 64,
          color: theme.colorScheme.primary,
        ),
        const SizedBox(height: AppDimensions.lg),

        // Success message
        Text(
          'Your password has been reset successfully. You can now login with your new password.',
          style: theme.textTheme.bodyMedium?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
          ),
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: AppDimensions.xl),

        // Go to Login button
        AppButton(
          label: 'Go to Login',
          onPressed: () => context.goNamed(AppRoutes.login),
        ),
      ],
    );
  }
}
