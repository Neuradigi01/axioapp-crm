// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'auth_schema.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$LoginRequestImpl _$$LoginRequestImplFromJson(Map<String, dynamic> json) =>
    _$LoginRequestImpl(
      identifier: json['identifier'] as String,
      password: json['password'] as String,
      twoFactorCode: json['two_factor_code'] as String?,
      twoFactorMethod: json['two_factor_method'] as String?,
      deviceInfo: (json['device_info'] as Map<String, dynamic>?)?.map(
        (k, e) => MapEntry(k, e as String),
      ),
      captchaToken: json['captcha_token'] as String?,
      captchaAnswer: json['captcha_answer'] as String?,
    );

Map<String, dynamic> _$$LoginRequestImplToJson(_$LoginRequestImpl instance) =>
    <String, dynamic>{
      'identifier': instance.identifier,
      'password': instance.password,
      'two_factor_code': instance.twoFactorCode,
      'two_factor_method': instance.twoFactorMethod,
      'device_info': instance.deviceInfo,
      'captcha_token': instance.captchaToken,
      'captcha_answer': instance.captchaAnswer,
    };

_$LoginDataImpl _$$LoginDataImplFromJson(Map<String, dynamic> json) =>
    _$LoginDataImpl(
      token: json['token'] as String,
      userId: json['user_id'] as String,
      role: json['role'] as String,
      firstName: json['first_name'] as String?,
      lastName: json['last_name'] as String?,
      name: json['name'] as String?,
      email: json['email'] as String,
      isSuperAdmin: json['is_super_admin'] as bool? ?? false,
    );

Map<String, dynamic> _$$LoginDataImplToJson(_$LoginDataImpl instance) =>
    <String, dynamic>{
      'token': instance.token,
      'user_id': instance.userId,
      'role': instance.role,
      'first_name': instance.firstName,
      'last_name': instance.lastName,
      'name': instance.name,
      'email': instance.email,
      'is_super_admin': instance.isSuperAdmin,
    };

_$TfaRequiredDataImpl _$$TfaRequiredDataImplFromJson(
  Map<String, dynamic> json,
) => _$TfaRequiredDataImpl(
  requires2fa: json['requires_2fa'] as bool? ?? true,
  method: json['method'] as String,
  availableMethods: (json['available_methods'] as List<dynamic>)
      .map((e) => e as String)
      .toList(),
);

Map<String, dynamic> _$$TfaRequiredDataImplToJson(
  _$TfaRequiredDataImpl instance,
) => <String, dynamic>{
  'requires_2fa': instance.requires2fa,
  'method': instance.method,
  'available_methods': instance.availableMethods,
};

_$EmailVerificationRequiredDataImpl
_$$EmailVerificationRequiredDataImplFromJson(Map<String, dynamic> json) =>
    _$EmailVerificationRequiredDataImpl(
      requiresEmailVerification:
          json['requires_email_verification'] as bool? ?? true,
    );

Map<String, dynamic> _$$EmailVerificationRequiredDataImplToJson(
  _$EmailVerificationRequiredDataImpl instance,
) => <String, dynamic>{
  'requires_email_verification': instance.requiresEmailVerification,
};

_$TryAnotherWayRequestImpl _$$TryAnotherWayRequestImplFromJson(
  Map<String, dynamic> json,
) => _$TryAnotherWayRequestImpl(
  identifier: json['identifier'] as String,
  password: json['password'] as String,
  userType: json['user_type'] as String,
  method: json['method'] as String,
);

Map<String, dynamic> _$$TryAnotherWayRequestImplToJson(
  _$TryAnotherWayRequestImpl instance,
) => <String, dynamic>{
  'identifier': instance.identifier,
  'password': instance.password,
  'user_type': instance.userType,
  'method': instance.method,
};

_$TryAnotherWayDataImpl _$$TryAnotherWayDataImplFromJson(
  Map<String, dynamic> json,
) => _$TryAnotherWayDataImpl(
  method: json['method'] as String,
  availableMethods: (json['available_methods'] as List<dynamic>)
      .map((e) => e as String)
      .toList(),
);

