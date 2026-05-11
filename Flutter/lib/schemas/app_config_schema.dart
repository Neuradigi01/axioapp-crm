import 'package:freezed_annotation/freezed_annotation.dart';

part 'app_config_schema.freezed.dart';
part 'app_config_schema.g.dart';

@freezed
class AppConfigData with _$AppConfigData {
  const factory AppConfigData({
    @JsonKey(name: 'captcha_enabled') @Default(false) bool captchaEnabled,
    @JsonKey(name: 'email_enabled') @Default(false) bool emailEnabled,
    @JsonKey(name: 'sms_enabled') @Default(false) bool smsEnabled,
    @JsonKey(name: 'contact_verification_mode')
    @Default('none')
    String contactVerificationMode,
    @JsonKey(name: 'push_notification_enabled')
    @Default(false)
    bool pushNotificationEnabled,
    @JsonKey(name: 'firebase_config')
    Map<String, dynamic>? firebaseConfig,
  }) = _AppConfigData;

  factory AppConfigData.fromJson(Map<String, dynamic> json) =>
      _$AppConfigDataFromJson(json);
}
