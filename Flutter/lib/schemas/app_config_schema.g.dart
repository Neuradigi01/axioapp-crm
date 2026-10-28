// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'app_config_schema.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$AppConfigDataImpl _$$AppConfigDataImplFromJson(Map<String, dynamic> json) =>
    _$AppConfigDataImpl(
      captchaEnabled: json['captcha_enabled'] as bool? ?? false,
      emailEnabled: json['email_enabled'] as bool? ?? false,
      smsEnabled: json['sms_enabled'] as bool? ?? false,
      contactVerificationMode:
          json['contact_verification_mode'] as String? ?? 'none',
      pushNotificationEnabled:
          json['push_notification_enabled'] as bool? ?? false,
      firebaseConfig: json['firebase_config'] as Map<String, dynamic>?,
    );

Map<String, dynamic> _$$AppConfigDataImplToJson(_$AppConfigDataImpl instance) =>
    <String, dynamic>{
      'captcha_enabled': instance.captchaEnabled,
      'email_enabled': instance.emailEnabled,
      'sms_enabled': instance.smsEnabled,
      'contact_verification_mode': instance.contactVerificationMode,
      'push_notification_enabled': instance.pushNotificationEnabled,
      'firebase_config': instance.firebaseConfig,
    };
