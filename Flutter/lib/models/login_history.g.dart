// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'login_history.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$LoginHistoryRecordImpl _$$LoginHistoryRecordImplFromJson(
  Map<String, dynamic> json,
) => _$LoginHistoryRecordImpl(
  tokenId: (json['token_id'] as num).toInt(),
  onDate: json['on_date'] as String,
  ipAddress: json['ip_address'] as String?,
  senderIp: json['sender_ip'] as String?,
  city: json['city'] as String?,
  region: json['region'] as String?,
  country: json['country'] as String?,
  latitude: (json['latitude'] as num?)?.toDouble(),
  longitude: (json['longitude'] as num?)?.toDouble(),
  device: json['device'] as String?,
  deviceType: json['device_type'] as String?,
  os: json['os'] as String?,
  osVersion: json['os_version'] as String?,
  browser: json['browser'] as String?,
  browserVersion: json['browser_version'] as String?,
  loginStatus: json['login_status'] as String? ?? 'active',
  logoutTimestamp: json['logout_timestamp'] as String?,
  byAdminTokenId: (json['by_admin_token_id'] as num?)?.toInt(),
);

Map<String, dynamic> _$$LoginHistoryRecordImplToJson(
  _$LoginHistoryRecordImpl instance,
) => <String, dynamic>{
  'token_id': instance.tokenId,
  'on_date': instance.onDate,
  'ip_address': instance.ipAddress,
  'sender_ip': instance.senderIp,
  'city': instance.city,
  'region': instance.region,
  'country': instance.country,
  'latitude': instance.latitude,
  'longitude': instance.longitude,
  'device': instance.device,
  'device_type': instance.deviceType,
  'os': instance.os,
  'os_version': instance.osVersion,
  'browser': instance.browser,
  'browser_version': instance.browserVersion,
  'login_status': instance.loginStatus,
  'logout_timestamp': instance.logoutTimestamp,
  'by_admin_token_id': instance.byAdminTokenId,
};
