import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/constants/app_constants.dart';
import '../../../core/constants/app_routes.dart';
import '../../../core/constants/messages.dart';
import '../../../core/theme/app_dimensions.dart';
import '../../../providers/location_provider.dart';
import '../../../providers/service_providers.dart';
import '../../../schemas/app_config_schema.dart';
import '../../../schemas/auth_schema.dart';
import '../../../shared/widgets/app_button.dart';
import '../../../shared/widgets/app_snackbar.dart';
import '../../../shared/widgets/app_text_field.dart';
import '../../../shared/widgets/captcha_widget.dart';
import '../../../shared/widgets/country_state_picker.dart';
import '../../../shared/widgets/otp_input_widget.dart';
import '../../../shared/widgets/password_field.dart';
import '../../../utils/validators.dart';
import '../widgets/auth_card_widget.dart';

class RegisterScreen extends ConsumerStatefulWidget {
  const RegisterScreen({super.key});

  @override
  ConsumerState<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends ConsumerState<RegisterScreen> {
  final _formKey = GlobalKey<FormState>();
  final _captchaKey = GlobalKey<CaptchaWidgetState>();
  final _emailOtpKey = GlobalKey<OtpInputWidgetState>();
  final _smsOtpKey = GlobalKey<OtpInputWidgetState>();

  final _firstNameController = TextEditingController();
  final _lastNameController = TextEditingController();
  final _emailController = TextEditingController();
  final _mobileController = TextEditingController();
  final _passwordController = TextEditingController();
  final _confirmPasswordController = TextEditingController();
  final _referralIdController = TextEditingController();

  CountryItem? _selectedCountry;
  StateItem? _selectedState;
  bool _isLoading = false;
  String? _captchaType;

  // App config
  AppConfigData? _appConfig;
  bool _isLoadingConfig = true;

  // Email OTP state
  bool _emailOtpSent = false;
  String? _emailOtpToken;
  String _emailOtpCode = '';
  bool _isSendingEmailOtp = false;
  int _emailResendCountdown = 0;
  Timer? _emailTimer;

  // SMS OTP state
  bool _smsOtpSent = false;
  String? _smsOtpToken;
  String _smsOtpCode = '';
  bool _isSendingSmsOtp = false;
  int _smsResendCountdown = 0;
  Timer? _smsTimer;

  bool get _needsEmailOtp =>
      _appConfig?.contactVerificationMode == 'pre' &&
      _appConfig!.emailEnabled;

  bool get _needsSmsOtp =>
      _appConfig?.contactVerificationMode == 'pre' &&
      _appConfig!.smsEnabled;

  @override
  void initState() {
    super.initState();
    _loadAppConfig();
  }

  @override
  void dispose() {
    _firstNameController.dispose();
    _lastNameController.dispose();
    _emailController.dispose();
    _mobileController.dispose();
    _passwordController.dispose();
    _confirmPasswordController.dispose();
    _referralIdController.dispose();
    _emailTimer?.cancel();
    _smsTimer?.cancel();
    super.dispose();
  }

  Future<void> _loadAppConfig() async {
    try {
      final configService = ref.read(appConfigApiServiceProvider);
      final response = await configService.getAppConfig();
      if (!mounted) return;
      if (response.success && response.data != null) {
        setState(() {
          _appConfig = AppConfigData.fromJson(
            response.data as Map<String, dynamic>,
          );
          _isLoadingConfig = false;
        });
      } else {
        setState(() => _isLoadingConfig = false);
      }
    } catch (_) {
      if (mounted) {
        setState(() => _isLoadingConfig = false);
      }
    }
  }

  void _onCaptchaTypeChanged(String? type) {
    setState(() => _captchaType = type);
  }

  void _onCountryChanged(CountryItem? country) {
    setState(() {
      _selectedCountry = country;
      _selectedState = null;
    });
  }

  void _onStateChanged(StateItem? state) {
    setState(() => _selectedState = state);
  }

  // ── Email OTP ──────────────────────────────────────────────────────────────

  void _startEmailTimer() {
    _emailResendCountdown = AppConstants.resendCooldownSeconds;
    _emailTimer?.cancel();
    _emailTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted) {
        timer.cancel();
        return;
      }
      setState(() {
        _emailResendCountdown--;
        if (_emailResendCountdown <= 0) {
          timer.cancel();
        }
      });
    });
  }

  Future<void> _sendEmailOtp() async {
    // Validate email field first
    final email = _emailController.text.trim();
    if (email.isEmpty || Validators.email(email) != null) {
      AppSnackbar.show(
        context,
        message: Messages.invalidEmail,
        type: SnackbarType.error,
      );
      return;
    }

    setState(() => _isSendingEmailOtp = true);

    try {
      final authApiService = ref.read(authApiServiceProvider);
      final response = await authApiService.sendContactVerificationOtp(
        SendOtpRequest(type: 'email', value: email),
      );

      if (!mounted) return;

      if (response.success && response.data != null) {
        final data = OtpTokenData.fromJson(
          response.data as Map<String, dynamic>,
        );
        setState(() {
          _emailOtpSent = true;
          _emailOtpToken = data.otpToken;
        });
        _startEmailTimer();
        AppSnackbar.show(
          context,
          message: Messages.contactOtpSent,
          type: SnackbarType.success,
        );
      } else {
        AppSnackbar.show(
          context,
          message: response.message.isNotEmpty
              ? response.message
              : Messages.contactOtpSendFailed,
          type: SnackbarType.error,
        );
      }
    } catch (_) {
      if (!mounted) return;
      AppSnackbar.show(
        context,
        message: Messages.contactOtpSendFailed,
        type: SnackbarType.error,
      );
    } finally {
      if (mounted) {
        setState(() => _isSendingEmailOtp = false);
      }
    }
  }

  // ── SMS OTP ────────────────────────────────────────────────────────────────

  void _startSmsTimer() {
    _smsResendCountdown = AppConstants.resendCooldownSeconds;
    _smsTimer?.cancel();
    _smsTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted) {
        timer.cancel();
        return;
      }
      setState(() {
        _smsResendCountdown--;
        if (_smsResendCountdown <= 0) {
          timer.cancel();
        }
      });
    });
  }

  Future<void> _sendSmsOtp() async {
    final mobile = _mobileController.text.trim();
    if (mobile.isEmpty || Validators.mobile(mobile) != null) {
      AppSnackbar.show(
        context,
        message: Messages.invalidPhoneNumber,
        type: SnackbarType.error,
      );
      return;
    }

    setState(() => _isSendingSmsOtp = true);

    try {
      final authApiService = ref.read(authApiServiceProvider);
      final response = await authApiService.sendContactVerificationOtp(
        SendOtpRequest(type: 'sms', value: mobile),
      );

      if (!mounted) return;

      if (response.success && response.data != null) {
        final data = OtpTokenData.fromJson(
          response.data as Map<String, dynamic>,
        );
        setState(() {
          _smsOtpSent = true;
          _smsOtpToken = data.otpToken;
        });
        _startSmsTimer();
        AppSnackbar.show(
          context,
          message: Messages.contactOtpSent,
          type: SnackbarType.success,
        );
      } else {
        AppSnackbar.show(
          context,
          message: response.message.isNotEmpty
              ? response.message
              : Messages.contactOtpSendFailed,
          type: SnackbarType.error,
        );
      }
    } catch (_) {
      if (!mounted) return;
      AppSnackbar.show(
        context,
        message: Messages.contactOtpSendFailed,
        type: SnackbarType.error,
      );
    } finally {
      if (mounted) {
        setState(() => _isSendingSmsOtp = false);
      }
    }
  }

  // ── Registration ───────────────────────────────────────────────────────────

  Future<void> _onRegister() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() => _isLoading = true);

    try {
      // Execute captcha if active
      CaptchaResult? captchaResult;
      if (_captchaType != null) {
        captchaResult = await _captchaKey.currentState?.execute();
      }

      // Build registration request
      final request = RegisterRequest(
        firstName: _firstNameController.text.trim(),
        lastName: _lastNameController.text.trim(),
        email: _emailController.text.trim(),
        password: _passwordController.text,
        mobileNo: _mobileController.text.trim().isNotEmpty
            ? _mobileController.text.trim()
            : null,
        countryId: _selectedCountry?.id,
        stateId: _selectedState?.id,
        referralId: _referralIdController.text.trim().isNotEmpty
            ? _referralIdController.text.trim()
            : null,
        captchaToken: captchaResult?.token,
        captchaAnswer: captchaResult?.answer,
        emailOtpToken:
            _needsEmailOtp && _emailOtpToken != null ? _emailOtpToken : null,
        emailOtpCode:
            _needsEmailOtp && _emailOtpCode.isNotEmpty ? _emailOtpCode : null,
        mobileOtpToken:
            _needsSmsOtp && _smsOtpToken != null ? _smsOtpToken : null,
        mobileOtpCode:
            _needsSmsOtp && _smsOtpCode.isNotEmpty ? _smsOtpCode : null,
      );

      // Call register API
      final authApiService = ref.read(authApiServiceProvider);
      final response = await authApiService.register(request);

      if (!mounted) return;

      if (response.success) {
        // Build success message with user ID if available
        String message = Messages.registrationSuccess;
        if (response.data != null) {
          final data = response.data as Map<String, dynamic>;
          final userId = data['user_id'] as String?;
          if (userId != null && userId.isNotEmpty) {
            message = '${Messages.registrationSuccess} Your User ID is: $userId';
          }
        }

        AppSnackbar.show(
          context,
          message: message,
          type: SnackbarType.success,
          duration: const Duration(
            milliseconds: AppConstants.snackbarDurationLongMs,
          ),
        );

        // Navigate to login
        if (mounted) {
          context.goNamed(AppRoutes.login);
        }
        return;
      }

      // Registration failed — show error and refresh CAPTCHA
      AppSnackbar.show(
        context,
        message: response.message.isNotEmpty
            ? response.message
            : Messages.registrationFailed,
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

  // ── Build ──────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    // Watch country/state providers
    final countriesAsync = ref.watch(countriesProvider);
    final statesAsync = _selectedCountry != null
        ? ref.watch(statesProvider(_selectedCountry!.id))
        : null;

    // Map provider data to picker items
    final countryItems = countriesAsync.maybeWhen(
      data: (countries) => countries
          .map((c) => CountryItem(id: c.id, name: c.name))
          .toList(),
      orElse: () => <CountryItem>[],
    );

    final stateItems = statesAsync?.maybeWhen(
          data: (states) => states
              .map((s) => StateItem(id: s.id, name: s.name))
              .toList(),
          orElse: () => <StateItem>[],
        ) ??
        <StateItem>[];

    final isLoadingCountries = countriesAsync.isLoading;
    final isLoadingStates = statesAsync?.isLoading ?? false;

    return AuthCardWidget(
      title: 'Create Account',
      subtitle: 'Fill in your details to get started',
      child: Form(
        key: _formKey,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          mainAxisSize: MainAxisSize.min,
          children: [
            // First Name
            AppTextField(
              controller: _firstNameController,
              label: 'First Name',
              prefixIcon: Icons.person_outline,
              validator: Validators.required,
              textInputAction: TextInputAction.next,
              autofocus: true,
            ),
            const SizedBox(height: AppDimensions.md),

            // Last Name
            AppTextField(
              controller: _lastNameController,
              label: 'Last Name',
              prefixIcon: Icons.person_outline,
              validator: Validators.required,
              textInputAction: TextInputAction.next,
            ),
            const SizedBox(height: AppDimensions.md),

            // Email
            AppTextField(
              controller: _emailController,
              label: 'Email',
              prefixIcon: Icons.email_outlined,
              validator: Validators.email,
              keyboardType: TextInputType.emailAddress,
              textInputAction: TextInputAction.next,
              suffixIcon: _needsEmailOtp ? _buildEmailOtpSuffixButton() : null,
            ),
            // Email OTP countdown hint
            if (_needsEmailOtp && _emailResendCountdown > 0)
              Padding(
                padding: const EdgeInsets.only(
                  top: AppDimensions.xs,
                  left: AppDimensions.md,
                ),
                child: Text(
                  'Resend in ${_emailResendCountdown}s',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ),
            // Email OTP input
            if (_needsEmailOtp && _emailOtpSent) ...[
              const SizedBox(height: AppDimensions.md),
              Text(
                'Email Verification Code',
                style: theme.textTheme.bodyMedium?.copyWith(
                  fontWeight: FontWeight.w500,
                ),
              ),
              const SizedBox(height: AppDimensions.sm),
              OtpInputWidget(
                key: _emailOtpKey,
                onCompleted: (code) => _emailOtpCode = code,
                onChanged: (code) => _emailOtpCode = code,
              ),
            ],
            const SizedBox(height: AppDimensions.md),

            // Mobile Number (optional unless SMS OTP needed)
            AppTextField(
              controller: _mobileController,
              label: _needsSmsOtp
                  ? 'Mobile Number'
                  : 'Mobile Number (optional)',
              prefixIcon: Icons.phone_outlined,
              validator: _needsSmsOtp ? Validators.mobile : null,
              keyboardType: TextInputType.phone,
              textInputAction: TextInputAction.next,
              suffixIcon: _needsSmsOtp ? _buildSmsOtpSuffixButton() : null,
            ),
            // SMS OTP countdown hint
            if (_needsSmsOtp && _smsResendCountdown > 0)
              Padding(
                padding: const EdgeInsets.only(
                  top: AppDimensions.xs,
                  left: AppDimensions.md,
                ),
                child: Text(
                  'Resend in ${_smsResendCountdown}s',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ),
            // SMS OTP input
            if (_needsSmsOtp && _smsOtpSent) ...[
              const SizedBox(height: AppDimensions.md),
              Text(
                'SMS Verification Code',
                style: theme.textTheme.bodyMedium?.copyWith(
                  fontWeight: FontWeight.w500,
                ),
              ),
              const SizedBox(height: AppDimensions.sm),
              OtpInputWidget(
                key: _smsOtpKey,
                onCompleted: (code) => _smsOtpCode = code,
                onChanged: (code) => _smsOtpCode = code,
              ),
            ],
            const SizedBox(height: AppDimensions.md),

            // Password
            PasswordField(
              controller: _passwordController,
              validator: Validators.password,
              textInputAction: TextInputAction.next,
            ),
            const SizedBox(height: AppDimensions.md),

            // Confirm Password
            PasswordField(
              controller: _confirmPasswordController,
              label: 'Confirm Password',
              validator: Validators.confirmPassword(_passwordController),
              textInputAction: TextInputAction.next,
            ),
            const SizedBox(height: AppDimensions.md),

            // Country & State picker
            CountryStatePicker(
              countries: countryItems,
              states: stateItems,
              selectedCountry: _selectedCountry,
              selectedState: _selectedState,
              onCountryChanged: _onCountryChanged,
              onStateChanged: _onStateChanged,
              isLoadingCountries: isLoadingCountries,
              isLoadingStates: isLoadingStates,
            ),
            const SizedBox(height: AppDimensions.md),

            // Referral ID (optional)
            AppTextField(
              controller: _referralIdController,
              label: 'Referral ID (optional)',
              prefixIcon: Icons.card_giftcard_outlined,
              textInputAction: TextInputAction.done,
            ),
            const SizedBox(height: AppDimensions.md),

            // CAPTCHA
            CaptchaWidget(
              key: _captchaKey,
              onTokenChanged: (_) {},
              onTypeChanged: _onCaptchaTypeChanged,
            ),
            if (_captchaType != null) const SizedBox(height: AppDimensions.md),

            // Register button
            AppButton(
              label: 'Register',
              onPressed: _isLoading || _isLoadingConfig ? null : _onRegister,
              isLoading: _isLoading,
            ),
            const SizedBox(height: AppDimensions.md),

            // Sign In link
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  'Already have an account? ',
                  style: theme.textTheme.bodyMedium,
                ),
                TextButton(
                  onPressed: () => context.goNamed(AppRoutes.login),
                  style: TextButton.styleFrom(
                    padding: EdgeInsets.zero,
                    minimumSize: Size.zero,
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                  child: const Text('Sign In'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  // ── OTP Suffix Buttons ─────────────────────────────────────────────────────

  Widget _buildEmailOtpSuffixButton() {
    final isDisabled = _isSendingEmailOtp || _emailResendCountdown > 0;

    return IconButton(
      onPressed: isDisabled ? null : _sendEmailOtp,
      icon: _isSendingEmailOtp
          ? const SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          : Icon(_emailOtpSent ? Icons.refresh : Icons.send),
      tooltip: _emailOtpSent ? 'Resend OTP' : 'Send OTP',
    );
  }

  Widget _buildSmsOtpSuffixButton() {
    final isDisabled = _isSendingSmsOtp || _smsResendCountdown > 0;

    return IconButton(
      onPressed: isDisabled ? null : _sendSmsOtp,
      icon: _isSendingSmsOtp
          ? const SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          : Icon(_smsOtpSent ? Icons.refresh : Icons.send),
      tooltip: _smsOtpSent ? 'Resend OTP' : 'Send OTP',
    );
  }
}
