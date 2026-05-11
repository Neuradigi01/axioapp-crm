// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'user_schema.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
  'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models',
);

ProfileUpdateRequest _$ProfileUpdateRequestFromJson(Map<String, dynamic> json) {
  return _ProfileUpdateRequest.fromJson(json);
}

/// @nodoc
mixin _$ProfileUpdateRequest {
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

  /// Serializes this ProfileUpdateRequest to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of ProfileUpdateRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $ProfileUpdateRequestCopyWith<ProfileUpdateRequest> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $ProfileUpdateRequestCopyWith<$Res> {
  factory $ProfileUpdateRequestCopyWith(
    ProfileUpdateRequest value,
    $Res Function(ProfileUpdateRequest) then,
  ) = _$ProfileUpdateRequestCopyWithImpl<$Res, ProfileUpdateRequest>;
  @useResult
  $Res call({
    @JsonKey(name: 'first_name') String firstName,
    @JsonKey(name: 'last_name') String lastName,
    String email,
    @JsonKey(name: 'mobile_no') String? mobileNo,
    @JsonKey(name: 'country_id') int? countryId,
    @JsonKey(name: 'state_id') int? stateId,
  });
}

/// @nodoc
class _$ProfileUpdateRequestCopyWithImpl<
  $Res,
  $Val extends ProfileUpdateRequest
>
    implements $ProfileUpdateRequestCopyWith<$Res> {
  _$ProfileUpdateRequestCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of ProfileUpdateRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? firstName = null,
    Object? lastName = null,
    Object? email = null,
    Object? mobileNo = freezed,
    Object? countryId = freezed,
    Object? stateId = freezed,
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
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$ProfileUpdateRequestImplCopyWith<$Res>
    implements $ProfileUpdateRequestCopyWith<$Res> {
  factory _$$ProfileUpdateRequestImplCopyWith(
    _$ProfileUpdateRequestImpl value,
    $Res Function(_$ProfileUpdateRequestImpl) then,
  ) = __$$ProfileUpdateRequestImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({
    @JsonKey(name: 'first_name') String firstName,
    @JsonKey(name: 'last_name') String lastName,
    String email,
    @JsonKey(name: 'mobile_no') String? mobileNo,
    @JsonKey(name: 'country_id') int? countryId,
    @JsonKey(name: 'state_id') int? stateId,
  });
}

/// @nodoc
class __$$ProfileUpdateRequestImplCopyWithImpl<$Res>
    extends _$ProfileUpdateRequestCopyWithImpl<$Res, _$ProfileUpdateRequestImpl>
    implements _$$ProfileUpdateRequestImplCopyWith<$Res> {
  __$$ProfileUpdateRequestImplCopyWithImpl(
    _$ProfileUpdateRequestImpl _value,
    $Res Function(_$ProfileUpdateRequestImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of ProfileUpdateRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? firstName = null,
    Object? lastName = null,
    Object? email = null,
    Object? mobileNo = freezed,
    Object? countryId = freezed,
    Object? stateId = freezed,
  }) {
    return _then(
      _$ProfileUpdateRequestImpl(
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
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$ProfileUpdateRequestImpl implements _ProfileUpdateRequest {
  const _$ProfileUpdateRequestImpl({
    @JsonKey(name: 'first_name') required this.firstName,
    @JsonKey(name: 'last_name') required this.lastName,
    required this.email,
    @JsonKey(name: 'mobile_no') this.mobileNo,
    @JsonKey(name: 'country_id') this.countryId,
    @JsonKey(name: 'state_id') this.stateId,
  });

  factory _$ProfileUpdateRequestImpl.fromJson(Map<String, dynamic> json) =>
      _$$ProfileUpdateRequestImplFromJson(json);

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
  String toString() {
    return 'ProfileUpdateRequest(firstName: $firstName, lastName: $lastName, email: $email, mobileNo: $mobileNo, countryId: $countryId, stateId: $stateId)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$ProfileUpdateRequestImpl &&
            (identical(other.firstName, firstName) ||
                other.firstName == firstName) &&
            (identical(other.lastName, lastName) ||
                other.lastName == lastName) &&
            (identical(other.email, email) || other.email == email) &&
            (identical(other.mobileNo, mobileNo) ||
                other.mobileNo == mobileNo) &&
            (identical(other.countryId, countryId) ||
                other.countryId == countryId) &&
            (identical(other.stateId, stateId) || other.stateId == stateId));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
    runtimeType,
    firstName,
    lastName,
    email,
    mobileNo,
    countryId,
    stateId,
  );

  /// Create a copy of ProfileUpdateRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$ProfileUpdateRequestImplCopyWith<_$ProfileUpdateRequestImpl>
  get copyWith =>
      __$$ProfileUpdateRequestImplCopyWithImpl<_$ProfileUpdateRequestImpl>(
        this,
        _$identity,
      );

  @override
  Map<String, dynamic> toJson() {
    return _$$ProfileUpdateRequestImplToJson(this);
  }
}

abstract class _ProfileUpdateRequest implements ProfileUpdateRequest {
  const factory _ProfileUpdateRequest({
    @JsonKey(name: 'first_name') required final String firstName,
    @JsonKey(name: 'last_name') required final String lastName,
    required final String email,
    @JsonKey(name: 'mobile_no') final String? mobileNo,
    @JsonKey(name: 'country_id') final int? countryId,
    @JsonKey(name: 'state_id') final int? stateId,
  }) = _$ProfileUpdateRequestImpl;

  factory _ProfileUpdateRequest.fromJson(Map<String, dynamic> json) =
      _$ProfileUpdateRequestImpl.fromJson;

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

  /// Create a copy of ProfileUpdateRequest
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$ProfileUpdateRequestImplCopyWith<_$ProfileUpdateRequestImpl>
  get copyWith => throw _privateConstructorUsedError;
}
