// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'user_profile.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
  'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models',
);

UserProfile _$UserProfileFromJson(Map<String, dynamic> json) {
  return _UserProfile.fromJson(json);
}

/// @nodoc
mixin _$UserProfile {
  @JsonKey(name: 'user_id')
  String get userId => throw _privateConstructorUsedError;
  @JsonKey(name: 'first_name')
  String get firstName => throw _privateConstructorUsedError;
  @JsonKey(name: 'last_name')
  String get lastName => throw _privateConstructorUsedError;
  String get email => throw _privateConstructorUsedError;
  @JsonKey(name: 'mobile_no')
  String? get mobileNo => throw _privateConstructorUsedError;
  @JsonKey(name: 'country_id')
  int? get countryId => throw _privateConstructorUsedError;
  @JsonKey(name: 'state_id')
  int? get stateId => throw _privateConstructorUsedError;
  @JsonKey(name: 'referral_id')
  String? get referralId => throw _privateConstructorUsedError;
  @JsonKey(name: 'profile_image')
  String? get profileImage => throw _privateConstructorUsedError;
  @JsonKey(name: 'joining_date')
  String? get joiningDate => throw _privateConstructorUsedError;
  @JsonKey(name: 'two_factor_enabled')
  bool get twoFactorEnabled => throw _privateConstructorUsedError;
  @JsonKey(name: 'two_factor_method')
  String? get twoFactorMethod => throw _privateConstructorUsedError;
  @JsonKey(name: 'is_active')
  bool get isActive => throw _privateConstructorUsedError;

  /// Serializes this UserProfile to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of UserProfile
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $UserProfileCopyWith<UserProfile> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $UserProfileCopyWith<$Res> {
  factory $UserProfileCopyWith(
    UserProfile value,
    $Res Function(UserProfile) then,
  ) = _$UserProfileCopyWithImpl<$Res, UserProfile>;
  @useResult
  $Res call({
    @JsonKey(name: 'user_id') String userId,
    @JsonKey(name: 'first_name') String firstName,
    @JsonKey(name: 'last_name') String lastName,
    String email,
    @JsonKey(name: 'mobile_no') String? mobileNo,
    @JsonKey(name: 'country_id') int? countryId,
    @JsonKey(name: 'state_id') int? stateId,
    @JsonKey(name: 'referral_id') String? referralId,
    @JsonKey(name: 'profile_image') String? profileImage,
    @JsonKey(name: 'joining_date') String? joiningDate,
    @JsonKey(name: 'two_factor_enabled') bool twoFactorEnabled,
    @JsonKey(name: 'two_factor_method') String? twoFactorMethod,
    @JsonKey(name: 'is_active') bool isActive,
  });
}

/// @nodoc
class _$UserProfileCopyWithImpl<$Res, $Val extends UserProfile>
    implements $UserProfileCopyWith<$Res> {
  _$UserProfileCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of UserProfile
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? userId = null,
    Object? firstName = null,
    Object? lastName = null,
    Object? email = null,
    Object? mobileNo = freezed,
    Object? countryId = freezed,
    Object? stateId = freezed,
    Object? referralId = freezed,
    Object? profileImage = freezed,
    Object? joiningDate = freezed,
    Object? twoFactorEnabled = null,
    Object? twoFactorMethod = freezed,
    Object? isActive = null,
  }) {
    return _then(
      _value.copyWith(
            userId: null == userId
                ? _value.userId
                : userId // ignore: cast_nullable_to_non_nullable
                      as String,
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
            mobileNo: freezed == mobileNo
                ? _value.mobileNo
                : mobileNo // ignore: cast_nullable_to_non_nullable
                      as String?,
            countryId: freezed == countryId
                ? _value.countryId
                : countryId // ignore: cast_nullable_to_non_nullable
                      as int?,
            stateId: freezed == stateId
                ? _value.stateId
                : stateId // ignore: cast_nullable_to_non_nullable
                      as int?,
            referralId: freezed == referralId
                ? _value.referralId
                : referralId // ignore: cast_nullable_to_non_nullable
                      as String?,
            profileImage: freezed == profileImage
                ? _value.profileImage
                : profileImage // ignore: cast_nullable_to_non_nullable
                      as String?,
            joiningDate: freezed == joiningDate
                ? _value.joiningDate
                : joiningDate // ignore: cast_nullable_to_non_nullable
                      as String?,
            twoFactorEnabled: null == twoFactorEnabled
                ? _value.twoFactorEnabled
                : twoFactorEnabled // ignore: cast_nullable_to_non_nullable
                      as bool,
            twoFactorMethod: freezed == twoFactorMethod
                ? _value.twoFactorMethod
                : twoFactorMethod // ignore: cast_nullable_to_non_nullable
                      as String?,
            isActive: null == isActive
                ? _value.isActive
                : isActive // ignore: cast_nullable_to_non_nullable
                      as bool,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$UserProfileImplCopyWith<$Res>
    implements $UserProfileCopyWith<$Res> {
  factory _$$UserProfileImplCopyWith(
    _$UserProfileImpl value,
    $Res Function(_$UserProfileImpl) then,
  ) = __$$UserProfileImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({
    @JsonKey(name: 'user_id') String userId,
    @JsonKey(name: 'first_name') String firstName,
    @JsonKey(name: 'last_name') String lastName,
    String email,
    @JsonKey(name: 'mobile_no') String? mobileNo,
    @JsonKey(name: 'country_id') int? countryId,
    @JsonKey(name: 'state_id') int? stateId,
    @JsonKey(name: 'referral_id') String? referralId,
    @JsonKey(name: 'profile_image') String? profileImage,
    @JsonKey(name: 'joining_date') String? joiningDate,
    @JsonKey(name: 'two_factor_enabled') bool twoFactorEnabled,
    @JsonKey(name: 'two_factor_method') String? twoFactorMethod,
    @JsonKey(name: 'is_active') bool isActive,
  });
}

/// @nodoc
class __$$UserProfileImplCopyWithImpl<$Res>
    extends _$UserProfileCopyWithImpl<$Res, _$UserProfileImpl>
    implements _$$UserProfileImplCopyWith<$Res> {
  __$$UserProfileImplCopyWithImpl(
    _$UserProfileImpl _value,
    $Res Function(_$UserProfileImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of UserProfile
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? userId = null,
    Object? firstName = null,
    Object? lastName = null,
    Object? email = null,
    Object? mobileNo = freezed,
    Object? countryId = freezed,
    Object? stateId = freezed,
    Object? referralId = freezed,
    Object? profileImage = freezed,
    Object? joiningDate = freezed,
    Object? twoFactorEnabled = null,
    Object? twoFactorMethod = freezed,
    Object? isActive = null,
  }) {
    return _then(
      _$UserProfileImpl(
        userId: null == userId
            ? _value.userId
            : userId // ignore: cast_nullable_to_non_nullable
                  as String,
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
        mobileNo: freezed == mobileNo
            ? _value.mobileNo
            : mobileNo // ignore: cast_nullable_to_non_nullable
                  as String?,
        countryId: freezed == countryId
            ? _value.countryId
            : countryId // ignore: cast_nullable_to_non_nullable
                  as int?,
        stateId: freezed == stateId
            ? _value.stateId
            : stateId // ignore: cast_nullable_to_non_nullable
                  as int?,
        referralId: freezed == referralId
            ? _value.referralId
            : referralId // ignore: cast_nullable_to_non_nullable
                  as String?,
        profileImage: freezed == profileImage
            ? _value.profileImage
            : profileImage // ignore: cast_nullable_to_non_nullable
                  as String?,
        joiningDate: freezed == joiningDate
            ? _value.joiningDate
            : joiningDate // ignore: cast_nullable_to_non_nullable
                  as String?,
        twoFactorEnabled: null == twoFactorEnabled
            ? _value.twoFactorEnabled
            : twoFactorEnabled // ignore: cast_nullable_to_non_nullable
                  as bool,
        twoFactorMethod: freezed == twoFactorMethod
            ? _value.twoFactorMethod
            : twoFactorMethod // ignore: cast_nullable_to_non_nullable
                  as String?,
        isActive: null == isActive
            ? _value.isActive
            : isActive // ignore: cast_nullable_to_non_nullable
                  as bool,
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$UserProfileImpl implements _UserProfile {
  const _$UserProfileImpl({
    @JsonKey(name: 'user_id') required this.userId,
    @JsonKey(name: 'first_name') required this.firstName,
    @JsonKey(name: 'last_name') required this.lastName,
    required this.email,
    @JsonKey(name: 'mobile_no') this.mobileNo,
    @JsonKey(name: 'country_id') this.countryId,
    @JsonKey(name: 'state_id') this.stateId,
    @JsonKey(name: 'referral_id') this.referralId,
    @JsonKey(name: 'profile_image') this.profileImage,
    @JsonKey(name: 'joining_date') this.joiningDate,
    @JsonKey(name: 'two_factor_enabled') this.twoFactorEnabled = false,
    @JsonKey(name: 'two_factor_method') this.twoFactorMethod,
    @JsonKey(name: 'is_active') this.isActive = true,
  });

  factory _$UserProfileImpl.fromJson(Map<String, dynamic> json) =>
      _$$UserProfileImplFromJson(json);

  @override
  @JsonKey(name: 'user_id')
  final String userId;
  @override
  @JsonKey(name: 'first_name')
  final String firstName;
  @override
  @JsonKey(name: 'last_name')
  final String lastName;
  @override
  final String email;
  @override
  @JsonKey(name: 'mobile_no')
  final String? mobileNo;
  @override
  @JsonKey(name: 'country_id')
  final int? countryId;
  @override
  @JsonKey(name: 'state_id')
  final int? stateId;
  @override
  @JsonKey(name: 'referral_id')
  final String? referralId;
  @override
  @JsonKey(name: 'profile_image')
  final String? profileImage;
  @override
  @JsonKey(name: 'joining_date')
  final String? joiningDate;
  @override
  @JsonKey(name: 'two_factor_enabled')
  final bool twoFactorEnabled;
  @override
  @JsonKey(name: 'two_factor_method')
  final String? twoFactorMethod;
  @override
  @JsonKey(name: 'is_active')
  final bool isActive;

  @override
  String toString() {
    return 'UserProfile(userId: $userId, firstName: $firstName, lastName: $lastName, email: $email, mobileNo: $mobileNo, countryId: $countryId, stateId: $stateId, referralId: $referralId, profileImage: $profileImage, joiningDate: $joiningDate, twoFactorEnabled: $twoFactorEnabled, twoFactorMethod: $twoFactorMethod, isActive: $isActive)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$UserProfileImpl &&
            (identical(other.userId, userId) || other.userId == userId) &&
            (identical(other.firstName, firstName) ||
                other.firstName == firstName) &&
            (identical(other.lastName, lastName) ||
                other.lastName == lastName) &&
            (identical(other.email, email) || other.email == email) &&
            (identical(other.mobileNo, mobileNo) ||
                other.mobileNo == mobileNo) &&
            (identical(other.countryId, countryId) ||
                other.countryId == countryId) &&
            (identical(other.stateId, stateId) || other.stateId == stateId) &&
            (identical(other.referralId, referralId) ||
                other.referralId == referralId) &&
            (identical(other.profileImage, profileImage) ||
                other.profileImage == profileImage) &&
            (identical(other.joiningDate, joiningDate) ||
                other.joiningDate == joiningDate) &&
            (identical(other.twoFactorEnabled, twoFactorEnabled) ||
                other.twoFactorEnabled == twoFactorEnabled) &&
            (identical(other.twoFactorMethod, twoFactorMethod) ||
                other.twoFactorMethod == twoFactorMethod) &&
            (identical(other.isActive, isActive) ||
                other.isActive == isActive));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
    runtimeType,
    userId,
    firstName,
    lastName,
    email,
    mobileNo,
    countryId,
    stateId,
    referralId,
    profileImage,
    joiningDate,
    twoFactorEnabled,
    twoFactorMethod,
    isActive,
  );

  /// Create a copy of UserProfile
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$UserProfileImplCopyWith<_$UserProfileImpl> get copyWith =>
      __$$UserProfileImplCopyWithImpl<_$UserProfileImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$UserProfileImplToJson(this);
  }
}

abstract class _UserProfile implements UserProfile {
  const factory _UserProfile({
    @JsonKey(name: 'user_id') required final String userId,
    @JsonKey(name: 'first_name') required final String firstName,
    @JsonKey(name: 'last_name') required final String lastName,
    required final String email,
    @JsonKey(name: 'mobile_no') final String? mobileNo,
    @JsonKey(name: 'country_id') final int? countryId,
    @JsonKey(name: 'state_id') final int? stateId,
    @JsonKey(name: 'referral_id') final String? referralId,
    @JsonKey(name: 'profile_image') final String? profileImage,
    @JsonKey(name: 'joining_date') final String? joiningDate,
    @JsonKey(name: 'two_factor_enabled') final bool twoFactorEnabled,
    @JsonKey(name: 'two_factor_method') final String? twoFactorMethod,
    @JsonKey(name: 'is_active') final bool isActive,
  }) = _$UserProfileImpl;

  factory _UserProfile.fromJson(Map<String, dynamic> json) =
      _$UserProfileImpl.fromJson;

  @override
  @JsonKey(name: 'user_id')
  String get userId;
  @override
  @JsonKey(name: 'first_name')
  String get firstName;
  @override
  @JsonKey(name: 'last_name')
  String get lastName;
  @override
  String get email;
  @override
  @JsonKey(name: 'mobile_no')
  String? get mobileNo;
  @override
  @JsonKey(name: 'country_id')
  int? get countryId;
  @override
  @JsonKey(name: 'state_id')
  int? get stateId;
  @override
  @JsonKey(name: 'referral_id')
  String? get referralId;
  @override
  @JsonKey(name: 'profile_image')
  String? get profileImage;
  @override
  @JsonKey(name: 'joining_date')
  String? get joiningDate;
  @override
  @JsonKey(name: 'two_factor_enabled')
  bool get twoFactorEnabled;
  @override
  @JsonKey(name: 'two_factor_method')
  String? get twoFactorMethod;
  @override
  @JsonKey(name: 'is_active')
  bool get isActive;

  /// Create a copy of UserProfile
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$UserProfileImplCopyWith<_$UserProfileImpl> get copyWith =>
      throw _privateConstructorUsedError;
}
