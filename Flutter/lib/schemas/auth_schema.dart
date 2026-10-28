import 'package:freezed_annotation/freezed_annotation.dart';

part 'auth_schema.freezed.dart';
part 'auth_schema.g.dart';

// ── Login ────────────────────────────────────────────────────────────────────

@freezed
class LoginRequest with _$LoginRequest {
  const factory LoginRequest({
    required String identifier,
    required String password,
    @JsonKey(name: 'two_factor_code') String? twoFactorCode,
    @JsonKey(name: 'two_factor_method') String? twoFactorMethod,
    @JsonKey(name: 'device_info') Map<String, String>? deviceInfo,
    @JsonKey(name: 'captcha_token') String? captchaToken,
    @JsonKey(name: 'captcha_answer') String? captchaAnswer,
  }) = _LoginRequest;

  factory LoginRequest.fromJson(Map<String, dynamic> json) =>
      _$LoginRequestFromJson(json);
}

@freezed
class LoginData with _$LoginData {
  const factory LoginData({
    required String token,
    @JsonKey(name: 'user_id') required String userId,
    required String role,
    @JsonKey(name: 'first_name') String? firstName,
    @JsonKey(name: 'last_name') String? lastName,
    String? name,
    required String email,
    @JsonKey(name: 'is_super_admin') @Default(false) bool isSuperAdmin,
  }) = _LoginData;

  factory LoginData.fromJson(Map<String, dynamic> json) =>
      _$LoginDataFromJson(json);
}

@freezed
class TfaRequiredData with _$TfaRequiredData {
  const factory TfaRequiredData({
    @JsonKey(name: 'requires_2fa') @Default(true) bool requires2fa,
    required String method,
    @JsonKey(name: 'available_methods') required List<String> availableMethods,
  }) = _TfaRequiredData;

  factory TfaRequiredData.fromJson(Map<String, dynamic> json) =>
      _$TfaRequiredDataFromJson(json);
}

@freezed
class EmailVerificationRequiredData with _$EmailVerificationRequiredData {
  const factory EmailVerificationRequiredData({
    @JsonKey(name: 'requires_email_verification')
    @Default(true)
    bool requiresEmailVerification,
  }) = _EmailVerificationRequiredData;

  factory EmailVerificationRequiredData.fromJson(Map<String, dynamic> json) =>
      _$EmailVerificationRequiredDataFromJson(json);
}

// ── 2FA Try Another Way ──────────────────────────────────────────────────────

@freezed
class TryAnotherWayRequest with _$TryAnotherWayRequest {
  const factory TryAnotherWayRequest({
    required String identifier,
    required String password,
    @JsonKey(name: 'user_type') required String userType,
    required String method,
  }) = _TryAnotherWayRequest;

  factory TryAnotherWayRequest.fromJson(Map<String, dynamic> json) =>
      _$TryAnotherWayRequestFromJson(json);
}

@freezed
class TryAnotherWayData with _$TryAnotherWayData {
  const factory TryAnotherWayData({
    required String method,
    @JsonKey(name: 'available_methods') required List<String> availableMethods,
  }) = _TryAnotherWayData;

  factory TryAnotherWayData.fromJson(Map<String, dynamic> json) =>
      _$TryAnotherWayDataFromJson(json);
}

// ── Forgot / Reset Password ──────────────────────────────────────────────────

@freezed
class ForgotPasswordRequest with _$ForgotPasswordRequest {
  const factory ForgotPasswordRequest({
    required String identifier,
  }) = _ForgotPasswordRequest;

  factory ForgotPasswordRequest.fromJson(Map<String, dynamic> json) =>
      _$ForgotPasswordRequestFromJson(json);
}

@freezed
class ResetPasswordRequest with _$ResetPasswordRequest {
  const factory ResetPasswordRequest({
    required String token,
    @JsonKey(name: 'new_password') required String newPassword,
  }) = _ResetPasswordRequest;

  factory ResetPasswordRequest.fromJson(Map<String, dynamic> json) =>
      _$ResetPasswordRequestFromJson(json);
}

// ── Contact Verification ─────────────────────────────────────────────────────

@freezed
class SendOtpRequest with _$SendOtpRequest {
  const factory SendOtpRequest({
    required String type,
    required String value,
  }) = _SendOtpRequest;

  factory SendOtpRequest.fromJson(Map<String, dynamic> json) =>
      _$SendOtpRequestFromJson(json);
}

@freezed
class OtpTokenData with _$OtpTokenData {
  const factory OtpTokenData({
    @JsonKey(name: 'otp_token') required String otpToken,
  }) = _OtpTokenData;

  factory OtpTokenData.fromJson(Map<String, dynamic> json) =>
      _$OtpTokenDataFromJson(json);
}

// ── Register ────────────────────────────────────────────────────────────────

@freezed
class RegisterRequest with _$RegisterRequest {
  const factory RegisterRequest({
    @JsonKey(name: 'first_name') required String firstName,
    @JsonKey(name: 'last_name') required String lastName,
    required String email,
    required String password,
    @JsonKey(name: 'mobile_no') String? mobileNo,
    @JsonKey(name: 'country_id') int? countryId,
    @JsonKey(name: 'state_id') int? stateId,
    @JsonKey(name: 'referral_id') String? referralId,
    @JsonKey(name: 'captcha_token') String? captchaToken,
    @JsonKey(name: 'captcha_answer') String? captchaAnswer,
    @JsonKey(name: 'email_otp_token') String? emailOtpToken,
    @JsonKey(name: 'email_otp_code') String? emailOtpCode,
    @JsonKey(name: 'mobile_otp_token') String? mobileOtpToken,
    @JsonKey(name: 'mobile_otp_code') String? mobileOtpCode,
  }) = _RegisterRequest;

  factory RegisterRequest.fromJson(Map<String, dynamic> json) =>
      _$RegisterRequestFromJson(json);
}

// ── Captcha ──────────────────────────────────────────────────────────────────

@freezed
class CaptchaData with _$CaptchaData {
  const factory CaptchaData({
    required String type,
    String? image,
    String? token,
    @JsonKey(name: 'site_key') String? siteKey,
  }) = _CaptchaData;

  factory CaptchaData.fromJson(Map<String, dynamic> json) =>
      _$CaptchaDataFromJson(json);
}
