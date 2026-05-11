import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/constants/app_constants.dart';
import '../../../core/constants/messages.dart';
import '../../../core/theme/app_dimensions.dart';
import '../../../models/tfa_status.dart';
import '../../../providers/service_providers.dart';
import '../../../providers/tfa_provider.dart';
import '../../../schemas/tfa_schema.dart';
import '../../../shared/widgets/app_button.dart';
import '../../../shared/widgets/app_card.dart';
import '../../../shared/widgets/app_error_widget.dart';
import '../../../shared/widgets/app_loading_indicator.dart';
import '../../../shared/widgets/app_snackbar.dart';
import '../../../shared/widgets/otp_input_widget.dart';

/// Current view state for the 2FA settings widget.
enum _TfaView {
  status,
  setupChooseMethod,
  setupAuthenticator,
  setupOtp,
  changeMethod,
}

/// Complete 2FA management widget.
///
/// Shows current 2FA status and provides flows for:
/// - Enabling 2FA (Authenticator, Email OTP, SMS OTP)
/// - Disabling 2FA (with automatic action verification via interceptor)
/// - Changing 2FA method (with automatic action verification via interceptor)
class TfaSettingsWidget extends ConsumerStatefulWidget {
  const TfaSettingsWidget({super.key});

  @override
  ConsumerState<TfaSettingsWidget> createState() => _TfaSettingsWidgetState();
}

class _TfaSettingsWidgetState extends ConsumerState<TfaSettingsWidget> {
  final _otpKey = GlobalKey<OtpInputWidgetState>();

  _TfaView _currentView = _TfaView.status;
  String? _selectedMethod;

  // Setup authenticator data
  String? _qrCodeBase64;
  String? _secretKey;

  // OTP setup state
  String? _maskedContact;
  bool _isSendingOtp = false;
  int _resendCooldown = 0;
  Timer? _resendTimer;

  // Verification state
  bool _isVerifying = false;
  bool _hasOtpError = false;

  // Disable / change method state
  bool _isDisabling = false;
  bool _isChangingMethod = false;

  // Loading for authenticator setup
  bool _isSettingUp = false;

