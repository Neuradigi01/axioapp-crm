// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'dashboard_data.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$DashboardDataImpl _$$DashboardDataImplFromJson(Map<String, dynamic> json) =>
    _$DashboardDataImpl(
      firstName: json['first_name'] as String,
      lastName: json['last_name'] as String,
      email: json['email'] as String,
      joiningDate: json['joining_date'] as String?,
      twoFactorEnabled: json['two_factor_enabled'] as bool? ?? false,
      referralCount: (json['referral_count'] as num?)?.toInt() ?? 0,
      openTickets: (json['open_tickets'] as num?)?.toInt() ?? 0,
      profileImage: json['profile_image'] as String?,
    );

Map<String, dynamic> _$$DashboardDataImplToJson(_$DashboardDataImpl instance) =>
    <String, dynamic>{
      'first_name': instance.firstName,
      'last_name': instance.lastName,
      'email': instance.email,
      'joining_date': instance.joiningDate,
      'two_factor_enabled': instance.twoFactorEnabled,
      'referral_count': instance.referralCount,
      'open_tickets': instance.openTickets,
      'profile_image': instance.profileImage,
    };
