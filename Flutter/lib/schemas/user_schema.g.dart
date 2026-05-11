// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'user_schema.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$ProfileUpdateRequestImpl _$$ProfileUpdateRequestImplFromJson(
  Map<String, dynamic> json,
) => _$ProfileUpdateRequestImpl(
  firstName: json['first_name'] as String,
  lastName: json['last_name'] as String,
  email: json['email'] as String,
  mobileNo: json['mobile_no'] as String?,
  countryId: (json['country_id'] as num?)?.toInt(),
  stateId: (json['state_id'] as num?)?.toInt(),
);

Map<String, dynamic> _$$ProfileUpdateRequestImplToJson(
  _$ProfileUpdateRequestImpl instance,
) => <String, dynamic>{
  'first_name': instance.firstName,
  'last_name': instance.lastName,
  'email': instance.email,
  'mobile_no': instance.mobileNo,
  'country_id': instance.countryId,
  'state_id': instance.stateId,
};
