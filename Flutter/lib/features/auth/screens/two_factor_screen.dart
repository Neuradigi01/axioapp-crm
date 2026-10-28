import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../../core/constants/app_constants.dart';
import '../../../core/constants/app_routes.dart';
import '../../../core/constants/messages.dart';
import '../../../core/theme/app_dimensions.dart';
import '../../../providers/auth_provider.dart';
import '../../../providers/service_providers.dart';
import '../../../schemas/auth_schema.dart';
import '../../../shared/widgets/app_button.dart';
import '../../../shared/widgets/app_snackbar.dart';
import '../../../shared/widgets/otp_input_widget.dart';
import '../widgets/auth_card_widget.dart';

/// Key for persisting remembered identifier in SharedPreferences.
const _keyRememberedIdentifier = 'remembered_identifier';

class TwoFactorScreen extends ConsumerStatefulWidget {
  const TwoFactorScreen({super.key, this.extra});

  /// Data passed from the login screen via GoRouter extra.
  final Map<String, dynamic>? extra;

  @override
  ConsumerState<TwoFactorScreen> createState() => _TwoFactorScreenState();
}

class _TwoFactorScreenState extends ConsumerState<TwoFactorScreen> {
  final _otpKey = GlobalKey<OtpInputWidgetState>();

  late String _identifier;
  late String _password;
  late String _currentMethod;
  late List<String> _availableMethods;
  late bool _rememberMe;

  bool _isVerifying = false;
  bool _isSwitching = false;
  bool _showMethodSelection = false;
  bool _hasError = false;
  String? _selectedMethod;

  // Expiry countdown (5 minutes)
  late int _expirySeconds;
  Timer? _expiryTimer;

  // Resend cooldown (30 seconds)
  int _resendCooldown = 0;
  Timer? _resendTimer;

