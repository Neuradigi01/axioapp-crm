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
import '../../../shared/widgets/app_text_field.dart';
import '../../../utils/validators.dart';
import '../widgets/auth_card_widget.dart';

class ForgotPasswordScreen extends ConsumerStatefulWidget {
  const ForgotPasswordScreen({super.key});

  @override
  ConsumerState<ForgotPasswordScreen> createState() =>
      _ForgotPasswordScreenState();
}

class _ForgotPasswordScreenState extends ConsumerState<ForgotPasswordScreen> {
  final _formKey = GlobalKey<FormState>();
  final _identifierController = TextEditingController();

  bool _isLoading = false;
  bool _submitted = false;

  @override
  void dispose() {
    _identifierController.dispose();
    super.dispose();
  }

  Future<void> _onSubmit() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() => _isLoading = true);

    try {
      final authApiService = ref.read(authApiServiceProvider);
      await authApiService.forgotPassword(
        ForgotPasswordRequest(
          identifier: _identifierController.text.trim(),
        ),
      );
    } catch (_) {
      // Intentionally ignore errors to prevent email enumeration
    } finally {
      if (mounted) {
        setState(() {
          _isLoading = false;
          _submitted = true;
        });
        AppSnackbar.show(
          context,
          message: Messages.passwordResetSent,
          type: SnackbarType.success,
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return AuthCardWidget(
      title: 'Forgot Password',
      subtitle: _submitted
          ? null
          : 'Enter your email or username to receive a password reset link',
      child: _submitted ? _buildSuccessView(theme) : _buildFormView(theme),
    );
  }

  Widget _buildFormView(ThemeData theme) {
    return Form(
      key: _formKey,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          // Identifier field
          AppTextField(
            controller: _identifierController,
            label: 'Email or Username',
            prefixIcon: Icons.person_outline,
            validator: Validators.required,
            textInputAction: TextInputAction.done,
            autofocus: true,
          ),
          const SizedBox(height: AppDimensions.lg),

          // Send Reset Link button
          AppButton(
            label: 'Send Reset Link',
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
          Icons.mark_email_read_outlined,
          size: 64,
          color: theme.colorScheme.primary,
        ),
        const SizedBox(height: AppDimensions.lg),

        // Success message
        Text(
          'If an account exists with this identifier, a password reset link has been sent.',
          style: theme.textTheme.bodyMedium?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
          ),
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: AppDimensions.xl),

        // Back to Login button
        AppButton(
          label: 'Back to Login',
          onPressed: () => context.goNamed(AppRoutes.login),
        ),
      ],
    );
  }
}