  @override
  void dispose() {
    _resendTimer?.cancel();
    super.dispose();
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  String _methodLabel(String method) =>
      AppConstants.tfaMethodLabels[method] ?? method;

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

  String _methodDescription(String method) {
    switch (method) {
      case AppConstants.tfaMethodAuthenticator:
        return 'Use an authenticator app like Google Authenticator';
      case AppConstants.tfaMethodEmail:
        return 'Receive a code via email';
      case AppConstants.tfaMethodSms:
        return 'Receive a code via SMS';
      default:
        return '';
    }
  }

  List<String> _availableMethods(TfaStatus status) {
    final methods = <String>[AppConstants.tfaMethodAuthenticator];
    if (status.emailEnabled && status.maskedEmail != null) {
      methods.add(AppConstants.tfaMethodEmail);
    }
    if (status.smsEnabled && status.maskedMobile != null) {
      methods.add(AppConstants.tfaMethodSms);
    }
    return methods;
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

  void _resetState() {
    _resendTimer?.cancel();
    setState(() {
      _currentView = _TfaView.status;
      _selectedMethod = null;
      _qrCodeBase64 = null;
      _secretKey = null;
      _maskedContact = null;
      _isSendingOtp = false;
      _resendCooldown = 0;
      _isVerifying = false;
      _hasOtpError = false;
      _isDisabling = false;
      _isChangingMethod = false;
      _isSettingUp = false;
    });
  }

  // ── Enable Flow ───────────────────────────────────────────────────────────

  void _onEnableTfa(TfaStatus status) {
    final methods = _availableMethods(status);
    if (methods.length == 1) {
      // Only authenticator available — go directly to setup
      _onSelectMethod(AppConstants.tfaMethodAuthenticator);
    } else {
      setState(() {
        _currentView = _TfaView.setupChooseMethod;
        _selectedMethod = null;
      });
    }
  }

  Future<void> _onSelectMethod(String method) async {
    _selectedMethod = method;

    if (method == AppConstants.tfaMethodAuthenticator) {
      await _setupAuthenticator();
    } else {
      await _sendSetupOtp(method);
    }
  }

  Future<void> _setupAuthenticator() async {
    setState(() => _isSettingUp = true);

    try {
      final tfaApi = ref.read(twoFactorApiServiceProvider);
      final response = await tfaApi.setupAuthenticator();

      if (!mounted) return;

      if (response.success && response.data != null) {
        final data = TfaSetupAuthenticatorData.fromJson(
          response.data as Map<String, dynamic>,
        );
        setState(() {
          _qrCodeBase64 = data.qrCode;
          _secretKey = data.secret;
          _currentView = _TfaView.setupAuthenticator;
          _isSettingUp = false;
        });
      } else {
        setState(() => _isSettingUp = false);
        AppSnackbar.show(
          context,
          message: response.message.isNotEmpty
              ? response.message
              : Messages.tfaSetupFailed,
          type: SnackbarType.error,
        );
      }
    } catch (_) {
      if (!mounted) return;
      setState(() => _isSettingUp = false);
      AppSnackbar.show(
        context,
        message: Messages.errorGeneric,
        type: SnackbarType.error,
      );
    }
  }

  Future<void> _sendSetupOtp(String method) async {
    setState(() => _isSendingOtp = true);

    try {
      final tfaApi = ref.read(twoFactorApiServiceProvider);
      final request = SendSetupOtpRequest(method: method);
      final response = await tfaApi.sendSetupOtp(request);

      if (!mounted) return;

      if (response.success) {
        final status = ref.read(tfaStatusProvider).valueOrNull;
        setState(() {
          _maskedContact = method == AppConstants.tfaMethodEmail
              ? status?.maskedEmail
              : status?.maskedMobile;
          _currentView = _TfaView.setupOtp;
          _isSendingOtp = false;
        });
        _startResendCooldown();
        AppSnackbar.show(
          context,
          message: Messages.tfaOtpSent,
          type: SnackbarType.success,
        );
      } else {
        setState(() => _isSendingOtp = false);
        AppSnackbar.show(
          context,
          message: response.message.isNotEmpty
              ? response.message
              : Messages.tfaOtpSendFailed,
          type: SnackbarType.error,
        );
      }
    } catch (_) {
      if (!mounted) return;
      setState(() => _isSendingOtp = false);
      AppSnackbar.show(
        context,
        message: Messages.errorGeneric,
        type: SnackbarType.error,
      );
    }
  }

  Future<void> _onResendOtp() async {
    if (_resendCooldown > 0 || _selectedMethod == null) return;
    await _sendSetupOtp(_selectedMethod!);
  }

  Future<void> _onVerifyAndEnable(String code) async {
    if (code.length != AppConstants.otpLength || _selectedMethod == null) return;

    setState(() {
      _isVerifying = true;
      _hasOtpError = false;
    });

    try {
      final tfaApi = ref.read(twoFactorApiServiceProvider);
      final request = VerifyAndEnableRequest(
        code: code,
        method: _selectedMethod!,
      );
      final response = await tfaApi.verifyAndEnable(request);

      if (!mounted) return;

      if (response.success) {
        ref.invalidate(tfaStatusProvider);
        _resetState();
        AppSnackbar.show(
          context,
          message: Messages.tfaEnabled,
          type: SnackbarType.success,
        );
      } else {
        setState(() {
          _isVerifying = false;
          _hasOtpError = true;
        });
        _otpKey.currentState?.clear();
        AppSnackbar.show(
          context,
          message: response.message.isNotEmpty
              ? response.message
              : Messages.tfaVerifyFailed,
          type: SnackbarType.error,
        );
      }
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _isVerifying = false;
        _hasOtpError = true;
      });
      _otpKey.currentState?.clear();
      AppSnackbar.show(
        context,
        message: Messages.errorGeneric,
        type: SnackbarType.error,
      );
    }
  }

  // ── Disable Flow ──────────────────────────────────────────────────────────

  Future<void> _onDisableTfa() async {
    setState(() => _isDisabling = true);

    try {
      final tfaApi = ref.read(twoFactorApiServiceProvider);
      final response = await tfaApi.disable();

      if (!mounted) return;

      if (response.success) {
        ref.invalidate(tfaStatusProvider);
        _resetState();
        AppSnackbar.show(
          context,
          message: Messages.tfaDisabled,
          type: SnackbarType.success,
        );
      } else {
        setState(() => _isDisabling = false);
        AppSnackbar.show(
          context,
          message: response.message.isNotEmpty
              ? response.message
              : Messages.tfaDisableFailed,
          type: SnackbarType.error,
        );
      }
    } catch (_) {
      if (!mounted) return;
      setState(() => _isDisabling = false);
      // Action verification cancelled or network error — do nothing extra
    }
  }