  @override
  void initState() {
    super.initState();

    final extra = widget.extra;
    if (extra == null) {
      // No data — redirect back to login after build
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) context.goNamed(AppRoutes.login);
      });
      return;
    }

    _identifier = extra['identifier'] as String? ?? '';
    _password = extra['password'] as String? ?? '';
    _currentMethod = extra['method'] as String? ?? AppConstants.tfaMethodAuthenticator;
    _availableMethods = List<String>.from(extra['availableMethods'] as List? ?? []);
    _rememberMe = extra['rememberMe'] as bool? ?? false;

    _expirySeconds = AppConstants.otpExpirySeconds;
    _startExpiryTimer();
    _startResendCooldown();
  }

  @override
  void dispose() {
    _expiryTimer?.cancel();
    _resendTimer?.cancel();
    super.dispose();
  }

  void _startExpiryTimer() {
    _expiryTimer?.cancel();
    setState(() => _expirySeconds = AppConstants.otpExpirySeconds);
    _expiryTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (_expirySeconds > 0) {
        setState(() => _expirySeconds--);
      } else {
        _expiryTimer?.cancel();
      }
    });
  }

  void _startResendCooldown() {
    _resendTimer?.cancel();
    setState(() => _resendCooldown = AppConstants.resendCooldownSeconds);
    _resendTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (_resendCooldown > 0) {
        setState(() => _resendCooldown--);
      } else {
        _resendTimer?.cancel();
      }
    });
  }

  String _formatTime(int seconds) {
    final m = seconds ~/ 60;
    final s = seconds % 60;
    return '${m.toString().padLeft(2, '0')}:${s.toString().padLeft(2, '0')}';
  }

  String get _methodLabel =>
      AppConstants.tfaMethodLabels[_currentMethod] ?? _currentMethod;

  bool get _isOtpMethod =>
      _currentMethod == AppConstants.tfaMethodEmail ||
      _currentMethod == AppConstants.tfaMethodSms;

  Future<void> _onVerify(String code) async {
    if (code.length != AppConstants.otpLength) return;
    if (_expirySeconds <= 0) {
      if (!mounted) return;
      AppSnackbar.show(
        context,
        message: 'Code has expired. Please request a new one.',
        type: SnackbarType.error,
      );
      return;
    }

    setState(() {
      _isVerifying = true;
      _hasError = false;
    });

    try {
      final request = LoginRequest(
        identifier: _identifier,
        password: _password,
        twoFactorCode: code,
        twoFactorMethod: _currentMethod,
      );

      final authApiService = ref.read(authApiServiceProvider);
      final response = await authApiService.login(request);

      if (!mounted) return;

      if (response.success && response.data != null) {
        final loginData = LoginData.fromJson(
          response.data as Map<String, dynamic>,
        );

        // Save remembered identifier if enabled
        if (_rememberMe) {
          final prefs = await SharedPreferences.getInstance();
          await prefs.setString(_keyRememberedIdentifier, _identifier);
        }

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

      // Verification failed
      setState(() => _hasError = true);
      _otpKey.currentState?.clear();
      AppSnackbar.show(
        context,
        message: response.message.isNotEmpty
            ? response.message
            : Messages.tfaVerifyFailed,
        type: SnackbarType.error,
      );
    } catch (_) {
      if (!mounted) return;
      setState(() => _hasError = true);
      _otpKey.currentState?.clear();
      AppSnackbar.show(
        context,
        message: Messages.errorGeneric,
        type: SnackbarType.error,
      );
    } finally {
      if (mounted) {
        setState(() => _isVerifying = false);
      }
    }
  }

  Future<void> _onResend() async {
    if (_resendCooldown > 0 || !_isOtpMethod) return;

    setState(() => _isSwitching = true);

    try {
      final request = TryAnotherWayRequest(
        identifier: _identifier,
        password: _password,
        userType: AppConstants.roleUser,
        method: _currentMethod,
      );

      final authApiService = ref.read(authApiServiceProvider);
      final response = await authApiService.tryAnotherWay2fa(request);

      if (!mounted) return;

      if (response.success) {
        _otpKey.currentState?.clear();
        _startExpiryTimer();
        _startResendCooldown();
        setState(() => _hasError = false);
        AppSnackbar.show(
          context,
          message: Messages.tfaCodeResent,
          type: SnackbarType.success,
        );
      } else {
        AppSnackbar.show(
          context,
          message: response.message.isNotEmpty
              ? response.message
              : Messages.tfaCodeResendFailed,
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
      if (mounted) {
        setState(() => _isSwitching = false);
      }
    }
  }

  Future<void> _onSwitchMethod() async {
    if (_selectedMethod == null || _selectedMethod == _currentMethod) return;

    setState(() => _isSwitching = true);

    try {
      final request = TryAnotherWayRequest(
        identifier: _identifier,
        password: _password,
        userType: AppConstants.roleUser,
        method: _selectedMethod!,
      );

      final authApiService = ref.read(authApiServiceProvider);
      final response = await authApiService.tryAnotherWay2fa(request);

      if (!mounted) return;

      if (response.success && response.data != null) {
        final data = TryAnotherWayData.fromJson(
          response.data as Map<String, dynamic>,
        );

        _otpKey.currentState?.clear();
        _startExpiryTimer();
        _startResendCooldown();

        setState(() {
          _currentMethod = data.method;
          _availableMethods = data.availableMethods;
          _showMethodSelection = false;
          _selectedMethod = null;
          _hasError = false;
        });

        AppSnackbar.show(
          context,
          message: Messages.tfaMethodSwitched,
          type: SnackbarType.success,
        );
      } else {
        AppSnackbar.show(
          context,
          message: response.message.isNotEmpty
              ? response.message
              : Messages.tfaMethodSwitchFailed,
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
      if (mounted) {
        setState(() => _isSwitching = false);
      }
    }
  }

  void _onBackToLogin() {
    context.goNamed(AppRoutes.login);
  }

  @override
  Widget build(BuildContext context) {
    if (widget.extra == null) {
      return const SizedBox.shrink();
    }

    final theme = Theme.of(context);

    return AuthCardWidget(
      title: 'Two-Factor Authentication',
      subtitle: _showMethodSelection
          ? 'Choose a verification method'
          : 'Enter the verification code from your $_methodLabel',
      child: _showMethodSelection
          ? _buildMethodSelection(theme)
          : _buildOtpEntry(theme),
    );
  }

  Widget _buildOtpEntry(ThemeData theme) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        // Current method indicator
        Container(
          padding: const EdgeInsets.symmetric(
            horizontal: AppDimensions.md,
            vertical: AppDimensions.sm,
          ),
          decoration: BoxDecoration(
            color: theme.colorScheme.primaryContainer.withValues(alpha: 0.3),
            borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(
                _methodIcon(_currentMethod),
                size: 20,
                color: theme.colorScheme.primary,
              ),
              const SizedBox(width: AppDimensions.sm),
              Text(
                _methodLabel,
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: theme.colorScheme.primary,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: AppDimensions.lg),

        // OTP input
        OtpInputWidget(
          key: _otpKey,
          onCompleted: _onVerify,
          hasError: _hasError,
          enabled: !_isVerifying,
          onChanged: (_) {
            if (_hasError) setState(() => _hasError = false);
          },
        ),
        const SizedBox(height: AppDimensions.md),

        // Expiry countdown
        Text(
          _expirySeconds > 0
              ? 'Code expires in ${_formatTime(_expirySeconds)}'
              : 'Code has expired',
          style: theme.textTheme.bodySmall?.copyWith(
            color: _expirySeconds > 60
                ? theme.colorScheme.onSurfaceVariant
                : theme.colorScheme.error,
          ),
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: AppDimensions.md),

        // Verify button
        AppButton(
          label: 'Verify',
          onPressed: _isVerifying
              ? null
              : () => _onVerify(_otpKey.currentState?.code ?? ''),
          isLoading: _isVerifying,
        ),
        const SizedBox(height: AppDimensions.md),

        // Resend OTP (only for email/SMS)
        if (_isOtpMethod)
          Center(
            child: TextButton(
              onPressed: _resendCooldown > 0 || _isSwitching ? null : _onResend,
              child: Text(
                _resendCooldown > 0
                    ? 'Resend code in ${_resendCooldown}s'
                    : 'Resend code',
              ),
            ),
          ),

        // Try another way (only if multiple methods available)
        if (_availableMethods.length > 1)
          Center(
            child: TextButton(
              onPressed: _isSwitching
                  ? null
                  : () {
                      setState(() {
                        _showMethodSelection = true;
                        _selectedMethod = null;
                      });
                    },
              child: const Text('Try another way'),
            ),
          ),
        const SizedBox(height: AppDimensions.sm),

        // Back to login
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(
              'Having trouble? ',
              style: theme.textTheme.bodyMedium,
            ),
            TextButton(
              onPressed: _onBackToLogin,
              style: TextButton.styleFrom(
                padding: EdgeInsets.zero,
                minimumSize: Size.zero,
                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              ),
              child: const Text('Back to Login'),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildMethodSelection(ThemeData theme) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        // Method radio buttons
        RadioGroup<String>(
          groupValue: _selectedMethod ?? '',
          onChanged: (value) => setState(() => _selectedMethod = value),
          child: Column(
            children: _availableMethods.map((method) {
              final label = AppConstants.tfaMethodLabels[method] ?? method;
              return RadioListTile<String>(
                value: method,
                title: Row(
                  children: [
                    Icon(
                      _methodIcon(method),
                      size: 20,
                      color: _selectedMethod == method
                          ? theme.colorScheme.primary
                          : theme.colorScheme.onSurfaceVariant,
                    ),
                    const SizedBox(width: AppDimensions.sm),
                    Text(label),
                  ],
                ),
                contentPadding: EdgeInsets.zero,
                dense: true,
              );
            }).toList(),
          ),
        ),
        const SizedBox(height: AppDimensions.md),

        // Switch method button
        AppButton(
          label: 'Continue',
          onPressed: _selectedMethod == null || _isSwitching
              ? null
              : _onSwitchMethod,
          isLoading: _isSwitching,
        ),
        const SizedBox(height: AppDimensions.sm),

        // Cancel — go back to OTP entry
        Center(
          child: TextButton(
            onPressed: () => setState(() {
              _showMethodSelection = false;
              _selectedMethod = null;
            }),
            child: const Text('Cancel'),
          ),
        ),
      ],
    );
  }

  IconData _methodIcon(String method) {
    switch (method) {
      case AppConstants.tfaMethodAuthenticator:
        return Icons.security;
      case AppConstants.tfaMethodEmail:
        return Icons.email_outlined;
      case AppConstants.tfaMethodSms:
        return Icons.sms_outlined;
      default:
        return Icons.lock_outline;
    }
  }
}
