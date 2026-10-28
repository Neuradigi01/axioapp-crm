// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'user_profile.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$UserProfileImpl _$$UserProfileImplFromJson(Map<String, dynamic> json) =>
    _$UserProfileImpl(
      userId: json['user_id'] as String,
      firstName: json['first_name'] as String,
      lastName: json['last_name'] as String,
      email: json['email'] as String,
      mobileNo: json['mobile_no'] as String?,
      countryId: (json['country_id'] as num?)?.toInt(),
      stateId: (json['state_id'] as num?)?.toInt(),
      referralId: json['referral_id'] as String?,
      profileImage: json['profile_image'] as String?,
      joiningDate: json['joining_date'] as String?,
      twoFactorEnabled: json['two_factor_enabled'] as bool? ?? false,
      twoFactorMethod: json['two_factor_method'] as String?,
      isActive: json['is_active'] as bool? ?? true,
    );

Map<String, dynamic> _$$UserProfileImplToJson(_$UserProfileImpl instance) =>
    <String, dynamic>{
      'user_id': instance.userId,
      'first_name': instance.firstName,
      'last_name': instance.lastName,
      'email': instance.email,
      'mobile_no': instance.mobileNo,
      'country_id': instance.countryId,
      'state_id': instance.stateId,
      'referral_id': instance.referralId,
      'profile_image': instance.profileImage,
      'joining_date': instance.joiningDate,
      'two_factor_enabled': instance.twoFactorEnabled,
      'two_factor_method': instance.twoFactorMethod,
      'is_active': instance.isActive,
    };
