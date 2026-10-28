// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'tfa_status.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$TfaStatusImpl _$$TfaStatusImplFromJson(Map<String, dynamic> json) =>
    _$TfaStatusImpl(
      twoFactorEnabled: json['two_factor_enabled'] as bool? ?? false,
      twoFactorMethod: json['two_factor_method'] as String?,
      maskedEmail: json['masked_email'] as String?,
      maskedMobile: json['masked_mobile'] as String?,
      emailEnabled: json['email_enabled'] as bool? ?? false,
      smsEnabled: json['sms_enabled'] as bool? ?? false,
    );

Map<String, dynamic> _$$TfaStatusImplToJson(_$TfaStatusImpl instance) =>
    <String, dynamic>{
      'two_factor_enabled': instance.twoFactorEnabled,
      'two_factor_method': instance.twoFactorMethod,
      'masked_email': instance.maskedEmail,
      'masked_mobile': instance.maskedMobile,
      'email_enabled': instance.emailEnabled,
      'sms_enabled': instance.smsEnabled,
    };

_$TfaSetupAuthenticatorDataImpl _$$TfaSetupAuthenticatorDataImplFromJson(
  Map<String, dynamic> json,
) => _$TfaSetupAuthenticatorDataImpl(
  secret: json['secret'] as String,
  qrCode: json['qr_code'] as String,
);

Map<String, dynamic> _$$TfaSetupAuthenticatorDataImplToJson(
  _$TfaSetupAuthenticatorDataImpl instance,
) => <String, dynamic>{'secret': instance.secret, 'qr_code': instance.qrCode};
