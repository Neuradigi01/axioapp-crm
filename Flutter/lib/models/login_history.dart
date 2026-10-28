import 'package:freezed_annotation/freezed_annotation.dart';

part 'login_history.freezed.dart';
part 'login_history.g.dart';

@freezed
class LoginHistoryRecord with _$LoginHistoryRecord {
  const factory LoginHistoryRecord({
    @JsonKey(name: 'token_id') required int tokenId,
    @JsonKey(name: 'on_date') required String onDate,
    @JsonKey(name: 'ip_address') String? ipAddress,
    @JsonKey(name: 'sender_ip') String? senderIp,
    String? city,
    String? region,
    String? country,
    double? latitude,
    double? longitude,
    String? device,
    @JsonKey(name: 'device_type') String? deviceType,
    String? os,
    @JsonKey(name: 'os_version') String? osVersion,
    String? browser,
    @JsonKey(name: 'browser_version') String? browserVersion,
    @JsonKey(name: 'login_status') @Default('active') String loginStatus,
    @JsonKey(name: 'logout_timestamp') String? logoutTimestamp,
    @JsonKey(name: 'by_admin_token_id') int? byAdminTokenId,
  }) = _LoginHistoryRecord;

  factory LoginHistoryRecord.fromJson(Map<String, dynamic> json) =>
      _$LoginHistoryRecordFromJson(json);
}
