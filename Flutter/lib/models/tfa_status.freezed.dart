// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'tfa_status.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
  'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models',
);

TfaStatus _$TfaStatusFromJson(Map<String, dynamic> json) {
  return _TfaStatus.fromJson(json);
}

/// @nodoc
mixin _$TfaStatus {
  @JsonKey(name: 'two_factor_enabled')
  bool get twoFactorEnabled => throw _privateConstructorUsedError;
  @JsonKey(name: 'two_factor_method')
  String? get twoFactorMethod => throw _privateConstructorUsedError;
  @JsonKey(name: 'masked_email')
  String? get maskedEmail => throw _privateConstructorUsedError;
  @JsonKey(name: 'masked_mobile')
  String? get maskedMobile => throw _privateConstructorUsedError;
  @JsonKey(name: 'email_enabled')
  bool get emailEnabled => throw _privateConstructorUsedError;
  @JsonKey(name: 'sms_enabled')
  bool get smsEnabled => throw _privateConstructorUsedError;

  /// Serializes this TfaStatus to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of TfaStatus
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $TfaStatusCopyWith<TfaStatus> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $TfaStatusCopyWith<$Res> {
  factory $TfaStatusCopyWith(TfaStatus value, $Res Function(TfaStatus) then) =
      _$TfaStatusCopyWithImpl<$Res, TfaStatus>;
  @useResult
  $Res call({
    @JsonKey(name: 'two_factor_enabled') bool twoFactorEnabled,
    @JsonKey(name: 'two_factor_method') String? twoFactorMethod,
    @JsonKey(name: 'masked_email') String? maskedEmail,
    @JsonKey(name: 'masked_mobile') String? maskedMobile,
    @JsonKey(name: 'email_enabled') bool emailEnabled,
    @JsonKey(name: 'sms_enabled') bool smsEnabled,
  });
}

/// @nodoc
class _$TfaStatusCopyWithImpl<$Res, $Val extends TfaStatus>
    implements $TfaStatusCopyWith<$Res> {
  _$TfaStatusCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of TfaStatus
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? twoFactorEnabled = null,
    Object? twoFactorMethod = freezed,
    Object? maskedEmail = freezed,
    Object? maskedMobile = freezed,
    Object? emailEnabled = null,
    Object? smsEnabled = null,
  }) {
    return _then(
      _value.copyWith(
            twoFactorEnabled: null == twoFactorEnabled
                ? _value.twoFactorEnabled
                : twoFactorEnabled // ignore: cast_nullable_to_non_nullable
                      as bool,
            twoFactorMethod: freezed == twoFactorMethod
                ? _value.twoFactorMethod
                : twoFactorMethod // ignore: cast_nullable_to_non_nullable
                      as String?,
            maskedEmail: freezed == maskedEmail
                ? _value.maskedEmail
                : maskedEmail // ignore: cast_nullable_to_non_nullable
                      as String?,
            maskedMobile: freezed == maskedMobile
                ? _value.maskedMobile
                : maskedMobile // ignore: cast_nullable_to_non_nullable
                      as String?,
            emailEnabled: null == emailEnabled
                ? _value.emailEnabled
                : emailEnabled // ignore: cast_nullable_to_non_nullable
                      as bool,
            smsEnabled: null == smsEnabled
                ? _value.smsEnabled
                : smsEnabled // ignore: cast_nullable_to_non_nullable
                      as bool,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$TfaStatusImplCopyWith<$Res>
    implements $TfaStatusCopyWith<$Res> {
  factory _$$TfaStatusImplCopyWith(
    _$TfaStatusImpl value,
    $Res Function(_$TfaStatusImpl) then,
  ) = __$$TfaStatusImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({
    @JsonKey(name: 'two_factor_enabled') bool twoFactorEnabled,
    @JsonKey(name: 'two_factor_method') String? twoFactorMethod,
    @JsonKey(name: 'masked_email') String? maskedEmail,
    @JsonKey(name: 'masked_mobile') String? maskedMobile,
    @JsonKey(name: 'email_enabled') bool emailEnabled,
    @JsonKey(name: 'sms_enabled') bool smsEnabled,
  });
}

/// @nodoc
class __$$TfaStatusImplCopyWithImpl<$Res>
    extends _$TfaStatusCopyWithImpl<$Res, _$TfaStatusImpl>
    implements _$$TfaStatusImplCopyWith<$Res> {
  __$$TfaStatusImplCopyWithImpl(
    _$TfaStatusImpl _value,
    $Res Function(_$TfaStatusImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of TfaStatus
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? twoFactorEnabled = null,
    Object? twoFactorMethod = freezed,
    Object? maskedEmail = freezed,
    Object? maskedMobile = freezed,
    Object? emailEnabled = null,
    Object? smsEnabled = null,
  }) {
    return _then(
      _$TfaStatusImpl(
        twoFactorEnabled: null == twoFactorEnabled
            ? _value.twoFactorEnabled
            : twoFactorEnabled // ignore: cast_nullable_to_non_nullable
                  as bool,
        twoFactorMethod: freezed == twoFactorMethod
            ? _value.twoFactorMethod
            : twoFactorMethod // ignore: cast_nullable_to_non_nullable
                  as String?,
        maskedEmail: freezed == maskedEmail
            ? _value.maskedEmail
            : maskedEmail // ignore: cast_nullable_to_non_nullable
                  as String?,
        maskedMobile: freezed == maskedMobile
            ? _value.maskedMobile
            : maskedMobile // ignore: cast_nullable_to_non_nullable
                  as String?,
        emailEnabled: null == emailEnabled
            ? _value.emailEnabled
            : emailEnabled // ignore: cast_nullable_to_non_nullable
                  as bool,
        smsEnabled: null == smsEnabled
            ? _value.smsEnabled
            : smsEnabled // ignore: cast_nullable_to_non_nullable
                  as bool,
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$TfaStatusImpl implements _TfaStatus {
  const _$TfaStatusImpl({
    @JsonKey(name: 'two_factor_enabled') this.twoFactorEnabled = false,
    @JsonKey(name: 'two_factor_method') this.twoFactorMethod,
    @JsonKey(name: 'masked_email') this.maskedEmail,
    @JsonKey(name: 'masked_mobile') this.maskedMobile,
    @JsonKey(name: 'email_enabled') this.emailEnabled = false,
    @JsonKey(name: 'sms_enabled') this.smsEnabled = false,
  });

  factory _$TfaStatusImpl.fromJson(Map<String, dynamic> json) =>
      _$$TfaStatusImplFromJson(json);

  @override
  @JsonKey(name: 'two_factor_enabled')
  final bool twoFactorEnabled;
  @override
  @JsonKey(name: 'two_factor_method')
  final String? twoFactorMethod;
  @override
  @JsonKey(name: 'masked_email')
  final String? maskedEmail;
  @override
  @JsonKey(name: 'masked_mobile')
  final String? maskedMobile;
  @override
  @JsonKey(name: 'email_enabled')
  final bool emailEnabled;
  @override
  @JsonKey(name: 'sms_enabled')
  final bool smsEnabled;

  @override
  String toString() {
    return 'TfaStatus(twoFactorEnabled: $twoFactorEnabled, twoFactorMethod: $twoFactorMethod, maskedEmail: $maskedEmail, maskedMobile: $maskedMobile, emailEnabled: $emailEnabled, smsEnabled: $smsEnabled)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$TfaStatusImpl &&
            (identical(other.twoFactorEnabled, twoFactorEnabled) ||
                other.twoFactorEnabled == twoFactorEnabled) &&
            (identical(other.twoFactorMethod, twoFactorMethod) ||
                other.twoFactorMethod == twoFactorMethod) &&
            (identical(other.maskedEmail, maskedEmail) ||
                other.maskedEmail == maskedEmail) &&
            (identical(other.maskedMobile, maskedMobile) ||
                other.maskedMobile == maskedMobile) &&
            (identical(other.emailEnabled, emailEnabled) ||
                other.emailEnabled == emailEnabled) &&
            (identical(other.smsEnabled, smsEnabled) ||
                other.smsEnabled == smsEnabled));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
    runtimeType,
    twoFactorEnabled,
    twoFactorMethod,
    maskedEmail,
    maskedMobile,
    emailEnabled,
    smsEnabled,
  );

  /// Create a copy of TfaStatus
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$TfaStatusImplCopyWith<_$TfaStatusImpl> get copyWith =>
      __$$TfaStatusImplCopyWithImpl<_$TfaStatusImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$TfaStatusImplToJson(this);
  }
}

abstract class _TfaStatus implements TfaStatus {
  const factory _TfaStatus({
    @JsonKey(name: 'two_factor_enabled') final bool twoFactorEnabled,
    @JsonKey(name: 'two_factor_method') final String? twoFactorMethod,
    @JsonKey(name: 'masked_email') final String? maskedEmail,
    @JsonKey(name: 'masked_mobile') final String? maskedMobile,
    @JsonKey(name: 'email_enabled') final bool emailEnabled,
    @JsonKey(name: 'sms_enabled') final bool smsEnabled,
  }) = _$TfaStatusImpl;

  factory _TfaStatus.fromJson(Map<String, dynamic> json) =
      _$TfaStatusImpl.fromJson;

  @override
  @JsonKey(name: 'two_factor_enabled')
  bool get twoFactorEnabled;
  @override
  @JsonKey(name: 'two_factor_method')
  String? get twoFactorMethod;
  @override
  @JsonKey(name: 'masked_email')
  String? get maskedEmail;
  @override
  @JsonKey(name: 'masked_mobile')
  String? get maskedMobile;
  @override
  @JsonKey(name: 'email_enabled')
  bool get emailEnabled;
  @override
  @JsonKey(name: 'sms_enabled')
  bool get smsEnabled;

  /// Create a copy of TfaStatus
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$TfaStatusImplCopyWith<_$TfaStatusImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

TfaSetupAuthenticatorData _$TfaSetupAuthenticatorDataFromJson(
  Map<String, dynamic> json,
) {
  return _TfaSetupAuthenticatorData.fromJson(json);
}

/// @nodoc
mixin _$TfaSetupAuthenticatorData {
  String get secret => throw _privateConstructorUsedError;
  @JsonKey(name: 'qr_code')
  String get qrCode => throw _privateConstructorUsedError;

  /// Serializes this TfaSetupAuthenticatorData to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of TfaSetupAuthenticatorData
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $TfaSetupAuthenticatorDataCopyWith<TfaSetupAuthenticatorData> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $TfaSetupAuthenticatorDataCopyWith<$Res> {
  factory $TfaSetupAuthenticatorDataCopyWith(
    TfaSetupAuthenticatorData value,
    $Res Function(TfaSetupAuthenticatorData) then,
  ) = _$TfaSetupAuthenticatorDataCopyWithImpl<$Res, TfaSetupAuthenticatorData>;
  @useResult
  $Res call({String secret, @JsonKey(name: 'qr_code') String qrCode});
}

/// @nodoc
class _$TfaSetupAuthenticatorDataCopyWithImpl<
  $Res,
  $Val extends TfaSetupAuthenticatorData
>
    implements $TfaSetupAuthenticatorDataCopyWith<$Res> {
  _$TfaSetupAuthenticatorDataCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of TfaSetupAuthenticatorData
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? secret = null, Object? qrCode = null}) {
    return _then(
      _value.copyWith(
            secret: null == secret
                ? _value.secret
                : secret // ignore: cast_nullable_to_non_nullable
                      as String,
            qrCode: null == qrCode
                ? _value.qrCode
                : qrCode // ignore: cast_nullable_to_non_nullable
                      as String,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$TfaSetupAuthenticatorDataImplCopyWith<$Res>
    implements $TfaSetupAuthenticatorDataCopyWith<$Res> {
  factory _$$TfaSetupAuthenticatorDataImplCopyWith(
    _$TfaSetupAuthenticatorDataImpl value,
    $Res Function(_$TfaSetupAuthenticatorDataImpl) then,
  ) = __$$TfaSetupAuthenticatorDataImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({String secret, @JsonKey(name: 'qr_code') String qrCode});
}

/// @nodoc
class __$$TfaSetupAuthenticatorDataImplCopyWithImpl<$Res>
    extends
        _$TfaSetupAuthenticatorDataCopyWithImpl<
          $Res,
          _$TfaSetupAuthenticatorDataImpl
        >
    implements _$$TfaSetupAuthenticatorDataImplCopyWith<$Res> {
  __$$TfaSetupAuthenticatorDataImplCopyWithImpl(
    _$TfaSetupAuthenticatorDataImpl _value,
    $Res Function(_$TfaSetupAuthenticatorDataImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of TfaSetupAuthenticatorData
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? secret = null, Object? qrCode = null}) {
    return _then(
      _$TfaSetupAuthenticatorDataImpl(
        secret: null == secret
            ? _value.secret
            : secret // ignore: cast_nullable_to_non_nullable
                  as String,
        qrCode: null == qrCode
            ? _value.qrCode
            : qrCode // ignore: cast_nullable_to_non_nullable
                  as String,
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$TfaSetupAuthenticatorDataImpl implements _TfaSetupAuthenticatorData {
  const _$TfaSetupAuthenticatorDataImpl({
    required this.secret,
    @JsonKey(name: 'qr_code') required this.qrCode,
  });

  factory _$TfaSetupAuthenticatorDataImpl.fromJson(Map<String, dynamic> json) =>
      _$$TfaSetupAuthenticatorDataImplFromJson(json);

  @override
  final String secret;
  @override
  @JsonKey(name: 'qr_code')
  final String qrCode;

  @override
  String toString() {
    return 'TfaSetupAuthenticatorData(secret: $secret, qrCode: $qrCode)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$TfaSetupAuthenticatorDataImpl &&
            (identical(other.secret, secret) || other.secret == secret) &&
            (identical(other.qrCode, qrCode) || other.qrCode == qrCode));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, secret, qrCode);

  /// Create a copy of TfaSetupAuthenticatorData
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$TfaSetupAuthenticatorDataImplCopyWith<_$TfaSetupAuthenticatorDataImpl>
  get copyWith =>
      __$$TfaSetupAuthenticatorDataImplCopyWithImpl<
        _$TfaSetupAuthenticatorDataImpl
      >(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$TfaSetupAuthenticatorDataImplToJson(this);
  }
}

abstract class _TfaSetupAuthenticatorData implements TfaSetupAuthenticatorData {
  const factory _TfaSetupAuthenticatorData({
    required final String secret,
    @JsonKey(name: 'qr_code') required final String qrCode,
  }) = _$TfaSetupAuthenticatorDataImpl;

  factory _TfaSetupAuthenticatorData.fromJson(Map<String, dynamic> json) =
      _$TfaSetupAuthenticatorDataImpl.fromJson;

  @override
  String get secret;
  @override
  @JsonKey(name: 'qr_code')
  String get qrCode;

  /// Create a copy of TfaSetupAuthenticatorData
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$TfaSetupAuthenticatorDataImplCopyWith<_$TfaSetupAuthenticatorDataImpl>
  get copyWith => throw _privateConstructorUsedError;
}
