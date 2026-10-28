// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'login_history.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
  'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models',
);

LoginHistoryRecord _$LoginHistoryRecordFromJson(Map<String, dynamic> json) {
  return _LoginHistoryRecord.fromJson(json);
}

/// @nodoc
mixin _$LoginHistoryRecord {
  @JsonKey(name: 'token_id')
  int get tokenId => throw _privateConstructorUsedError;
  @JsonKey(name: 'on_date')
  String get onDate => throw _privateConstructorUsedError;
  @JsonKey(name: 'ip_address')
  String? get ipAddress => throw _privateConstructorUsedError;
  @JsonKey(name: 'sender_ip')
  String? get senderIp => throw _privateConstructorUsedError;
  String? get city => throw _privateConstructorUsedError;
  String? get region => throw _privateConstructorUsedError;
  String? get country => throw _privateConstructorUsedError;
  double? get latitude => throw _privateConstructorUsedError;
  double? get longitude => throw _privateConstructorUsedError;
  String? get device => throw _privateConstructorUsedError;
  @JsonKey(name: 'device_type')
  String? get deviceType => throw _privateConstructorUsedError;
  String? get os => throw _privateConstructorUsedError;
  @JsonKey(name: 'os_version')
  String? get osVersion => throw _privateConstructorUsedError;
  String? get browser => throw _privateConstructorUsedError;
  @JsonKey(name: 'browser_version')
  String? get browserVersion => throw _privateConstructorUsedError;
  @JsonKey(name: 'login_status')
  String get loginStatus => throw _privateConstructorUsedError;
  @JsonKey(name: 'logout_timestamp')
  String? get logoutTimestamp => throw _privateConstructorUsedError;
  @JsonKey(name: 'by_admin_token_id')
  int? get byAdminTokenId => throw _privateConstructorUsedError;

  /// Serializes this LoginHistoryRecord to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of LoginHistoryRecord
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $LoginHistoryRecordCopyWith<LoginHistoryRecord> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $LoginHistoryRecordCopyWith<$Res> {
  factory $LoginHistoryRecordCopyWith(
    LoginHistoryRecord value,
    $Res Function(LoginHistoryRecord) then,
  ) = _$LoginHistoryRecordCopyWithImpl<$Res, LoginHistoryRecord>;
  @useResult
  $Res call({
    @JsonKey(name: 'token_id') int tokenId,
    @JsonKey(name: 'on_date') String onDate,
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
    @JsonKey(name: 'login_status') String loginStatus,
    @JsonKey(name: 'logout_timestamp') String? logoutTimestamp,
    @JsonKey(name: 'by_admin_token_id') int? byAdminTokenId,
  });
}

/// @nodoc
class _$LoginHistoryRecordCopyWithImpl<$Res, $Val extends LoginHistoryRecord>
    implements $LoginHistoryRecordCopyWith<$Res> {
  _$LoginHistoryRecordCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of LoginHistoryRecord
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? tokenId = null,
    Object? onDate = null,
    Object? ipAddress = freezed,
    Object? senderIp = freezed,
    Object? city = freezed,
    Object? region = freezed,
    Object? country = freezed,
    Object? latitude = freezed,
    Object? longitude = freezed,
    Object? device = freezed,
    Object? deviceType = freezed,
    Object? os = freezed,
    Object? osVersion = freezed,
    Object? browser = freezed,
    Object? browserVersion = freezed,
    Object? loginStatus = null,
    Object? logoutTimestamp = freezed,
    Object? byAdminTokenId = freezed,
  }) {
    return _then(
      _value.copyWith(
            tokenId: null == tokenId
                ? _value.tokenId
                : tokenId // ignore: cast_nullable_to_non_nullable
                      as int,
            onDate: null == onDate
                ? _value.onDate
                : onDate // ignore: cast_nullable_to_non_nullable
                      as String,
            ipAddress: freezed == ipAddress
                ? _value.ipAddress
                : ipAddress // ignore: cast_nullable_to_non_nullable
                      as String?,
            senderIp: freezed == senderIp
                ? _value.senderIp
                : senderIp // ignore: cast_nullable_to_non_nullable
                      as String?,
            city: freezed == city
                ? _value.city
                : city // ignore: cast_nullable_to_non_nullable
                      as String?,
            region: freezed == region
                ? _value.region
                : region // ignore: cast_nullable_to_non_nullable
                      as String?,
            country: freezed == country
                ? _value.country
                : country // ignore: cast_nullable_to_non_nullable
                      as String?,
            latitude: freezed == latitude
                ? _value.latitude
                : latitude // ignore: cast_nullable_to_non_nullable
                      as double?,
            longitude: freezed == longitude
                ? _value.longitude
                : longitude // ignore: cast_nullable_to_non_nullable
                      as double?,
            device: freezed == device
                ? _value.device
                : device // ignore: cast_nullable_to_non_nullable
                      as String?,
            deviceType: freezed == deviceType
                ? _value.deviceType
                : deviceType // ignore: cast_nullable_to_non_nullable
                      as String?,
            os: freezed == os
                ? _value.os
                : os // ignore: cast_nullable_to_non_nullable
                      as String?,
            osVersion: freezed == osVersion
                ? _value.osVersion
                : osVersion // ignore: cast_nullable_to_non_nullable
                      as String?,
            browser: freezed == browser
                ? _value.browser
                : browser // ignore: cast_nullable_to_non_nullable
                      as String?,
            browserVersion: freezed == browserVersion
                ? _value.browserVersion
                : browserVersion // ignore: cast_nullable_to_non_nullable
                      as String?,
            loginStatus: null == loginStatus
                ? _value.loginStatus
                : loginStatus // ignore: cast_nullable_to_non_nullable
                      as String,
            logoutTimestamp: freezed == logoutTimestamp
                ? _value.logoutTimestamp
                : logoutTimestamp // ignore: cast_nullable_to_non_nullable
                      as String?,
            byAdminTokenId: freezed == byAdminTokenId
                ? _value.byAdminTokenId
                : byAdminTokenId // ignore: cast_nullable_to_non_nullable
                      as int?,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$LoginHistoryRecordImplCopyWith<$Res>
    implements $LoginHistoryRecordCopyWith<$Res> {
  factory _$$LoginHistoryRecordImplCopyWith(
    _$LoginHistoryRecordImpl value,
    $Res Function(_$LoginHistoryRecordImpl) then,
  ) = __$$LoginHistoryRecordImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({
    @JsonKey(name: 'token_id') int tokenId,
    @JsonKey(name: 'on_date') String onDate,
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
    @JsonKey(name: 'login_status') String loginStatus,
    @JsonKey(name: 'logout_timestamp') String? logoutTimestamp,
    @JsonKey(name: 'by_admin_token_id') int? byAdminTokenId,
  });
}

/// @nodoc
class __$$LoginHistoryRecordImplCopyWithImpl<$Res>
    extends _$LoginHistoryRecordCopyWithImpl<$Res, _$LoginHistoryRecordImpl>
    implements _$$LoginHistoryRecordImplCopyWith<$Res> {
  __$$LoginHistoryRecordImplCopyWithImpl(
    _$LoginHistoryRecordImpl _value,
    $Res Function(_$LoginHistoryRecordImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of LoginHistoryRecord
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? tokenId = null,
    Object? onDate = null,
    Object? ipAddress = freezed,
    Object? senderIp = freezed,
    Object? city = freezed,
    Object? region = freezed,
    Object? country = freezed,
    Object? latitude = freezed,
    Object? longitude = freezed,
    Object? device = freezed,
    Object? deviceType = freezed,
    Object? os = freezed,
    Object? osVersion = freezed,
    Object? browser = freezed,
    Object? browserVersion = freezed,
    Object? loginStatus = null,
    Object? logoutTimestamp = freezed,
    Object? byAdminTokenId = freezed,
  }) {
    return _then(
      _$LoginHistoryRecordImpl(
        tokenId: null == tokenId
            ? _value.tokenId
            : tokenId // ignore: cast_nullable_to_non_nullable
                  as int,
        onDate: null == onDate
            ? _value.onDate
            : onDate // ignore: cast_nullable_to_non_nullable
                  as String,
        ipAddress: freezed == ipAddress
            ? _value.ipAddress
            : ipAddress // ignore: cast_nullable_to_non_nullable
                  as String?,
        senderIp: freezed == senderIp
            ? _value.senderIp
            : senderIp // ignore: cast_nullable_to_non_nullable
                  as String?,
        city: freezed == city
            ? _value.city
            : city // ignore: cast_nullable_to_non_nullable
                  as String?,
        region: freezed == region
            ? _value.region
            : region // ignore: cast_nullable_to_non_nullable
                  as String?,
        country: freezed == country
            ? _value.country
            : country // ignore: cast_nullable_to_non_nullable
                  as String?,
        latitude: freezed == latitude
            ? _value.latitude
            : latitude // ignore: cast_nullable_to_non_nullable
                  as double?,
        longitude: freezed == longitude
            ? _value.longitude
            : longitude // ignore: cast_nullable_to_non_nullable
                  as double?,
        device: freezed == device
            ? _value.device
            : device // ignore: cast_nullable_to_non_nullable
                  as String?,
        deviceType: freezed == deviceType
            ? _value.deviceType
            : deviceType // ignore: cast_nullable_to_non_nullable
                  as String?,
        os: freezed == os
            ? _value.os
            : os // ignore: cast_nullable_to_non_nullable
                  as String?,
        osVersion: freezed == osVersion
            ? _value.osVersion
            : osVersion // ignore: cast_nullable_to_non_nullable
                  as String?,
        browser: freezed == browser
            ? _value.browser
            : browser // ignore: cast_nullable_to_non_nullable
                  as String?,
        browserVersion: freezed == browserVersion
            ? _value.browserVersion
            : browserVersion // ignore: cast_nullable_to_non_nullable
                  as String?,
        loginStatus: null == loginStatus
            ? _value.loginStatus
            : loginStatus // ignore: cast_nullable_to_non_nullable
                  as String,
        logoutTimestamp: freezed == logoutTimestamp
            ? _value.logoutTimestamp
            : logoutTimestamp // ignore: cast_nullable_to_non_nullable
                  as String?,
        byAdminTokenId: freezed == byAdminTokenId
            ? _value.byAdminTokenId
            : byAdminTokenId // ignore: cast_nullable_to_non_nullable
                  as int?,
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$LoginHistoryRecordImpl implements _LoginHistoryRecord {
  const _$LoginHistoryRecordImpl({
    @JsonKey(name: 'token_id') required this.tokenId,
    @JsonKey(name: 'on_date') required this.onDate,
    @JsonKey(name: 'ip_address') this.ipAddress,
    @JsonKey(name: 'sender_ip') this.senderIp,
    this.city,
    this.region,
    this.country,
    this.latitude,
    this.longitude,
    this.device,
    @JsonKey(name: 'device_type') this.deviceType,
    this.os,
    @JsonKey(name: 'os_version') this.osVersion,
    this.browser,
    @JsonKey(name: 'browser_version') this.browserVersion,
    @JsonKey(name: 'login_status') this.loginStatus = 'active',
    @JsonKey(name: 'logout_timestamp') this.logoutTimestamp,
    @JsonKey(name: 'by_admin_token_id') this.byAdminTokenId,
  });

  factory _$LoginHistoryRecordImpl.fromJson(Map<String, dynamic> json) =>
      _$$LoginHistoryRecordImplFromJson(json);

  @override
  @JsonKey(name: 'token_id')
  final int tokenId;
  @override
  @JsonKey(name: 'on_date')
  final String onDate;
  @override
  @JsonKey(name: 'ip_address')
  final String? ipAddress;
  @override
  @JsonKey(name: 'sender_ip')
  final String? senderIp;
  @override
  final String? city;
  @override
  final String? region;
  @override
  final String? country;
  @override
  final double? latitude;
  @override
  final double? longitude;
  @override
  final String? device;
  @override
  @JsonKey(name: 'device_type')
  final String? deviceType;
  @override
  final String? os;
  @override
  @JsonKey(name: 'os_version')
  final String? osVersion;
  @override
  final String? browser;
  @override
  @JsonKey(name: 'browser_version')
  final String? browserVersion;
  @override
  @JsonKey(name: 'login_status')
  final String loginStatus;
  @override
  @JsonKey(name: 'logout_timestamp')
  final String? logoutTimestamp;
  @override
  @JsonKey(name: 'by_admin_token_id')
  final int? byAdminTokenId;

  @override
  String toString() {
    return 'LoginHistoryRecord(tokenId: $tokenId, onDate: $onDate, ipAddress: $ipAddress, senderIp: $senderIp, city: $city, region: $region, country: $country, latitude: $latitude, longitude: $longitude, device: $device, deviceType: $deviceType, os: $os, osVersion: $osVersion, browser: $browser, browserVersion: $browserVersion, loginStatus: $loginStatus, logoutTimestamp: $logoutTimestamp, byAdminTokenId: $byAdminTokenId)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$LoginHistoryRecordImpl &&
            (identical(other.tokenId, tokenId) || other.tokenId == tokenId) &&
            (identical(other.onDate, onDate) || other.onDate == onDate) &&
            (identical(other.ipAddress, ipAddress) ||
                other.ipAddress == ipAddress) &&
            (identical(other.senderIp, senderIp) ||
                other.senderIp == senderIp) &&
            (identical(other.city, city) || other.city == city) &&
            (identical(other.region, region) || other.region == region) &&
            (identical(other.country, country) || other.country == country) &&
            (identical(other.latitude, latitude) ||
                other.latitude == latitude) &&
            (identical(other.longitude, longitude) ||
                other.longitude == longitude) &&
            (identical(other.device, device) || other.device == device) &&
            (identical(other.deviceType, deviceType) ||
                other.deviceType == deviceType) &&
            (identical(other.os, os) || other.os == os) &&
            (identical(other.osVersion, osVersion) ||
                other.osVersion == osVersion) &&
            (identical(other.browser, browser) || other.browser == browser) &&
            (identical(other.browserVersion, browserVersion) ||
                other.browserVersion == browserVersion) &&
            (identical(other.loginStatus, loginStatus) ||
                other.loginStatus == loginStatus) &&
            (identical(other.logoutTimestamp, logoutTimestamp) ||
                other.logoutTimestamp == logoutTimestamp) &&
            (identical(other.byAdminTokenId, byAdminTokenId) ||
                other.byAdminTokenId == byAdminTokenId));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
    runtimeType,
    tokenId,
    onDate,
    ipAddress,
    senderIp,
    city,
    region,
    country,
    latitude,
    longitude,
    device,
    deviceType,
    os,
    osVersion,
    browser,
    browserVersion,
    loginStatus,
    logoutTimestamp,
    byAdminTokenId,
  );

  /// Create a copy of LoginHistoryRecord
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$LoginHistoryRecordImplCopyWith<_$LoginHistoryRecordImpl> get copyWith =>
      __$$LoginHistoryRecordImplCopyWithImpl<_$LoginHistoryRecordImpl>(
        this,
        _$identity,
      );

  @override
  Map<String, dynamic> toJson() {
    return _$$LoginHistoryRecordImplToJson(this);
  }
}

abstract class _LoginHistoryRecord implements LoginHistoryRecord {
  const factory _LoginHistoryRecord({
    @JsonKey(name: 'token_id') required final int tokenId,
    @JsonKey(name: 'on_date') required final String onDate,
    @JsonKey(name: 'ip_address') final String? ipAddress,
    @JsonKey(name: 'sender_ip') final String? senderIp,
    final String? city,
    final String? region,
    final String? country,
    final double? latitude,
    final double? longitude,
    final String? device,
    @JsonKey(name: 'device_type') final String? deviceType,
    final String? os,
    @JsonKey(name: 'os_version') final String? osVersion,
    final String? browser,
    @JsonKey(name: 'browser_version') final String? browserVersion,
    @JsonKey(name: 'login_status') final String loginStatus,
    @JsonKey(name: 'logout_timestamp') final String? logoutTimestamp,
    @JsonKey(name: 'by_admin_token_id') final int? byAdminTokenId,
  }) = _$LoginHistoryRecordImpl;

  factory _LoginHistoryRecord.fromJson(Map<String, dynamic> json) =
      _$LoginHistoryRecordImpl.fromJson;

  @override
  @JsonKey(name: 'token_id')
  int get tokenId;
  @override
  @JsonKey(name: 'on_date')
  String get onDate;
  @override
  @JsonKey(name: 'ip_address')
  String? get ipAddress;
  @override
  @JsonKey(name: 'sender_ip')
  String? get senderIp;
  @override
  String? get city;
  @override
  String? get region;
  @override
  String? get country;
  @override
  double? get latitude;
  @override
  double? get longitude;
  @override
  String? get device;
  @override
  @JsonKey(name: 'device_type')
  String? get deviceType;
  @override
  String? get os;
  @override
  @JsonKey(name: 'os_version')
  String? get osVersion;
  @override
  String? get browser;
  @override
  @JsonKey(name: 'browser_version')
  String? get browserVersion;
  @override
  @JsonKey(name: 'login_status')
  String get loginStatus;
  @override
  @JsonKey(name: 'logout_timestamp')
  String? get logoutTimestamp;
  @override
  @JsonKey(name: 'by_admin_token_id')
  int? get byAdminTokenId;

  /// Create a copy of LoginHistoryRecord
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$LoginHistoryRecordImplCopyWith<_$LoginHistoryRecordImpl> get copyWith =>
      throw _privateConstructorUsedError;
}