  // ── Change Method Flow ────────────────────────────────────────────────────

  void _onStartChangeMethod(TfaStatus status) {
    setState(() {
      _currentView = _TfaView.changeMethod;
      _selectedMethod = null;
    });
  }

  Future<void> _onSubmitChangeMethod() async {
    if (_selectedMethod == null) return;

    setState(() => _isChangingMethod = true);

    try {
      final tfaApi = ref.read(twoFactorApiServiceProvider);
      final request = ChangeMethodRequest(newMethod: _selectedMethod!);
      final response = await tfaApi.changeMethod(request);

      if (!mounted) return;

      if (response.success) {
        ref.invalidate(tfaStatusProvider);
        _resetState();
        AppSnackbar.show(
          context,
          message: Messages.tfaMethodChanged,
          type: SnackbarType.success,
        );
      } else {
        setState(() => _isChangingMethod = false);
        AppSnackbar.show(
          context,
          message: response.message.isNotEmpty
              ? response.message
              : Messages.tfaMethodChangeFailed,
          type: SnackbarType.error,
        );
      }
    } catch (_) {
      if (!mounted) return;
      setState(() => _isChangingMethod = false);
      // Action verification cancelled or network error
    }
  }

  // ── Build ─────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final tfaAsync = ref.watch(tfaStatusProvider);

