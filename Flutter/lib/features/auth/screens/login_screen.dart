import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../../core/constants/app_routes.dart';
import '../../../core/constants/messages.dart';
import '../../../core/theme/app_dimensions.dart';
import '../../../providers/auth_provider.dart';
import '../../../providers/service_providers.dart';
import '../../../schemas/auth_schema.dart';
import '../../../shared/widgets/app_button.dart';
import '../../../shared/widgets/app_snackbar.dart';
import '../../../shared/widgets/app_text_field.dart';
import '../../../shared/widgets/captcha_widget.dart';
import '../../../shared/widgets/password_field.dart';
import '../../../utils/validators.dart';
import '../widgets/auth_card_widget.dart';

/// Key for persisting remembered identifier in SharedPreferences.
const _keyRememberedIdentifier = 'remembered_identifier';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _captchaKey = GlobalKey<CaptchaWidgetState>();

  final _identifierController = TextEditingController();
  final _passwordController = TextEditingController();

  bool _rememberMe = false;
  bool _isLoading = false;
  String? _captchaType;

  @override
  void initState() {
    super.initState();
    _loadRememberedIdentifier();
  }

  @override
  void dispose() {
    _identifierController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _loadRememberedIdentifier() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString(_keyRememberedIdentifier);
    if (saved != null && saved.isNotEmpty) {
      _identifierController.text = saved;
      setState(() => _rememberMe = true);
    }
  }

  Future<void> _saveRememberedIdentifier(String identifier) async {
    final prefs = await SharedPreferences.getInstance();
    if (_rememberMe) {
      await prefs.setString(_keyRememberedIdentifier, identifier);
    } else {
      await prefs.remove(_keyRememberedIdentifier);
    }
  }

  void _onCaptchaTypeChanged(String? type) {
    setState(() => _captchaType = type);
  }

  Future<void> _onSignIn() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() => _isLoading = true);

    try {
      // Execute captcha if active
      CaptchaResult? captchaResult;
      if (_captchaType != null) {
        captchaResult = await _captchaKey.currentState?.execute();
      }

      // Build login request
      final request = LoginRequest(
        identifier: _identifierController.text.trim(),
        password: _passwordController.text,
        captchaToken: captchaResult?.token,
        captchaAnswer: captchaResult?.answer,
      );

      // Call login API
      final authApiService = ref.read(authApiServiceProvider);
      final response = await authApiService.login(request);

      if (!mounted) return;

      // Success — save token and navigate to dashboard
      if (response.success && response.data != null) {
        final loginData = LoginData.fromJson(
          response.data as Map<String, dynamic>,
        );

        await _saveRememberedIdentifier(_identifierController.text.trim());

        await ref.read(authProvider.notifier).login(
              token: loginData.token,
              userId: loginData.userId,
              role: loginData.role,
              accessRights: const [],
            );

        if (!mounted) return;
        context.goNamed(AppRoutes.userDashboard);
        return;
      }

      // Failure with data — check for 2FA or email verification
      if (!response.success && response.data != null) {
        final data = response.data as Map<String, dynamic>;

        // 2FA required
        if (data['requires_2fa'] == true) {
          final tfaData = TfaRequiredData.fromJson(data);
          if (!mounted) return;
          context.goNamed(
            AppRoutes.twoFactorAuthentication,
            extra: {
              'identifier': _identifierController.text.trim(),
              'password': _passwordController.text,
              'method': tfaData.method,
              'availableMethods': tfaData.availableMethods,
              'rememberMe': _rememberMe,
            },
          );
          return;
        }

        // Email verification required
        if (data['requires_email_verification'] == true) {
          if (!mounted) return;
          context.goNamed(
            AppRoutes.emailVerificationNotice,
            extra: {'email': _identifierController.text.trim()},
          );
          return;
        }
      }

      // General failure — show error and refresh captcha
      if (!mounted) return;
      AppSnackbar.show(
        context,
        message: response.message.isNotEmpty
            ? response.message
            : Messages.loginFailed,
        type: SnackbarType.error,
      );
      _captchaKey.currentState?.refresh();
    } catch (_) {
      if (!mounted) return;
      AppSnackbar.show(
        context,
        message: Messages.errorGeneric,
        type: SnackbarType.error,
      );
      _captchaKey.currentState?.refresh();
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return AuthCardWidget(
      title: 'Sign In',
      subtitle: 'Enter your credentials to continue',
      child: Form(
        key: _formKey,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          mainAxisSize: MainAxisSize.min,
          children: [
            // Identifier field
            AppTextField(
              controller: _identifierController,
              label: 'Username or Email',
              prefixIcon: Icons.person_outline,
              validator: Validators.required,
              textInputAction: TextInputAction.next,
              autofocus: true,
            ),
            const SizedBox(height: AppDimensions.md),

            // Password field
            PasswordField(
              controller: _passwordController,
              validator: Validators.required,
              textInputAction: TextInputAction.done,
            ),
            const SizedBox(height: AppDimensions.sm),

            // Remember Me + Forgot Password row
            Row(
              children: [
                // Remember Me
                SizedBox(
                  height: AppDimensions.minTouchTarget,
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Checkbox(
                        value: _rememberMe,
                        onChanged: (value) {
                          setState(() => _rememberMe = value ?? false);
                        },
                      ),
                      GestureDetector(
                        onTap: () {
                          setState(() => _rememberMe = !_rememberMe);
                        },
                        child: Text(
                          'Remember Me',
                          style: theme.textTheme.bodyMedium,
                        ),
                      ),
                    ],
                  ),
                ),
                const Spacer(),
                // Forgot Password
                TextButton(
                  onPressed: () => context.goNamed(AppRoutes.forgotPassword),
                  child: const Text('Forgot Password?'),
                ),
              ],
            ),
            const SizedBox(height: AppDimensions.md),

            // CAPTCHA
            CaptchaWidget(
              key: _captchaKey,
              onTokenChanged: (_) {},
              onTypeChanged: _onCaptchaTypeChanged,
            ),
            if (_captchaType != null) const SizedBox(height: AppDimensions.md),

            // Sign In button
            AppButton(
              label: 'Sign In',
              onPressed: _isLoading ? null : _onSignIn,
              isLoading: _isLoading,
            ),
            const SizedBox(height: AppDimensions.md),

            // Register link
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  "Don't have an account? ",
                  style: theme.textTheme.bodyMedium,
                ),
                TextButton(
                  onPressed: () => context.goNamed(AppRoutes.register),
                  style: TextButton.styleFrom(
                    padding: EdgeInsets.zero,
                    minimumSize: Size.zero,
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                  child: const Text('Register'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
