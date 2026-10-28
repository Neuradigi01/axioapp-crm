import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/constants/app_routes.dart';
import '../../../core/theme/app_dimensions.dart';
import '../../../providers/service_providers.dart';
import '../../../shared/widgets/app_button.dart';
import '../widgets/auth_card_widget.dart';

class VerifyEmailScreen extends ConsumerStatefulWidget {
  const VerifyEmailScreen({super.key, this.token});

  final String? token;

  @override
  ConsumerState<VerifyEmailScreen> createState() => _VerifyEmailScreenState();
}

class _VerifyEmailScreenState extends ConsumerState<VerifyEmailScreen> {
  bool _isLoading = true;
  bool _isSuccess = false;
  String _message = '';

  @override
  void initState() {
    super.initState();
    _verifyEmail();
  }

  Future<void> _verifyEmail() async {
    final token = widget.token;
    if (token == null || token.isEmpty) {
      setState(() {
        _isLoading = false;
        _isSuccess = false;
        _message = 'Invalid or missing verification token.';
      });
      return;
    }

    final authApi = ref.read(authApiServiceProvider);
    final response = await authApi.verifyEmail(token);

    if (!mounted) return;

    setState(() {
      _isLoading = false;
      _isSuccess = response.success;
      _message = response.message;
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return AuthCardWidget(
      title: 'Email Verification',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          if (_isLoading) ...[
            const SizedBox(height: AppDimensions.xl),
            const Center(child: CircularProgressIndicator()),
            const SizedBox(height: AppDimensions.lg),
            Text(
              'Verifying your email...',
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: AppDimensions.xl),
          ] else ...[
            Icon(
              _isSuccess ? Icons.check_circle_outline : Icons.error_outline,
              size: 64,
              color: _isSuccess
                  ? theme.colorScheme.primary
                  : theme.colorScheme.error,
            ),
            const SizedBox(height: AppDimensions.lg),
            Text(
              _message,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: AppDimensions.xl),
            AppButton(
              label: _isSuccess ? 'Go to Login' : 'Back to Login',
              onPressed: () => context.goNamed(AppRoutes.login),
            ),
          ],
        ],
      ),
    );
  }
}
