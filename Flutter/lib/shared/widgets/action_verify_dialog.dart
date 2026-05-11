import 'dart:async';

import 'package:flutter/material.dart';

import 'package:template_app/core/constants/app_constants.dart';
import 'package:template_app/core/constants/messages.dart';
import 'package:template_app/core/theme/app_dimensions.dart';
import 'package:template_app/services/action_verify_api_service.dart';
import 'package:template_app/shared/widgets/otp_input_widget.dart';

/// Modal dialog for action verification (reusable 2FA).
///
/// Non-dismissable — user must complete verification or cancel.
/// Shows available 2FA methods, accepts OTP code, verifies, and returns
/// the action_token string on success or null on cancel.
class ActionVerifyDialog extends StatefulWidget {
  const ActionVerifyDialog({
    super.key,
    required this.apiService,
    required this.availableMethods,
    required this.defaultMethod,
    this.maskedEmail,
    this.maskedPhone,
  });

  final ActionVerifyApiService apiService;
  final List<String> availableMethods;
  final String defaultMethod;
  final String? maskedEmail;
  final String? maskedPhone;

  @override
  State<ActionVerifyDialog> createState() => _ActionVerifyDialogState();
}

class _ActionVerifyDialogState extends State<ActionVerifyDialog> {
  late String _selectedMethod;
  bool _isVerifying = false;
  bool _isSendingOtp = false;
  bool _hasError = false;
  String? _errorMessage;
  int _resendCooldown = 0;
  Timer? _cooldownTimer;
  final _otpKey = GlobalKey<OtpInputWidgetState>();
  bool _showMethodPicker = false;

  @override
  void initState() {
    super.initState();
    _selectedMethod = widget.defaultMethod;
    // Auto-send OTP for email/SMS methods
    if (_selectedMethod != AppConstants.tfaMethodAuthenticator) {
      _sendOtp();
    }
  }

  @override
  void dispose() {
    _cooldownTimer?.cancel();
    super.dispose();
  }

  bool get _needsOtpSend =>
      _selectedMethod != AppConstants.tfaMethodAuthenticator;

  String get _methodLabel =>
      AppConstants.tfaMethodLabels[_selectedMethod] ?? _selectedMethod;

  String get _methodHint {
    switch (_selectedMethod) {
      case AppConstants.tfaMethodAuthenticator:
        return 'Enter the code from your authenticator app';
      case AppConstants.tfaMethodEmail:
        final email = widget.maskedEmail ?? 'your email';
        return 'Enter the code sent to $email';
      case AppConstants.tfaMethodSms:
        final phone = widget.maskedPhone ?? 'your phone';
        return 'Enter the code sent to $phone';
      default:
        return 'Enter your verification code';
    }
  }

