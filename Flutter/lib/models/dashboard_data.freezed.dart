// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'dashboard_data.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
  'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models',
);

DashboardData _$DashboardDataFromJson(Map<String, dynamic> json) {
  return _DashboardData.fromJson(json);
}

/// @nodoc
mixin _$DashboardData {
  @JsonKey(name: 'first_name')
  String get firstName => throw _privateConstructorUsedError;
  @JsonKey(name: 'last_name')
  String get lastName => throw _privateConstructorUsedError;
  String get email => throw _privateConstructorUsedError;
  @JsonKey(name: 'joining_date')
  String? get joiningDate => throw _privateConstructorUsedError;
  @JsonKey(name: 'two_factor_enabled')
  bool get twoFactorEnabled => throw _privateConstructorUsedError;
  @JsonKey(name: 'referral_count')
  int get referralCount => throw _privateConstructorUsedError;
  @JsonKey(name: 'open_tickets')
  int get openTickets => throw _privateConstructorUsedError;
  @JsonKey(name: 'profile_image')
  String? get profileImage => throw _privateConstructorUsedError;

  /// Serializes this DashboardData to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of DashboardData
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $DashboardDataCopyWith<DashboardData> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $DashboardDataCopyWith<$Res> {
  factory $DashboardDataCopyWith(
    DashboardData value,
    $Res Function(DashboardData) then,
  ) = _$DashboardDataCopyWithImpl<$Res, DashboardData>;
  @useResult
  $Res call({
    @JsonKey(name: 'first_name') String firstName,
    @JsonKey(name: 'last_name') String lastName,
    String email,
    @JsonKey(name: 'joining_date') String? joiningDate,
    @JsonKey(name: 'two_factor_enabled') bool twoFactorEnabled,
    @JsonKey(name: 'referral_count') int referralCount,
    @JsonKey(name: 'open_tickets') int openTickets,
    @JsonKey(name: 'profile_image') String? profileImage,
  });
}

/// @nodoc
class _$DashboardDataCopyWithImpl<$Res, $Val extends DashboardData>
    implements $DashboardDataCopyWith<$Res> {
  _$DashboardDataCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of DashboardData
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? firstName = null,
    Object? lastName = null,
    Object? email = null,
    Object? joiningDate = freezed,
    Object? twoFactorEnabled = null,
    Object? referralCount = null,
    Object? openTickets = null,
    Object? profileImage = freezed,
  }) {
    return _then(
      _value.copyWith(
            firstName: null == firstName
                ? _value.firstName
                : firstName // ignore: cast_nullable_to_non_nullable
                      as String,
            lastName: null == lastName
                ? _value.lastName
                : lastName // ignore: cast_nullable_to_non_nullable
                      as String,
            email: null == email
                ? _value.email
                : email // ignore: cast_nullable_to_non_nullable
                      as String,
            joiningDate: freezed == joiningDate
                ? _value.joiningDate
                : joiningDate // ignore: cast_nullable_to_non_nullable
                      as String?,
            twoFactorEnabled: null == twoFactorEnabled
                ? _value.twoFactorEnabled
                : twoFactorEnabled // ignore: cast_nullable_to_non_nullable
                      as bool,
            referralCount: null == referralCount
                ? _value.referralCount
                : referralCount // ignore: cast_nullable_to_non_nullable
                      as int,
            openTickets: null == openTickets
                ? _value.openTickets
                : openTickets // ignore: cast_nullable_to_non_nullable
                      as int,
            profileImage: freezed == profileImage
                ? _value.profileImage
                : profileImage // ignore: cast_nullable_to_non_nullable
                      as String?,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$DashboardDataImplCopyWith<$Res>
    implements $DashboardDataCopyWith<$Res> {
  factory _$$DashboardDataImplCopyWith(
    _$DashboardDataImpl value,
    $Res Function(_$DashboardDataImpl) then,
  ) = __$$DashboardDataImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({
    @JsonKey(name: 'first_name') String firstName,
    @JsonKey(name: 'last_name') String lastName,
    String email,
    @JsonKey(name: 'joining_date') String? joiningDate,
    @JsonKey(name: 'two_factor_enabled') bool twoFactorEnabled,
    @JsonKey(name: 'referral_count') int referralCount,
    @JsonKey(name: 'open_tickets') int openTickets,
    @JsonKey(name: 'profile_image') String? profileImage,
  });
}

/// @nodoc
class __$$DashboardDataImplCopyWithImpl<$Res>
    extends _$DashboardDataCopyWithImpl<$Res, _$DashboardDataImpl>
    implements _$$DashboardDataImplCopyWith<$Res> {
  __$$DashboardDataImplCopyWithImpl(
    _$DashboardDataImpl _value,
    $Res Function(_$DashboardDataImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of DashboardData
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? firstName = null,
    Object? lastName = null,
    Object? email = null,
    Object? joiningDate = freezed,
    Object? twoFactorEnabled = null,
    Object? referralCount = null,
    Object? openTickets = null,
    Object? profileImage = freezed,
  }) {
    return _then(
      _$DashboardDataImpl(
        firstName: null == firstName
            ? _value.firstName
            : firstName // ignore: cast_nullable_to_non_nullable
                  as String,
        lastName: null == lastName
            ? _value.lastName
            : lastName // ignore: cast_nullable_to_non_nullable
                  as String,
        email: null == email
            ? _value.email
            : email // ignore: cast_nullable_to_non_nullable
                  as String,
        joiningDate: freezed == joiningDate
            ? _value.joiningDate
            : joiningDate // ignore: cast_nullable_to_non_nullable
                  as String?,
        twoFactorEnabled: null == twoFactorEnabled
            ? _value.twoFactorEnabled
            : twoFactorEnabled // ignore: cast_nullable_to_non_nullable
                  as bool,
        referralCount: null == referralCount
            ? _value.referralCount
            : referralCount // ignore: cast_nullable_to_non_nullable
                  as int,
        openTickets: null == openTickets
            ? _value.openTickets
            : openTickets // ignore: cast_nullable_to_non_nullable
                  as int,
        profileImage: freezed == profileImage
            ? _value.profileImage
            : profileImage // ignore: cast_nullable_to_non_nullable
                  as String?,
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$DashboardDataImpl implements _DashboardData {
  const _$DashboardDataImpl({
    @JsonKey(name: 'first_name') required this.firstName,
    @JsonKey(name: 'last_name') required this.lastName,
    required this.email,
    @JsonKey(name: 'joining_date') this.joiningDate,
    @JsonKey(name: 'two_factor_enabled') this.twoFactorEnabled = false,
    @JsonKey(name: 'referral_count') this.referralCount = 0,
    @JsonKey(name: 'open_tickets') this.openTickets = 0,
    @JsonKey(name: 'profile_image') this.profileImage,
  });

  factory _$DashboardDataImpl.fromJson(Map<String, dynamic> json) =>
      _$$DashboardDataImplFromJson(json);

  @override
  @JsonKey(name: 'first_name')
  final String firstName;
  @override
  @JsonKey(name: 'last_name')
  final String lastName;
  @override
  final String email;
  @override
  @JsonKey(name: 'joining_date')
  final String? joiningDate;
  @override
  @JsonKey(name: 'two_factor_enabled')
  final bool twoFactorEnabled;
  @override
  @JsonKey(name: 'referral_count')
  final int referralCount;
  @override
  @JsonKey(name: 'open_tickets')
  final int openTickets;
  @override
  @JsonKey(name: 'profile_image')
  final String? profileImage;

  @override
  String toString() {
    return 'DashboardData(firstName: $firstName, lastName: $lastName, email: $email, joiningDate: $joiningDate, twoFactorEnabled: $twoFactorEnabled, referralCount: $referralCount, openTickets: $openTickets, profileImage: $profileImage)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$DashboardDataImpl &&
            (identical(other.firstName, firstName) ||
                other.firstName == firstName) &&
            (identical(other.lastName, lastName) ||
                other.lastName == lastName) &&
            (identical(other.email, email) || other.email == email) &&
            (identical(other.joiningDate, joiningDate) ||
                other.joiningDate == joiningDate) &&
            (identical(other.twoFactorEnabled, twoFactorEnabled) ||
                other.twoFactorEnabled == twoFactorEnabled) &&
            (identical(other.referralCount, referralCount) ||
                other.referralCount == referralCount) &&
            (identical(other.openTickets, openTickets) ||
                other.openTickets == openTickets) &&
            (identical(other.profileImage, profileImage) ||
                other.profileImage == profileImage));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
    runtimeType,
    firstName,
    lastName,
    email,
    joiningDate,
    twoFactorEnabled,
    referralCount,
    openTickets,
    profileImage,
  );

  /// Create a copy of DashboardData
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$DashboardDataImplCopyWith<_$DashboardDataImpl> get copyWith =>
      __$$DashboardDataImplCopyWithImpl<_$DashboardDataImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$DashboardDataImplToJson(this);
  }
}

abstract class _DashboardData implements DashboardData {
  const factory _DashboardData({
    @JsonKey(name: 'first_name') required final String firstName,
    @JsonKey(name: 'last_name') required final String lastName,
    required final String email,
    @JsonKey(name: 'joining_date') final String? joiningDate,
    @JsonKey(name: 'two_factor_enabled') final bool twoFactorEnabled,
    @JsonKey(name: 'referral_count') final int referralCount,
    @JsonKey(name: 'open_tickets') final int openTickets,
    @JsonKey(name: 'profile_image') final String? profileImage,
  }) = _$DashboardDataImpl;

  factory _DashboardData.fromJson(Map<String, dynamic> json) =
      _$DashboardDataImpl.fromJson;

  @override
  @JsonKey(name: 'first_name')
  String get firstName;
  @override
  @JsonKey(name: 'last_name')
  String get lastName;
  @override
  String get email;
  @override
  @JsonKey(name: 'joining_date')
  String? get joiningDate;
  @override
  @JsonKey(name: 'two_factor_enabled')
  bool get twoFactorEnabled;
  @override
  @JsonKey(name: 'referral_count')
  int get referralCount;
  @override
  @JsonKey(name: 'open_tickets')
  int get openTickets;
  @override
  @JsonKey(name: 'profile_image')
  String? get profileImage;

  /// Create a copy of DashboardData
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$DashboardDataImplCopyWith<_$DashboardDataImpl> get copyWith =>
      throw _privateConstructorUsedError;
}
