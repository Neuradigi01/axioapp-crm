// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'app_config_schema.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
  'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models',
);

AppConfigData _$AppConfigDataFromJson(Map<String, dynamic> json) {
  return _AppConfigData.fromJson(json);
}

/// @nodoc
mixin _$AppConfigData {
  @JsonKey(name: 'captcha_enabled')
  bool get captchaEnabled => throw _privateConstructorUsedError;
  @JsonKey(name: 'email_enabled')
  bool get emailEnabled => throw _privateConstructorUsedError;
  @JsonKey(name: 'sms_enabled')
  bool get smsEnabled => throw _privateConstructorUsedError;
  @JsonKey(name: 'contact_verification_mode')
  String get contactVerificationMode => throw _privateConstructorUsedError;
  @JsonKey(name: 'push_notification_enabled')
  bool get pushNotificationEnabled => throw _privateConstructorUsedError;
  @JsonKey(name: 'firebase_config')
  Map<String, dynamic>? get firebaseConfig =>
      throw _privateConstructorUsedError;

  /// Serializes this AppConfigData to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of AppConfigData
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $AppConfigDataCopyWith<AppConfigData> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $AppConfigDataCopyWith<$Res> {
  factory $AppConfigDataCopyWith(
    AppConfigData value,
    $Res Function(AppConfigData) then,
  ) = _$AppConfigDataCopyWithImpl<$Res, AppConfigData>;
  @useResult
  $Res call({
    @JsonKey(name: 'captcha_enabled') bool captchaEnabled,
    @JsonKey(name: 'email_enabled') bool emailEnabled,
    @JsonKey(name: 'sms_enabled') bool smsEnabled,
    @JsonKey(name: 'contact_verification_mode') String contactVerificationMode,
    @JsonKey(name: 'push_notification_enabled') bool pushNotificationEnabled,
    @JsonKey(name: 'firebase_config') Map<String, dynamic>? firebaseConfig,
  });
}

/// @nodoc
class _$AppConfigDataCopyWithImpl<$Res, $Val extends AppConfigData>
    implements $AppConfigDataCopyWith<$Res> {
  _$AppConfigDataCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of AppConfigData
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? captchaEnabled = null,
    Object? emailEnabled = null,
    Object? smsEnabled = null,
    Object? contactVerificationMode = null,
    Object? pushNotificationEnabled = null,
    Object? firebaseConfig = freezed,
  }) {
    return _then(
      _value.copyWith(
            captchaEnabled: null == captchaEnabled
                ? _value.captchaEnabled
                : captchaEnabled // ignore: cast_nullable_to_non_nullable
                      as bool,
            emailEnabled: null == emailEnabled
                ? _value.emailEnabled
                : emailEnabled // ignore: cast_nullable_to_non_nullable
                      as bool,
            smsEnabled: null == smsEnabled
                ? _value.smsEnabled
                : smsEnabled // ignore: cast_nullable_to_non_nullable
                      as bool,
            contactVerificationMode: null == contactVerificationMode
                ? _value.contactVerificationMode
                : contactVerificationMode // ignore: cast_nullable_to_non_nullable
                      as String,
            pushNotificationEnabled: null == pushNotificationEnabled
                ? _value.pushNotificationEnabled
                : pushNotificationEnabled // ignore: cast_nullable_to_non_nullable
                      as bool,
            firebaseConfig: freezed == firebaseConfig
                ? _value.firebaseConfig
                : firebaseConfig // ignore: cast_nullable_to_non_nullable
                      as Map<String, dynamic>?,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$AppConfigDataImplCopyWith<$Res>
    implements $AppConfigDataCopyWith<$Res> {
  factory _$$AppConfigDataImplCopyWith(
    _$AppConfigDataImpl value,
    $Res Function(_$AppConfigDataImpl) then,
  ) = __$$AppConfigDataImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({
    @JsonKey(name: 'captcha_enabled') bool captchaEnabled,
    @JsonKey(name: 'email_enabled') bool emailEnabled,
    @JsonKey(name: 'sms_enabled') bool smsEnabled,
    @JsonKey(name: 'contact_verification_mode') String contactVerificationMode,
    @JsonKey(name: 'push_notification_enabled') bool pushNotificationEnabled,
    @JsonKey(name: 'firebase_config') Map<String, dynamic>? firebaseConfig,
  });
}

/// @nodoc
class __$$AppConfigDataImplCopyWithImpl<$Res>
    extends _$AppConfigDataCopyWithImpl<$Res, _$AppConfigDataImpl>
    implements _$$AppConfigDataImplCopyWith<$Res> {
  __$$AppConfigDataImplCopyWithImpl(
    _$AppConfigDataImpl _value,
    $Res Function(_$AppConfigDataImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of AppConfigData
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? captchaEnabled = null,
    Object? emailEnabled = null,
    Object? smsEnabled = null,
    Object? contactVerificationMode = null,
    Object? pushNotificationEnabled = null,
    Object? firebaseConfig = freezed,
  }) {
    return _then(
      _$AppConfigDataImpl(
        captchaEnabled: null == captchaEnabled
            ? _value.captchaEnabled
            : captchaEnabled // ignore: cast_nullable_to_non_nullable
                  as bool,
        emailEnabled: null == emailEnabled
            ? _value.emailEnabled
            : emailEnabled // ignore: cast_nullable_to_non_nullable
                  as bool,
        smsEnabled: null == smsEnabled
            ? _value.smsEnabled
            : smsEnabled // ignore: cast_nullable_to_non_nullable
                  as bool,
        contactVerificationMode: null == contactVerificationMode
            ? _value.contactVerificationMode
            : contactVerificationMode // ignore: cast_nullable_to_non_nullable
                  as String,
        pushNotificationEnabled: null == pushNotificationEnabled
            ? _value.pushNotificationEnabled
            : pushNotificationEnabled // ignore: cast_nullable_to_non_nullable
                  as bool,
        firebaseConfig: freezed == firebaseConfig
            ? _value._firebaseConfig
            : firebaseConfig // ignore: cast_nullable_to_non_nullable
                  as Map<String, dynamic>?,
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$AppConfigDataImpl implements _AppConfigData {
  const _$AppConfigDataImpl({
    @JsonKey(name: 'captcha_enabled') this.captchaEnabled = false,
    @JsonKey(name: 'email_enabled') this.emailEnabled = false,
    @JsonKey(name: 'sms_enabled') this.smsEnabled = false,
    @JsonKey(name: 'contact_verification_mode')
    this.contactVerificationMode = 'none',
    @JsonKey(name: 'push_notification_enabled')
    this.pushNotificationEnabled = false,
    @JsonKey(name: 'firebase_config')
    final Map<String, dynamic>? firebaseConfig,
  }) : _firebaseConfig = firebaseConfig;

  factory _$AppConfigDataImpl.fromJson(Map<String, dynamic> json) =>
      _$$AppConfigDataImplFromJson(json);

  @override
  @JsonKey(name: 'captcha_enabled')
  final bool captchaEnabled;
  @override
  @JsonKey(name: 'email_enabled')
  final bool emailEnabled;
  @override
  @JsonKey(name: 'sms_enabled')
  final bool smsEnabled;
  @override
  @JsonKey(name: 'contact_verification_mode')
  final String contactVerificationMode;
  @override
  @JsonKey(name: 'push_notification_enabled')
  final bool pushNotificationEnabled;
  final Map<String, dynamic>? _firebaseConfig;
  @override
  @JsonKey(name: 'firebase_config')
  Map<String, dynamic>? get firebaseConfig {
    final value = _firebaseConfig;
    if (value == null) return null;
    if (_firebaseConfig is EqualUnmodifiableMapView) return _firebaseConfig;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableMapView(value);
  }

  @override
  String toString() {
    return 'AppConfigData(captchaEnabled: $captchaEnabled, emailEnabled: $emailEnabled, smsEnabled: $smsEnabled, contactVerificationMode: $contactVerificationMode, pushNotificationEnabled: $pushNotificationEnabled, firebaseConfig: $firebaseConfig)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$AppConfigDataImpl &&
            (identical(other.captchaEnabled, captchaEnabled) ||
                other.captchaEnabled == captchaEnabled) &&
            (identical(other.emailEnabled, emailEnabled) ||
                other.emailEnabled == emailEnabled) &&
            (identical(other.smsEnabled, smsEnabled) ||
                other.smsEnabled == smsEnabled) &&
            (identical(
                  other.contactVerificationMode,
                  contactVerificationMode,
                ) ||
                other.contactVerificationMode == contactVerificationMode) &&
            (identical(
                  other.pushNotificationEnabled,
                  pushNotificationEnabled,
                ) ||
                other.pushNotificationEnabled == pushNotificationEnabled) &&
            const DeepCollectionEquality().equals(
              other._firebaseConfig,
              _firebaseConfig,
            ));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
    runtimeType,
    captchaEnabled,
    emailEnabled,
    smsEnabled,
    contactVerificationMode,
    pushNotificationEnabled,
    const DeepCollectionEquality().hash(_firebaseConfig),
  );

  /// Create a copy of AppConfigData
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$AppConfigDataImplCopyWith<_$AppConfigDataImpl> get copyWith =>
      __$$AppConfigDataImplCopyWithImpl<_$AppConfigDataImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$AppConfigDataImplToJson(this);
  }
}

abstract class _AppConfigData implements AppConfigData {
  const factory _AppConfigData({
    @JsonKey(name: 'captcha_enabled') final bool captchaEnabled,
    @JsonKey(name: 'email_enabled') final bool emailEnabled,
    @JsonKey(name: 'sms_enabled') final bool smsEnabled,
    @JsonKey(name: 'contact_verification_mode')
    final String contactVerificationMode,
    @JsonKey(name: 'push_notification_enabled')
    final bool pushNotificationEnabled,
    @JsonKey(name: 'firebase_config')
    final Map<String, dynamic>? firebaseConfig,
  }) = _$AppConfigDataImpl;

  factory _AppConfigData.fromJson(Map<String, dynamic> json) =
      _$AppConfigDataImpl.fromJson;

  @override
  @JsonKey(name: 'captcha_enabled')
  bool get captchaEnabled;
  @override
  @JsonKey(name: 'email_enabled')
  bool get emailEnabled;
  @override
  @JsonKey(name: 'sms_enabled')
  bool get smsEnabled;
  @override
  @JsonKey(name: 'contact_verification_mode')
  String get contactVerificationMode;
  @override
  @JsonKey(name: 'push_notification_enabled')
  bool get pushNotificationEnabled;
  @override
  @JsonKey(name: 'firebase_config')
  Map<String, dynamic>? get firebaseConfig;

  /// Create a copy of AppConfigData
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$AppConfigDataImplCopyWith<_$AppConfigDataImpl> get copyWith =>
      throw _privateConstructorUsedError;
}