  Future<void> _sendOtp() async {
    setState(() {
      _isSendingOtp = true;
      _hasError = false;
      _errorMessage = null;
    });

    try {
      final response = await widget.apiService.sendOtp(
        method: _selectedMethod,
      );

      if (mounted) {
        if (response.success) {
          _startCooldown();
        } else {
          setState(() {
            _hasError = true;
            _errorMessage = response.message.isNotEmpty
                ? response.message
                : Messages.actionVerifyOtpSendFailed;
          });
        }
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _hasError = true;
          _errorMessage = Messages.actionVerifyOtpSendFailed;
        });
      }
    } finally {
      if (mounted) {
        setState(() => _isSendingOtp = false);
      }
    }
  }

  void _startCooldown() {
    _cooldownTimer?.cancel();
    setState(() => _resendCooldown = AppConstants.resendCooldownSeconds);
    _cooldownTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted) {
        timer.cancel();
        return;
      }
      setState(() {
        _resendCooldown--;
        if (_resendCooldown <= 0) {
          timer.cancel();
        }
      });
    });
  }

  Future<void> _verify(String code) async {
    if (code.length != AppConstants.otpLength) return;

    setState(() {
      _isVerifying = true;
      _hasError = false;
      _errorMessage = null;
    });

    try {
      final response = await widget.apiService.verify(
        code: code,
        method: _selectedMethod,
      );

      if (!mounted) return;

      if (response.success) {
        final data = response.data as Map<String, dynamic>?;
        final actionToken = data?['action_token'] as String?;
        Navigator.of(context).pop(actionToken);
      } else {
        setState(() {
          _hasError = true;
          _errorMessage = response.message.isNotEmpty
              ? response.message
              : Messages.actionVerifyFailed;
        });
        _otpKey.currentState?.clear();
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _hasError = true;
          _errorMessage = Messages.actionVerifyFailed;
        });
        _otpKey.currentState?.clear();
      }
    } finally {
      if (mounted) {
        setState(() => _isVerifying = false);
      }
    }
  }

  void _switchMethod(String method) {
    setState(() {
      _selectedMethod = method;
      _showMethodPicker = false;
      _hasError = false;
      _errorMessage = null;
      _resendCooldown = 0;
    });
    _cooldownTimer?.cancel();
    _otpKey.currentState?.clear();

    // Auto-send OTP for email/SMS methods
    if (method != AppConstants.tfaMethodAuthenticator) {
      _sendOtp();
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;

    return PopScope(
      canPop: false,
      child: AlertDialog(
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppDimensions.radiusMd),
        ),
        title: Row(
          children: [
            Icon(Icons.security, color: colorScheme.primary),
            const SizedBox(width: AppDimensions.sm),
            Expanded(
              child: Text(
                'Verification Required',
                style: theme.textTheme.titleLarge,
              ),
            ),
          ],
        ),
        content: SizedBox(
          width: double.maxFinite,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              // Method label & hint
              Text(
                _methodLabel,
                style: theme.textTheme.titleSmall?.copyWith(
                  color: colorScheme.primary,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: AppDimensions.xs),
              Text(
                _methodHint,
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: colorScheme.onSurfaceVariant,
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: AppDimensions.lg),

              // OTP input
              OtpInputWidget(
                key: _otpKey,
                onCompleted: _verify,
                hasError: _hasError,
                enabled: !_isVerifying,
              ),
              const SizedBox(height: AppDimensions.sm),

              // Error message
              if (_errorMessage != null) ...[
                Text(
                  _errorMessage!,
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: colorScheme.error,
                  ),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: AppDimensions.sm),
              ],

              // Resend OTP button (for email/SMS)
              if (_needsOtpSend) ...[
                _buildResendButton(theme),
                const SizedBox(height: AppDimensions.sm),
              ],

              // Method picker toggle
              if (_showMethodPicker)
                _buildMethodPicker(theme, colorScheme)
              else if (widget.availableMethods.length > 1)
                TextButton(
                  onPressed: _isVerifying
                      ? null
                      : () => setState(() => _showMethodPicker = true),
                  child: const Text('Try another way'),
                ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: _isVerifying ? null : () => Navigator.of(context).pop(),
            child: const Text('Cancel'),
          ),
        ],
      ),
    );
  }

  Widget _buildResendButton(ThemeData theme) {
    if (_isSendingOtp) {
      return Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          SizedBox(
            width: 16,
            height: 16,
            child: CircularProgressIndicator(
              strokeWidth: 2,
              color: theme.colorScheme.primary,
            ),
          ),
          const SizedBox(width: AppDimensions.sm),
          Text(
            'Sending...',
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ],
      );
    }

    if (_resendCooldown > 0) {
      return Text(
        'Resend code in ${_resendCooldown}s',
        style: theme.textTheme.bodySmall?.copyWith(
          color: theme.colorScheme.onSurfaceVariant,
        ),
      );
    }

    return TextButton(
      onPressed: _isVerifying ? null : _sendOtp,
      child: const Text('Resend code'),
    );
  }

  Widget _buildMethodPicker(ThemeData theme, ColorScheme colorScheme) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          'Choose verification method',
          style: theme.textTheme.titleSmall,
        ),
        const SizedBox(height: AppDimensions.sm),
        RadioGroup<String>(
          groupValue: _selectedMethod,
          onChanged: (String? v) {
            if (!_isVerifying && v != null) _switchMethod(v);
          },
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: widget.availableMethods.map((method) {
              final label = AppConstants.tfaMethodLabels[method] ?? method;
              return RadioListTile<String>(
                dense: true,
                title: Text(label),
                value: method,
                activeColor: colorScheme.primary,
              );
            }).toList(),
          ),
        ),
      ],
    );
  }
}
