// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'tfa_schema.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$SendSetupOtpRequestImpl _$$SendSetupOtpRequestImplFromJson(
  Map<String, dynamic> json,
) => _$SendSetupOtpRequestImpl(method: json['method'] as String);

Map<String, dynamic> _$$SendSetupOtpRequestImplToJson(
  _$SendSetupOtpRequestImpl instance,
) => <String, dynamic>{'method': instance.method};

_$VerifyAndEnableRequestImpl _$$VerifyAndEnableRequestImplFromJson(
  Map<String, dynamic> json,
) => _$VerifyAndEnableRequestImpl(
  code: json['code'] as String,
  method: json['method'] as String,
);

Map<String, dynamic> _$$VerifyAndEnableRequestImplToJson(
  _$VerifyAndEnableRequestImpl instance,
) => <String, dynamic>{'code': instance.code, 'method': instance.method};

_$ChangeMethodRequestImpl _$$ChangeMethodRequestImplFromJson(
  Map<String, dynamic> json,
) => _$ChangeMethodRequestImpl(newMethod: json['new_method'] as String);

Map<String, dynamic> _$$ChangeMethodRequestImplToJson(
  _$ChangeMethodRequestImpl instance,
) => <String, dynamic>{'new_method': instance.newMethod};