    return tfaAsync.when(
      loading: () => const AppLoadingIndicator(message: 'Loading 2FA status...'),
      error: (error, _) => AppErrorWidget(
        message: Messages.tfaStatusFailed,
        onRetry: () => ref.invalidate(tfaStatusProvider),
      ),
      data: (status) {
        if (status == null) {
          return AppErrorWidget(
            message: Messages.tfaStatusFailed,
            onRetry: () => ref.invalidate(tfaStatusProvider),
          );
        }

        return _buildContent(status);
      },
    );
  }

  Widget _buildContent(TfaStatus status) {
    switch (_currentView) {
      case _TfaView.status:
        return _buildStatusView(status);
      case _TfaView.setupChooseMethod:
        return _buildChooseMethodView(status);
      case _TfaView.setupAuthenticator:
        return _buildAuthenticatorSetupView();
      case _TfaView.setupOtp:
        return _buildOtpSetupView();
      case _TfaView.changeMethod:
        return _buildChangeMethodView(status);
    }
  }

  // ── Status View ───────────────────────────────────────────────────────────

  Widget _buildStatusView(TfaStatus status) {
    final theme = Theme.of(context);

    return AppCard(
      title: 'Two-Factor Authentication',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Status indicator
          Container(
            padding: const EdgeInsets.all(AppDimensions.md),
            decoration: BoxDecoration(
              color: status.twoFactorEnabled
                  ? theme.colorScheme.primaryContainer.withValues(alpha: 0.3)
                  : theme.colorScheme.surfaceContainerHighest
                      .withValues(alpha: 0.5),
              borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
            ),
            child: Row(
              children: [
                Icon(
                  status.twoFactorEnabled
                      ? Icons.shield_outlined
                      : Icons.shield_outlined,
                  size: 32,
                  color: status.twoFactorEnabled
                      ? theme.colorScheme.primary
                      : theme.colorScheme.onSurfaceVariant,
                ),
                const SizedBox(width: AppDimensions.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        status.twoFactorEnabled ? 'Enabled' : 'Disabled',
                        style: theme.textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.w600,
                          color: status.twoFactorEnabled
                              ? theme.colorScheme.primary
                              : theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                      if (status.twoFactorEnabled &&
                          status.twoFactorMethod != null)
                        Text(
                          'Method: ${_methodLabel(status.twoFactorMethod!)}',
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                        ),
                      if (!status.twoFactorEnabled)
                        Text(
                          'Add an extra layer of security to your account',
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: AppDimensions.lg),

          // Action buttons
          if (status.twoFactorEnabled) ...[
            AppButton(
              label: 'Change Method',
              onPressed: _availableMethods(status).length > 1
                  ? () => _onStartChangeMethod(status)
                  : null,
              isOutlined: true,
              icon: Icons.swap_horiz,
            ),
            const SizedBox(height: AppDimensions.sm),
            AppButton(
              label: 'Disable 2FA',
              onPressed: _isDisabling ? null : _onDisableTfa,
              isLoading: _isDisabling,
              isOutlined: true,
              color: theme.colorScheme.error,
              icon: Icons.lock_open_outlined,
            ),
          ] else
            AppButton(
              label: 'Enable 2FA',
              onPressed: _isSettingUp
                  ? null
                  : () => _onEnableTfa(status),
              isLoading: _isSettingUp,
              icon: Icons.lock_outline,
            ),
        ],
      ),
    );
  }

  // ── Choose Method View ────────────────────────────────────────────────────

  Widget _buildChooseMethodView(TfaStatus status) {
    final theme = Theme.of(context);
    final methods = _availableMethods(status);

    return AppCard(
      title: 'Enable Two-Factor Authentication',
      subtitle: 'Choose a verification method',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ...methods.map((method) => Padding(
                padding: const EdgeInsets.only(bottom: AppDimensions.sm),
                child: _buildMethodCard(theme, method),
              )),
          const SizedBox(height: AppDimensions.sm),
          Center(
            child: TextButton(
              onPressed: _isSendingOtp || _isSettingUp ? null : _resetState,
              child: const Text('Cancel'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMethodCard(ThemeData theme, String method) {
    final isLoading = (_isSettingUp &&
            _selectedMethod == method &&
            method == AppConstants.tfaMethodAuthenticator) ||
        (_isSendingOtp && _selectedMethod == method);

    return OutlinedButton(
      onPressed:
          _isSendingOtp || _isSettingUp ? null : () => _onSelectMethod(method),
      style: OutlinedButton.styleFrom(
        padding: const EdgeInsets.all(AppDimensions.md),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
        ),
      ),
      child: Row(
        children: [
          Icon(_methodIcon(method), size: 28),
          const SizedBox(width: AppDimensions.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  _methodLabel(method),
                  style: theme.textTheme.titleSmall,
                ),
                Text(
                  _methodDescription(method),
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
          if (isLoading)
            const SizedBox(
              width: 20,
              height: 20,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          else
            const Icon(Icons.chevron_right),
        ],
      ),
    );
  }

  // ── Authenticator Setup View ──────────────────────────────────────────────

  Widget _buildAuthenticatorSetupView() {
    final theme = Theme.of(context);

    return AppCard(
      title: 'Setup Authenticator',
      subtitle:
          'Scan the QR code with your authenticator app, then enter the 6-digit code',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // QR code
          if (_qrCodeBase64 != null)
            Center(
              child: Container(
                padding: const EdgeInsets.all(AppDimensions.md),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
                ),
                child: Image.memory(
                  base64Decode(_qrCodeBase64!),
                  width: 200,
                  height: 200,
                  fit: BoxFit.contain,
                ),
              ),
            ),
          const SizedBox(height: AppDimensions.md),

          // Secret key (copyable)
          if (_secretKey != null) ...[
            Text(
              'Or enter this key manually:',
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: AppDimensions.sm),
            Container(
              padding: const EdgeInsets.symmetric(
                horizontal: AppDimensions.md,
                vertical: AppDimensions.sm,
              ),
              decoration: BoxDecoration(
                color: theme.colorScheme.surfaceContainerHighest,
                borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
              ),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Flexible(
                    child: SelectableText(
                      _secretKey!,
                      style: theme.textTheme.bodyMedium?.copyWith(
                        fontFamily: 'monospace',
                        fontWeight: FontWeight.w600,
                        letterSpacing: 1.2,
                      ),
                      textAlign: TextAlign.center,
                    ),
                  ),
                  const SizedBox(width: AppDimensions.sm),
                  IconButton(
                    icon: const Icon(Icons.copy, size: 20),
                    tooltip: 'Copy key',
                    onPressed: () {
                      Clipboard.setData(ClipboardData(text: _secretKey!));
                      AppSnackbar.show(
                        context,
                        message: 'Secret key copied to clipboard',
                        type: SnackbarType.info,
                      );
                    },
                  ),
                ],
              ),
            ),
          ],
          const SizedBox(height: AppDimensions.lg),

          // OTP input
          OtpInputWidget(
            key: _otpKey,
            onCompleted: _onVerifyAndEnable,
            hasError: _hasOtpError,
            enabled: !_isVerifying,
            onChanged: (_) {
              if (_hasOtpError) setState(() => _hasOtpError = false);
            },
          ),
          const SizedBox(height: AppDimensions.md),

          // Verify button
          AppButton(
            label: 'Verify & Enable',
            onPressed: _isVerifying
                ? null
                : () => _onVerifyAndEnable(_otpKey.currentState?.code ?? ''),
            isLoading: _isVerifying,
          ),
          const SizedBox(height: AppDimensions.sm),

          Center(
            child: TextButton(
              onPressed: _isVerifying ? null : _resetState,
              child: const Text('Cancel'),
            ),
          ),
        ],
      ),
    );
  }

  // ── OTP Setup View (Email / SMS) ──────────────────────────────────────────

  Widget _buildOtpSetupView() {
    final theme = Theme.of(context);

    return AppCard(
      title: 'Verify ${_methodLabel(_selectedMethod!)}',
      subtitle: _maskedContact != null
          ? 'A verification code has been sent to $_maskedContact'
          : 'Enter the verification code',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Method indicator
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
                  _methodIcon(_selectedMethod!),
                  size: 20,
                  color: theme.colorScheme.primary,
                ),
                const SizedBox(width: AppDimensions.sm),
                Text(
                  _methodLabel(_selectedMethod!),
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
            onCompleted: _onVerifyAndEnable,
            hasError: _hasOtpError,
            enabled: !_isVerifying,
            onChanged: (_) {
              if (_hasOtpError) setState(() => _hasOtpError = false);
            },
          ),
          const SizedBox(height: AppDimensions.md),

          // Verify button
          AppButton(
            label: 'Verify & Enable',
            onPressed: _isVerifying
                ? null
                : () => _onVerifyAndEnable(_otpKey.currentState?.code ?? ''),
            isLoading: _isVerifying,
          ),
          const SizedBox(height: AppDimensions.md),

          // Resend OTP
          Center(
            child: TextButton(
              onPressed:
                  _resendCooldown > 0 || _isSendingOtp ? null : _onResendOtp,
              child: Text(
                _resendCooldown > 0
                    ? 'Resend code in ${_resendCooldown}s'
                    : 'Resend code',
              ),
            ),
          ),

          Center(
            child: TextButton(
              onPressed: _isVerifying ? null : _resetState,
              child: const Text('Cancel'),
            ),
          ),
        ],
      ),
    );
  }

  // ── Change Method View ────────────────────────────────────────────────────

  Widget _buildChangeMethodView(TfaStatus status) {
    final theme = Theme.of(context);
    final methods = _availableMethods(status)
        .where((m) => m != status.twoFactorMethod)
        .toList();

    return AppCard(
      title: 'Change 2FA Method',
      subtitle: 'Select a new verification method',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ...methods.map((method) {
            final isSelected = _selectedMethod == method;
            return Padding(
              padding: const EdgeInsets.only(bottom: AppDimensions.sm),
              child: RadioListTile<String>(
                value: method,
                groupValue: _selectedMethod,
                onChanged: _isChangingMethod
                    ? null
                    : (value) => setState(() => _selectedMethod = value),
                title: Row(
                  children: [
                    Icon(
                      _methodIcon(method),
                      size: 20,
                      color: isSelected
                          ? theme.colorScheme.primary
                          : theme.colorScheme.onSurfaceVariant,
                    ),
                    const SizedBox(width: AppDimensions.sm),
                    Text(_methodLabel(method)),
                  ],
                ),
                subtitle: Text(
                  _methodDescription(method),
                  style: theme.textTheme.bodySmall,
                ),
                contentPadding: EdgeInsets.zero,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
                ),
              ),
            );
          }),
          const SizedBox(height: AppDimensions.sm),

          AppButton(
            label: 'Change Method',
            onPressed: _selectedMethod == null || _isChangingMethod
                ? null
                : _onSubmitChangeMethod,
            isLoading: _isChangingMethod,
          ),
          const SizedBox(height: AppDimensions.sm),

          Center(
            child: TextButton(
              onPressed: _isChangingMethod ? null : _resetState,
              child: const Text('Cancel'),
            ),
          ),
        ],
      ),
    );
  }
}