Map<String, dynamic> _$$TryAnotherWayDataImplToJson(
  _$TryAnotherWayDataImpl instance,
) => <String, dynamic>{
  'method': instance.method,
  'available_methods': instance.availableMethods,
};

_$ForgotPasswordRequestImpl _$$ForgotPasswordRequestImplFromJson(
  Map<String, dynamic> json,
) => _$ForgotPasswordRequestImpl(identifier: json['identifier'] as String);

Map<String, dynamic> _$$ForgotPasswordRequestImplToJson(
  _$ForgotPasswordRequestImpl instance,
) => <String, dynamic>{'identifier': instance.identifier};

_$ResetPasswordRequestImpl _$$ResetPasswordRequestImplFromJson(
  Map<String, dynamic> json,
) => _$ResetPasswordRequestImpl(
  token: json['token'] as String,
  newPassword: json['new_password'] as String,
);

Map<String, dynamic> _$$ResetPasswordRequestImplToJson(
  _$ResetPasswordRequestImpl instance,
) => <String, dynamic>{
  'token': instance.token,
  'new_password': instance.newPassword,
};

_$SendOtpRequestImpl _$$SendOtpRequestImplFromJson(Map<String, dynamic> json) =>
    _$SendOtpRequestImpl(
      type: json['type'] as String,
      value: json['value'] as String,
    );

Map<String, dynamic> _$$SendOtpRequestImplToJson(
  _$SendOtpRequestImpl instance,
) => <String, dynamic>{'type': instance.type, 'value': instance.value};

_$OtpTokenDataImpl _$$OtpTokenDataImplFromJson(Map<String, dynamic> json) =>
    _$OtpTokenDataImpl(otpToken: json['otp_token'] as String);

Map<String, dynamic> _$$OtpTokenDataImplToJson(_$OtpTokenDataImpl instance) =>
    <String, dynamic>{'otp_token': instance.otpToken};

_$RegisterRequestImpl _$$RegisterRequestImplFromJson(
  Map<String, dynamic> json,
) => _$RegisterRequestImpl(
  firstName: json['first_name'] as String,
  lastName: json['last_name'] as String,
  email: json['email'] as String,
  password: json['password'] as String,
  mobileNo: json['mobile_no'] as String?,
  countryId: (json['country_id'] as num?)?.toInt(),
  stateId: (json['state_id'] as num?)?.toInt(),
  referralId: json['referral_id'] as String?,
  captchaToken: json['captcha_token'] as String?,
  captchaAnswer: json['captcha_answer'] as String?,
  emailOtpToken: json['email_otp_token'] as String?,
  emailOtpCode: json['email_otp_code'] as String?,
  mobileOtpToken: json['mobile_otp_token'] as String?,
  mobileOtpCode: json['mobile_otp_code'] as String?,
);

Map<String, dynamic> _$$RegisterRequestImplToJson(
  _$RegisterRequestImpl instance,
) => <String, dynamic>{
  'first_name': instance.firstName,
  'last_name': instance.lastName,
  'email': instance.email,
  'password': instance.password,
  'mobile_no': instance.mobileNo,
  'country_id': instance.countryId,
  'state_id': instance.stateId,
  'referral_id': instance.referralId,
  'captcha_token': instance.captchaToken,
  'captcha_answer': instance.captchaAnswer,
  'email_otp_token': instance.emailOtpToken,
  'email_otp_code': instance.emailOtpCode,
  'mobile_otp_token': instance.mobileOtpToken,
  'mobile_otp_code': instance.mobileOtpCode,
};

_$CaptchaDataImpl _$$CaptchaDataImplFromJson(Map<String, dynamic> json) =>
    _$CaptchaDataImpl(
      type: json['type'] as String,
      image: json['image'] as String?,
      token: json['token'] as String?,
      siteKey: json['site_key'] as String?,
    );

Map<String, dynamic> _$$CaptchaDataImplToJson(_$CaptchaDataImpl instance) =>
    <String, dynamic>{
      'type': instance.type,
      'image': instance.image,
      'token': instance.token,
      'site_key': instance.siteKey,
    };
