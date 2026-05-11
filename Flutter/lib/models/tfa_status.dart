import 'package:freezed_annotation/freezed_annotation.dart';

part 'tfa_status.freezed.dart';
part 'tfa_status.g.dart';

@freezed
class TfaStatus with _$TfaStatus {
  const factory TfaStatus({
    @JsonKey(name: 'two_factor_enabled') @Default(false) bool twoFactorEnabled,
    @JsonKey(name: 'two_factor_method') String? twoFactorMethod,
    @JsonKey(name: 'masked_email') String? maskedEmail,
    @JsonKey(name: 'masked_mobile') String? maskedMobile,
    @JsonKey(name: 'email_enabled') @Default(false) bool emailEnabled,
    @JsonKey(name: 'sms_enabled') @Default(false) bool smsEnabled,
  }) = _TfaStatus;

  factory TfaStatus.fromJson(Map<String, dynamic> json) =>
      _$TfaStatusFromJson(json);
}

@freezed
class TfaSetupAuthenticatorData with _$TfaSetupAuthenticatorData {
  const factory TfaSetupAuthenticatorData({
    required String secret,
    @JsonKey(name: 'qr_code') required String qrCode,
  }) = _TfaSetupAuthenticatorData;

  factory TfaSetupAuthenticatorData.fromJson(Map<String, dynamic> json) =>
      _$TfaSetupAuthenticatorDataFromJson(json);
}
