// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'auth_schema.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
  'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models',
);

LoginRequest _$LoginRequestFromJson(Map<String, dynamic> json) {
  return _LoginRequest.fromJson(json);
}

/// @nodoc
mixin _$LoginRequest {
  String get identifier => throw _privateConstructorUsedError;
  String get password => throw _privateConstructorUsedError;
  @JsonKey(name: 'two_factor_code')
  String? get twoFactorCode => throw _privateConstructorUsedError;
  @JsonKey(name: 'two_factor_method')
  String? get twoFactorMethod => throw _privateConstructorUsedError;
  @JsonKey(name: 'device_info')
  Map<String, String>? get deviceInfo => throw _privateConstructorUsedError;
  @JsonKey(name: 'captcha_token')
  String? get captchaToken => throw _privateConstructorUsedError;
  @JsonKey(name: 'captcha_answer')
  String? get captchaAnswer => throw _privateConstructorUsedError;

  /// Serializes this LoginRequest to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of LoginRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $LoginRequestCopyWith<LoginRequest> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $LoginRequestCopyWith<$Res> {
  factory $LoginRequestCopyWith(
    LoginRequest value,
    $Res Function(LoginRequest) then,
  ) = _$LoginRequestCopyWithImpl<$Res, LoginRequest>;
  @useResult
  $Res call({
    String identifier,
    String password,
    @JsonKey(name: 'two_factor_code') String? twoFactorCode,
    @JsonKey(name: 'two_factor_method') String? twoFactorMethod,
    @JsonKey(name: 'device_info') Map<String, String>? deviceInfo,
    @JsonKey(name: 'captcha_token') String? captchaToken,
    @JsonKey(name: 'captcha_answer') String? captchaAnswer,
  });
}

/// @nodoc
class _$LoginRequestCopyWithImpl<$Res, $Val extends LoginRequest>
    implements $LoginRequestCopyWith<$Res> {
  _$LoginRequestCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of LoginRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? identifier = null,
    Object? password = null,
    Object? twoFactorCode = freezed,
    Object? twoFactorMethod = freezed,
    Object? deviceInfo = freezed,
    Object? captchaToken = freezed,
    Object? captchaAnswer = freezed,
  }) {
    return _then(
      _value.copyWith(
            identifier: null == identifier
                ? _value.identifier
                : identifier // ignore: cast_nullable_to_non_nullable
                      as String,
            password: null == password
                ? _value.password
                : password // ignore: cast_nullable_to_non_nullable
                      as String,
            twoFactorCode: freezed == twoFactorCode
                ? _value.twoFactorCode
                : twoFactorCode // ignore: cast_nullable_to_non_nullable
                      as String?,
            twoFactorMethod: freezed == twoFactorMethod
                ? _value.twoFactorMethod
                : twoFactorMethod // ignore: cast_nullable_to_non_nullable
                      as String?,
            deviceInfo: freezed == deviceInfo
                ? _value.deviceInfo
                : deviceInfo // ignore: cast_nullable_to_non_nullable
                      as Map<String, String>?,
            captchaToken: freezed == captchaToken
                ? _value.captchaToken
                : captchaToken // ignore: cast_nullable_to_non_nullable
                      as String?,
            captchaAnswer: freezed == captchaAnswer
                ? _value.captchaAnswer
                : captchaAnswer // ignore: cast_nullable_to_non_nullable
                      as String?,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$LoginRequestImplCopyWith<$Res>
    implements $LoginRequestCopyWith<$Res> {
  factory _$$LoginRequestImplCopyWith(
    _$LoginRequestImpl value,
    $Res Function(_$LoginRequestImpl) then,
  ) = __$$LoginRequestImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({
    String identifier,
    String password,
    @JsonKey(name: 'two_factor_code') String? twoFactorCode,
    @JsonKey(name: 'two_factor_method') String? twoFactorMethod,
    @JsonKey(name: 'device_info') Map<String, String>? deviceInfo,
    @JsonKey(name: 'captcha_token') String? captchaToken,
    @JsonKey(name: 'captcha_answer') String? captchaAnswer,
  });
}

/// @nodoc
class __$$LoginRequestImplCopyWithImpl<$Res>
    extends _$LoginRequestCopyWithImpl<$Res, _$LoginRequestImpl>
    implements _$$LoginRequestImplCopyWith<$Res> {
  __$$LoginRequestImplCopyWithImpl(
    _$LoginRequestImpl _value,
    $Res Function(_$LoginRequestImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of LoginRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? identifier = null,
    Object? password = null,
    Object? twoFactorCode = freezed,
    Object? twoFactorMethod = freezed,
    Object? deviceInfo = freezed,
    Object? captchaToken = freezed,
    Object? captchaAnswer = freezed,
  }) {
    return _then(
      _$LoginRequestImpl(
        identifier: null == identifier
            ? _value.identifier
            : identifier // ignore: cast_nullable_to_non_nullable
                  as String,
        password: null == password
            ? _value.password
            : password // ignore: cast_nullable_to_non_nullable
                  as String,
        twoFactorCode: freezed == twoFactorCode
            ? _value.twoFactorCode
            : twoFactorCode // ignore: cast_nullable_to_non_nullable
                  as String?,
        twoFactorMethod: freezed == twoFactorMethod
            ? _value.twoFactorMethod
            : twoFactorMethod // ignore: cast_nullable_to_non_nullable
                  as String?,
        deviceInfo: freezed == deviceInfo
            ? _value._deviceInfo
            : deviceInfo // ignore: cast_nullable_to_non_nullable
                  as Map<String, String>?,
        captchaToken: freezed == captchaToken
            ? _value.captchaToken
            : captchaToken // ignore: cast_nullable_to_non_nullable
                  as String?,
        captchaAnswer: freezed == captchaAnswer
            ? _value.captchaAnswer
            : captchaAnswer // ignore: cast_nullable_to_non_nullable
                  as String?,
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$LoginRequestImpl implements _LoginRequest {
  const _$LoginRequestImpl({
    required this.identifier,
    required this.password,
    @JsonKey(name: 'two_factor_code') this.twoFactorCode,
    @JsonKey(name: 'two_factor_method') this.twoFactorMethod,
    @JsonKey(name: 'device_info') final Map<String, String>? deviceInfo,
    @JsonKey(name: 'captcha_token') this.captchaToken,
    @JsonKey(name: 'captcha_answer') this.captchaAnswer,
  }) : _deviceInfo = deviceInfo;

  factory _$LoginRequestImpl.fromJson(Map<String, dynamic> json) =>
      _$$LoginRequestImplFromJson(json);

  @override
  final String identifier;
  @override
  final String password;
  @override
  @JsonKey(name: 'two_factor_code')
  final String? twoFactorCode;
  @override
  @JsonKey(name: 'two_factor_method')
  final String? twoFactorMethod;
  final Map<String, String>? _deviceInfo;
  @override
  @JsonKey(name: 'device_info')
  Map<String, String>? get deviceInfo {
    final value = _deviceInfo;
    if (value == null) return null;
    if (_deviceInfo is EqualUnmodifiableMapView) return _deviceInfo;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableMapView(value);
  }

  @override
  @JsonKey(name: 'captcha_token')
  final String? captchaToken;
  @override
  @JsonKey(name: 'captcha_answer')
  final String? captchaAnswer;

  @override
  String toString() {
    return 'LoginRequest(identifier: $identifier, password: $password, twoFactorCode: $twoFactorCode, twoFactorMethod: $twoFactorMethod, deviceInfo: $deviceInfo, captchaToken: $captchaToken, captchaAnswer: $captchaAnswer)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$LoginRequestImpl &&
            (identical(other.identifier, identifier) ||
                other.identifier == identifier) &&
            (identical(other.password, password) ||
                other.password == password) &&
            (identical(other.twoFactorCode, twoFactorCode) ||
                other.twoFactorCode == twoFactorCode) &&
            (identical(other.twoFactorMethod, twoFactorMethod) ||
                other.twoFactorMethod == twoFactorMethod) &&
            const DeepCollectionEquality().equals(
              other._deviceInfo,
              _deviceInfo,
            ) &&
            (identical(other.captchaToken, captchaToken) ||
                other.captchaToken == captchaToken) &&
            (identical(other.captchaAnswer, captchaAnswer) ||
                other.captchaAnswer == captchaAnswer));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
    runtimeType,
    identifier,
    password,
    twoFactorCode,
    twoFactorMethod,
    const DeepCollectionEquality().hash(_deviceInfo),
    captchaToken,
    captchaAnswer,
  );

  /// Create a copy of LoginRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$LoginRequestImplCopyWith<_$LoginRequestImpl> get copyWith =>
      __$$LoginRequestImplCopyWithImpl<_$LoginRequestImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$LoginRequestImplToJson(this);
  }
}

abstract class _LoginRequest implements LoginRequest {
  const factory _LoginRequest({
    required final String identifier,
    required final String password,
    @JsonKey(name: 'two_factor_code') final String? twoFactorCode,
    @JsonKey(name: 'two_factor_method') final String? twoFactorMethod,
    @JsonKey(name: 'device_info') final Map<String, String>? deviceInfo,
    @JsonKey(name: 'captcha_token') final String? captchaToken,
    @JsonKey(name: 'captcha_answer') final String? captchaAnswer,
  }) = _$LoginRequestImpl;

  factory _LoginRequest.fromJson(Map<String, dynamic> json) =
      _$LoginRequestImpl.fromJson;

  @override
  String get identifier;
  @override
  String get password;
  @override
  @JsonKey(name: 'two_factor_code')
  String? get twoFactorCode;
  @override
  @JsonKey(name: 'two_factor_method')
  String? get twoFactorMethod;
  @override
  @JsonKey(name: 'device_info')
  Map<String, String>? get deviceInfo;
  @override
  @JsonKey(name: 'captcha_token')
  String? get captchaToken;
  @override
  @JsonKey(name: 'captcha_answer')
  String? get captchaAnswer;

  /// Create a copy of LoginRequest
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$LoginRequestImplCopyWith<_$LoginRequestImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

LoginData _$LoginDataFromJson(Map<String, dynamic> json) {
  return _LoginData.fromJson(json);
}

/// @nodoc
mixin _$LoginData {
  String get token => throw _privateConstructorUsedError;
  @JsonKey(name: 'user_id')
  String get userId => throw _privateConstructorUsedError;
  String get role => throw _privateConstructorUsedError;
  @JsonKey(name: 'first_name')
  String? get firstName => throw _privateConstructorUsedError;
  @JsonKey(name: 'last_name')
  String? get lastName => throw _privateConstructorUsedError;
  String? get name => throw _privateConstructorUsedError;
  String get email => throw _privateConstructorUsedError;
  @JsonKey(name: 'is_super_admin')
  bool get isSuperAdmin => throw _privateConstructorUsedError;

  /// Serializes this LoginData to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of LoginData
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $LoginDataCopyWith<LoginData> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $LoginDataCopyWith<$Res> {
  factory $LoginDataCopyWith(LoginData value, $Res Function(LoginData) then) =
      _$LoginDataCopyWithImpl<$Res, LoginData>;
  @useResult
  $Res call({
    String token,
    @JsonKey(name: 'user_id') String userId,
    String role,
    @JsonKey(name: 'first_name') String? firstName,
    @JsonKey(name: 'last_name') String? lastName,
    String? name,
    String email,
    @JsonKey(name: 'is_super_admin') bool isSuperAdmin,
  });
}

/// @nodoc
class _$LoginDataCopyWithImpl<$Res, $Val extends LoginData>
    implements $LoginDataCopyWith<$Res> {
  _$LoginDataCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of LoginData
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? token = null,
    Object? userId = null,
    Object? role = null,
    Object? firstName = freezed,
    Object? lastName = freezed,
    Object? name = freezed,
    Object? email = null,
    Object? isSuperAdmin = null,
  }) {
    return _then(
      _value.copyWith(
            token: null == token
                ? _value.token
                : token // ignore: cast_nullable_to_non_nullable
                      as String,
            userId: null == userId
                ? _value.userId
                : userId // ignore: cast_nullable_to_non_nullable
                      as String,
            role: null == role
                ? _value.role
                : role // ignore: cast_nullable_to_non_nullable
                      as String,
            firstName: freezed == firstName
                ? _value.firstName
                : firstName // ignore: cast_nullable_to_non_nullable
                      as String?,
            lastName: freezed == lastName
                ? _value.lastName
                : lastName // ignore: cast_nullable_to_non_nullable
                      as String?,
            name: freezed == name
                ? _value.name
                : name // ignore: cast_nullable_to_non_nullable
                      as String?,
            email: null == email
                ? _value.email
                : email // ignore: cast_nullable_to_non_nullable
                      as String,
            isSuperAdmin: null == isSuperAdmin
                ? _value.isSuperAdmin
                : isSuperAdmin // ignore: cast_nullable_to_non_nullable
                      as bool,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$LoginDataImplCopyWith<$Res>
    implements $LoginDataCopyWith<$Res> {
  factory _$$LoginDataImplCopyWith(
    _$LoginDataImpl value,
    $Res Function(_$LoginDataImpl) then,
  ) = __$$LoginDataImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({
    String token,
    @JsonKey(name: 'user_id') String userId,
    String role,
    @JsonKey(name: 'first_name') String? firstName,
    @JsonKey(name: 'last_name') String? lastName,
    String? name,
    String email,
    @JsonKey(name: 'is_super_admin') bool isSuperAdmin,
  });
}

/// @nodoc
class __$$LoginDataImplCopyWithImpl<$Res>
    extends _$LoginDataCopyWithImpl<$Res, _$LoginDataImpl>
    implements _$$LoginDataImplCopyWith<$Res> {
  __$$LoginDataImplCopyWithImpl(
    _$LoginDataImpl _value,
    $Res Function(_$LoginDataImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of LoginData
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? token = null,
    Object? userId = null,
    Object? role = null,
    Object? firstName = freezed,
    Object? lastName = freezed,
    Object? name = freezed,
    Object? email = null,
    Object? isSuperAdmin = null,
  }) {
    return _then(
      _$LoginDataImpl(
        token: null == token
            ? _value.token
            : token // ignore: cast_nullable_to_non_nullable
                  as String,
        userId: null == userId
            ? _value.userId
            : userId // ignore: cast_nullable_to_non_nullable
                  as String,
        role: null == role
            ? _value.role
            : role // ignore: cast_nullable_to_non_nullable
                  as String,
        firstName: freezed == firstName
            ? _value.firstName
            : firstName // ignore: cast_nullable_to_non_nullable
                  as String?,
        lastName: freezed == lastName
            ? _value.lastName
            : lastName // ignore: cast_nullable_to_non_nullable
                  as String?,
        name: freezed == name
            ? _value.name
            : name // ignore: cast_nullable_to_non_nullable
                  as String?,
        email: null == email
            ? _value.email
            : email // ignore: cast_nullable_to_non_nullable
                  as String,
        isSuperAdmin: null == isSuperAdmin
            ? _value.isSuperAdmin
            : isSuperAdmin // ignore: cast_nullable_to_non_nullable
                  as bool,
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$LoginDataImpl implements _LoginData {
  const _$LoginDataImpl({
    required this.token,
    @JsonKey(name: 'user_id') required this.userId,
    required this.role,
    @JsonKey(name: 'first_name') this.firstName,
    @JsonKey(name: 'last_name') this.lastName,
    this.name,
    required this.email,
    @JsonKey(name: 'is_super_admin') this.isSuperAdmin = false,
  });

  factory _$LoginDataImpl.fromJson(Map<String, dynamic> json) =>
      _$$LoginDataImplFromJson(json);

  @override
  final String token;
  @override
  @JsonKey(name: 'user_id')
  final String userId;
  @override
  final String role;
  @override
  @JsonKey(name: 'first_name')
  final String? firstName;
  @override
  @JsonKey(name: 'last_name')
  final String? lastName;
  @override
  final String? name;
  @override
  final String email;
  @override
  @JsonKey(name: 'is_super_admin')
  final bool isSuperAdmin;

  @override
  String toString() {
    return 'LoginData(token: $token, userId: $userId, role: $role, firstName: $firstName, lastName: $lastName, name: $name, email: $email, isSuperAdmin: $isSuperAdmin)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$LoginDataImpl &&
            (identical(other.token, token) || other.token == token) &&
            (identical(other.userId, userId) || other.userId == userId) &&
            (identical(other.role, role) || other.role == role) &&
            (identical(other.firstName, firstName) ||
                other.firstName == firstName) &&
            (identical(other.lastName, lastName) ||
                other.lastName == lastName) &&
            (identical(other.name, name) || other.name == name) &&
            (identical(other.email, email) || other.email == email) &&
            (identical(other.isSuperAdmin, isSuperAdmin) ||
                other.isSuperAdmin == isSuperAdmin));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
    runtimeType,
    token,
    userId,
    role,
    firstName,
    lastName,
    name,
    email,
    isSuperAdmin,
  );

  /// Create a copy of LoginData
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$LoginDataImplCopyWith<_$LoginDataImpl> get copyWith =>
      __$$LoginDataImplCopyWithImpl<_$LoginDataImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$LoginDataImplToJson(this);
  }
}

abstract class _LoginData implements LoginData {
  const factory _LoginData({
    required final String token,
    @JsonKey(name: 'user_id') required final String userId,
    required final String role,
    @JsonKey(name: 'first_name') final String? firstName,
    @JsonKey(name: 'last_name') final String? lastName,
    final String? name,
    required final String email,
    @JsonKey(name: 'is_super_admin') final bool isSuperAdmin,
  }) = _$LoginDataImpl;

  factory _LoginData.fromJson(Map<String, dynamic> json) =
      _$LoginDataImpl.fromJson;

  @override
  String get token;
  @override
  @JsonKey(name: 'user_id')
  String get userId;
  @override
  String get role;
  @override
  @JsonKey(name: 'first_name')
  String? get firstName;
  @override
  @JsonKey(name: 'last_name')
  String? get lastName;
  @override
  String? get name;
  @override
  String get email;
  @override
  @JsonKey(name: 'is_super_admin')
  bool get isSuperAdmin;

  /// Create a copy of LoginData
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$LoginDataImplCopyWith<_$LoginDataImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

TfaRequiredData _$TfaRequiredDataFromJson(Map<String, dynamic> json) {
  return _TfaRequiredData.fromJson(json);
}

/// @nodoc
mixin _$TfaRequiredData {
  @JsonKey(name: 'requires_2fa')
  bool get requires2fa => throw _privateConstructorUsedError;
  String get method => throw _privateConstructorUsedError;
  @JsonKey(name: 'available_methods')
  List<String> get availableMethods => throw _privateConstructorUsedError;

  /// Serializes this TfaRequiredData to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of TfaRequiredData
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $TfaRequiredDataCopyWith<TfaRequiredData> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $TfaRequiredDataCopyWith<$Res> {
  factory $TfaRequiredDataCopyWith(
    TfaRequiredData value,
    $Res Function(TfaRequiredData) then,
  ) = _$TfaRequiredDataCopyWithImpl<$Res, TfaRequiredData>;
  @useResult
  $Res call({
    @JsonKey(name: 'requires_2fa') bool requires2fa,
    String method,
    @JsonKey(name: 'available_methods') List<String> availableMethods,
  });
}

/// @nodoc
class _$TfaRequiredDataCopyWithImpl<$Res, $Val extends TfaRequiredData>
    implements $TfaRequiredDataCopyWith<$Res> {
  _$TfaRequiredDataCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of TfaRequiredData
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? requires2fa = null,
    Object? method = null,
    Object? availableMethods = null,
  }) {
    return _then(
      _value.copyWith(
            requires2fa: null == requires2fa
                ? _value.requires2fa
                : requires2fa // ignore: cast_nullable_to_non_nullable
                      as bool,
            method: null == method
                ? _value.method
                : method // ignore: cast_nullable_to_non_nullable
                      as String,
            availableMethods: null == availableMethods
                ? _value.availableMethods
                : availableMethods // ignore: cast_nullable_to_non_nullable
                      as List<String>,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$TfaRequiredDataImplCopyWith<$Res>
    implements $TfaRequiredDataCopyWith<$Res> {
  factory _$$TfaRequiredDataImplCopyWith(
    _$TfaRequiredDataImpl value,
    $Res Function(_$TfaRequiredDataImpl) then,
  ) = __$$TfaRequiredDataImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({
    @JsonKey(name: 'requires_2fa') bool requires2fa,
    String method,
    @JsonKey(name: 'available_methods') List<String> availableMethods,
  });
}

/// @nodoc
class __$$TfaRequiredDataImplCopyWithImpl<$Res>
    extends _$TfaRequiredDataCopyWithImpl<$Res, _$TfaRequiredDataImpl>
    implements _$$TfaRequiredDataImplCopyWith<$Res> {
  __$$TfaRequiredDataImplCopyWithImpl(
    _$TfaRequiredDataImpl _value,
    $Res Function(_$TfaRequiredDataImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of TfaRequiredData
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? requires2fa = null,
    Object? method = null,
    Object? availableMethods = null,
  }) {
    return _then(
      _$TfaRequiredDataImpl(
        requires2fa: null == requires2fa
            ? _value.requires2fa
            : requires2fa // ignore: cast_nullable_to_non_nullable
                  as bool,
        method: null == method
            ? _value.method
            : method // ignore: cast_nullable_to_non_nullable
                  as String,
        availableMethods: null == availableMethods
            ? _value._availableMethods
            : availableMethods // ignore: cast_nullable_to_non_nullable
                  as List<String>,
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$TfaRequiredDataImpl implements _TfaRequiredData {
  const _$TfaRequiredDataImpl({
    @JsonKey(name: 'requires_2fa') this.requires2fa = true,
    required this.method,
    @JsonKey(name: 'available_methods')
    required final List<String> availableMethods,
  }) : _availableMethods = availableMethods;

  factory _$TfaRequiredDataImpl.fromJson(Map<String, dynamic> json) =>
      _$$TfaRequiredDataImplFromJson(json);

  @override
  @JsonKey(name: 'requires_2fa')
  final bool requires2fa;
  @override
  final String method;
  final List<String> _availableMethods;
  @override
  @JsonKey(name: 'available_methods')
  List<String> get availableMethods {
    if (_availableMethods is EqualUnmodifiableListView)
      return _availableMethods;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_availableMethods);
  }

  @override
  String toString() {
    return 'TfaRequiredData(requires2fa: $requires2fa, method: $method, availableMethods: $availableMethods)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$TfaRequiredDataImpl &&
            (identical(other.requires2fa, requires2fa) ||
                other.requires2fa == requires2fa) &&
            (identical(other.method, method) || other.method == method) &&
            const DeepCollectionEquality().equals(
              other._availableMethods,
              _availableMethods,
            ));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
    runtimeType,
    requires2fa,
    method,
    const DeepCollectionEquality().hash(_availableMethods),
  );

  /// Create a copy of TfaRequiredData
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$TfaRequiredDataImplCopyWith<_$TfaRequiredDataImpl> get copyWith =>
      __$$TfaRequiredDataImplCopyWithImpl<_$TfaRequiredDataImpl>(
        this,
        _$identity,
      );

  @override
  Map<String, dynamic> toJson() {
    return _$$TfaRequiredDataImplToJson(this);
  }
}

abstract class _TfaRequiredData implements TfaRequiredData {
  const factory _TfaRequiredData({
    @JsonKey(name: 'requires_2fa') final bool requires2fa,
    required final String method,
    @JsonKey(name: 'available_methods')
    required final List<String> availableMethods,
  }) = _$TfaRequiredDataImpl;

  factory _TfaRequiredData.fromJson(Map<String, dynamic> json) =
      _$TfaRequiredDataImpl.fromJson;

  @override
  @JsonKey(name: 'requires_2fa')
  bool get requires2fa;
  @override
  String get method;
  @override
  @JsonKey(name: 'available_methods')
  List<String> get availableMethods;

  /// Create a copy of TfaRequiredData
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$TfaRequiredDataImplCopyWith<_$TfaRequiredDataImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

EmailVerificationRequiredData _$EmailVerificationRequiredDataFromJson(
  Map<String, dynamic> json,
) {
  return _EmailVerificationRequiredData.fromJson(json);
}

/// @nodoc
mixin _$EmailVerificationRequiredData {
  @JsonKey(name: 'requires_email_verification')
  bool get requiresEmailVerification => throw _privateConstructorUsedError;

  /// Serializes this EmailVerificationRequiredData to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of EmailVerificationRequiredData
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $EmailVerificationRequiredDataCopyWith<EmailVerificationRequiredData>
  get copyWith => throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $EmailVerificationRequiredDataCopyWith<$Res> {
  factory $EmailVerificationRequiredDataCopyWith(
    EmailVerificationRequiredData value,
    $Res Function(EmailVerificationRequiredData) then,
  ) =
      _$EmailVerificationRequiredDataCopyWithImpl<
        $Res,
        EmailVerificationRequiredData
      >;
  @useResult
  $Res call({
    @JsonKey(name: 'requires_email_verification')
    bool requiresEmailVerification,
  });
}

/// @nodoc
class _$EmailVerificationRequiredDataCopyWithImpl<
  $Res,
  $Val extends EmailVerificationRequiredData
>
    implements $EmailVerificationRequiredDataCopyWith<$Res> {
  _$EmailVerificationRequiredDataCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of EmailVerificationRequiredData
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? requiresEmailVerification = null}) {
    return _then(
      _value.copyWith(
            requiresEmailVerification: null == requiresEmailVerification
                ? _value.requiresEmailVerification
                : requiresEmailVerification // ignore: cast_nullable_to_non_nullable
                      as bool,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$EmailVerificationRequiredDataImplCopyWith<$Res>
    implements $EmailVerificationRequiredDataCopyWith<$Res> {
  factory _$$EmailVerificationRequiredDataImplCopyWith(
    _$EmailVerificationRequiredDataImpl value,
    $Res Function(_$EmailVerificationRequiredDataImpl) then,
  ) = __$$EmailVerificationRequiredDataImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({
    @JsonKey(name: 'requires_email_verification')
    bool requiresEmailVerification,
  });
}

/// @nodoc
class __$$EmailVerificationRequiredDataImplCopyWithImpl<$Res>
    extends
        _$EmailVerificationRequiredDataCopyWithImpl<
          $Res,
          _$EmailVerificationRequiredDataImpl
        >
    implements _$$EmailVerificationRequiredDataImplCopyWith<$Res> {
  __$$EmailVerificationRequiredDataImplCopyWithImpl(
    _$EmailVerificationRequiredDataImpl _value,
    $Res Function(_$EmailVerificationRequiredDataImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of EmailVerificationRequiredData
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? requiresEmailVerification = null}) {
    return _then(
      _$EmailVerificationRequiredDataImpl(
        requiresEmailVerification: null == requiresEmailVerification
            ? _value.requiresEmailVerification
            : requiresEmailVerification // ignore: cast_nullable_to_non_nullable
                  as bool,
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$EmailVerificationRequiredDataImpl
    implements _EmailVerificationRequiredData {
  const _$EmailVerificationRequiredDataImpl({
    @JsonKey(name: 'requires_email_verification')
    this.requiresEmailVerification = true,
  });

  factory _$EmailVerificationRequiredDataImpl.fromJson(
    Map<String, dynamic> json,
  ) => _$$EmailVerificationRequiredDataImplFromJson(json);

  @override
  @JsonKey(name: 'requires_email_verification')
  final bool requiresEmailVerification;

  @override
  String toString() {
    return 'EmailVerificationRequiredData(requiresEmailVerification: $requiresEmailVerification)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$EmailVerificationRequiredDataImpl &&
            (identical(
                  other.requiresEmailVerification,
                  requiresEmailVerification,
                ) ||
                other.requiresEmailVerification == requiresEmailVerification));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, requiresEmailVerification);

  /// Create a copy of EmailVerificationRequiredData
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$EmailVerificationRequiredDataImplCopyWith<
    _$EmailVerificationRequiredDataImpl
  >
  get copyWith =>
      __$$EmailVerificationRequiredDataImplCopyWithImpl<
        _$EmailVerificationRequiredDataImpl
      >(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$EmailVerificationRequiredDataImplToJson(this);
  }
}

abstract class _EmailVerificationRequiredData
    implements EmailVerificationRequiredData {
  const factory _EmailVerificationRequiredData({
    @JsonKey(name: 'requires_email_verification')
    final bool requiresEmailVerification,
  }) = _$EmailVerificationRequiredDataImpl;

  factory _EmailVerificationRequiredData.fromJson(Map<String, dynamic> json) =
      _$EmailVerificationRequiredDataImpl.fromJson;

  @override
  @JsonKey(name: 'requires_email_verification')
  bool get requiresEmailVerification;

  /// Create a copy of EmailVerificationRequiredData
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$EmailVerificationRequiredDataImplCopyWith<
    _$EmailVerificationRequiredDataImpl
  >
  get copyWith => throw _privateConstructorUsedError;
}

TryAnotherWayRequest _$TryAnotherWayRequestFromJson(Map<String, dynamic> json) {
  return _TryAnotherWayRequest.fromJson(json);
}

/// @nodoc
mixin _$TryAnotherWayRequest {
  String get identifier => throw _privateConstructorUsedError;
  String get password => throw _privateConstructorUsedError;
  @JsonKey(name: 'user_type')
  String get userType => throw _privateConstructorUsedError;
  String get method => throw _privateConstructorUsedError;

  /// Serializes this TryAnotherWayRequest to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of TryAnotherWayRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $TryAnotherWayRequestCopyWith<TryAnotherWayRequest> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $TryAnotherWayRequestCopyWith<$Res> {
  factory $TryAnotherWayRequestCopyWith(
    TryAnotherWayRequest value,
    $Res Function(TryAnotherWayRequest) then,
  ) = _$TryAnotherWayRequestCopyWithImpl<$Res, TryAnotherWayRequest>;
  @useResult
  $Res call({
    String identifier,
    String password,
    @JsonKey(name: 'user_type') String userType,
    String method,
  });
}

/// @nodoc
class _$TryAnotherWayRequestCopyWithImpl<
  $Res,
  $Val extends TryAnotherWayRequest
>
    implements $TryAnotherWayRequestCopyWith<$Res> {
  _$TryAnotherWayRequestCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of TryAnotherWayRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? identifier = null,
    Object? password = null,
    Object? userType = null,
    Object? method = null,
  }) {
    return _then(
      _value.copyWith(
            identifier: null == identifier
                ? _value.identifier
                : identifier // ignore: cast_nullable_to_non_nullable
                      as String,
            password: null == password
                ? _value.password
                : password // ignore: cast_nullable_to_non_nullable
                      as String,
            userType: null == userType
                ? _value.userType
                : userType // ignore: cast_nullable_to_non_nullable
                      as String,
            method: null == method
                ? _value.method
                : method // ignore: cast_nullable_to_non_nullable
                      as String,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$TryAnotherWayRequestImplCopyWith<$Res>
    implements $TryAnotherWayRequestCopyWith<$Res> {
  factory _$$TryAnotherWayRequestImplCopyWith(
    _$TryAnotherWayRequestImpl value,
    $Res Function(_$TryAnotherWayRequestImpl) then,
  ) = __$$TryAnotherWayRequestImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({
    String identifier,
    String password,
    @JsonKey(name: 'user_type') String userType,
    String method,
  });
}

/// @nodoc
class __$$TryAnotherWayRequestImplCopyWithImpl<$Res>
    extends _$TryAnotherWayRequestCopyWithImpl<$Res, _$TryAnotherWayRequestImpl>
    implements _$$TryAnotherWayRequestImplCopyWith<$Res> {
  __$$TryAnotherWayRequestImplCopyWithImpl(
    _$TryAnotherWayRequestImpl _value,
    $Res Function(_$TryAnotherWayRequestImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of TryAnotherWayRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? identifier = null,
    Object? password = null,
    Object? userType = null,
    Object? method = null,
  }) {
    return _then(
      _$TryAnotherWayRequestImpl(
        identifier: null == identifier
            ? _value.identifier
            : identifier // ignore: cast_nullable_to_non_nullable
                  as String,
        password: null == password
            ? _value.password
            : password // ignore: cast_nullable_to_non_nullable
                  as String,
        userType: null == userType
            ? _value.userType
            : userType // ignore: cast_nullable_to_non_nullable
                  as String,
        method: null == method
            ? _value.method
            : method // ignore: cast_nullable_to_non_nullable
                  as String,
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$TryAnotherWayRequestImpl implements _TryAnotherWayRequest {
  const _$TryAnotherWayRequestImpl({
    required this.identifier,
    required this.password,
    @JsonKey(name: 'user_type') required this.userType,
    required this.method,
  });

  factory _$TryAnotherWayRequestImpl.fromJson(Map<String, dynamic> json) =>
      _$$TryAnotherWayRequestImplFromJson(json);

  @override
  final String identifier;
  @override
  final String password;
  @override
  @JsonKey(name: 'user_type')
  final String userType;
  @override
  final String method;

  @override
  String toString() {
    return 'TryAnotherWayRequest(identifier: $identifier, password: $password, userType: $userType, method: $method)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$TryAnotherWayRequestImpl &&
            (identical(other.identifier, identifier) ||
                other.identifier == identifier) &&
            (identical(other.password, password) ||
                other.password == password) &&
            (identical(other.userType, userType) ||
                other.userType == userType) &&
            (identical(other.method, method) || other.method == method));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode =>
      Object.hash(runtimeType, identifier, password, userType, method);

  /// Create a copy of TryAnotherWayRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$TryAnotherWayRequestImplCopyWith<_$TryAnotherWayRequestImpl>
  get copyWith =>
      __$$TryAnotherWayRequestImplCopyWithImpl<_$TryAnotherWayRequestImpl>(
        this,
        _$identity,
      );

  @override
  Map<String, dynamic> toJson() {
    return _$$TryAnotherWayRequestImplToJson(this);
  }
}

abstract class _TryAnotherWayRequest implements TryAnotherWayRequest {
  const factory _TryAnotherWayRequest({
    required final String identifier,
    required final String password,
    @JsonKey(name: 'user_type') required final String userType,
    required final String method,
  }) = _$TryAnotherWayRequestImpl;

  factory _TryAnotherWayRequest.fromJson(Map<String, dynamic> json) =
      _$TryAnotherWayRequestImpl.fromJson;

  @override
  String get identifier;
  @override
  String get password;
  @override
  @JsonKey(name: 'user_type')
  String get userType;
  @override
  String get method;

  /// Create a copy of TryAnotherWayRequest
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$TryAnotherWayRequestImplCopyWith<_$TryAnotherWayRequestImpl>
  get copyWith => throw _privateConstructorUsedError;
}

TryAnotherWayData _$TryAnotherWayDataFromJson(Map<String, dynamic> json) {
  return _TryAnotherWayData.fromJson(json);
}

/// @nodoc
mixin _$TryAnotherWayData {
  String get method => throw _privateConstructorUsedError;
  @JsonKey(name: 'available_methods')
  List<String> get availableMethods => throw _privateConstructorUsedError;

  /// Serializes this TryAnotherWayData to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of TryAnotherWayData
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $TryAnotherWayDataCopyWith<TryAnotherWayData> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $TryAnotherWayDataCopyWith<$Res> {
  factory $TryAnotherWayDataCopyWith(
    TryAnotherWayData value,
    $Res Function(TryAnotherWayData) then,
  ) = _$TryAnotherWayDataCopyWithImpl<$Res, TryAnotherWayData>;
  @useResult
  $Res call({
    String method,
    @JsonKey(name: 'available_methods') List<String> availableMethods,
  });
}

/// @nodoc
class _$TryAnotherWayDataCopyWithImpl<$Res, $Val extends TryAnotherWayData>
    implements $TryAnotherWayDataCopyWith<$Res> {
  _$TryAnotherWayDataCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of TryAnotherWayData
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? method = null, Object? availableMethods = null}) {
    return _then(
      _value.copyWith(
            method: null == method
                ? _value.method
                : method // ignore: cast_nullable_to_non_nullable
                      as String,
            availableMethods: null == availableMethods
                ? _value.availableMethods
                : availableMethods // ignore: cast_nullable_to_non_nullable
                      as List<String>,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$TryAnotherWayDataImplCopyWith<$Res>
    implements $TryAnotherWayDataCopyWith<$Res> {
  factory _$$TryAnotherWayDataImplCopyWith(
    _$TryAnotherWayDataImpl value,
    $Res Function(_$TryAnotherWayDataImpl) then,
  ) = __$$TryAnotherWayDataImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({
    String method,
    @JsonKey(name: 'available_methods') List<String> availableMethods,
  });
}

/// @nodoc
class __$$TryAnotherWayDataImplCopyWithImpl<$Res>
    extends _$TryAnotherWayDataCopyWithImpl<$Res, _$TryAnotherWayDataImpl>
    implements _$$TryAnotherWayDataImplCopyWith<$Res> {
  __$$TryAnotherWayDataImplCopyWithImpl(
    _$TryAnotherWayDataImpl _value,
    $Res Function(_$TryAnotherWayDataImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of TryAnotherWayData
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? method = null, Object? availableMethods = null}) {
    return _then(
      _$TryAnotherWayDataImpl(
        method: null == method
            ? _value.method
            : method // ignore: cast_nullable_to_non_nullable
                  as String,
        availableMethods: null == availableMethods
            ? _value._availableMethods
            : availableMethods // ignore: cast_nullable_to_non_nullable
                  as List<String>,
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$TryAnotherWayDataImpl implements _TryAnotherWayData {
  const _$TryAnotherWayDataImpl({
    required this.method,
    @JsonKey(name: 'available_methods')
    required final List<String> availableMethods,
  }) : _availableMethods = availableMethods;

  factory _$TryAnotherWayDataImpl.fromJson(Map<String, dynamic> json) =>
      _$$TryAnotherWayDataImplFromJson(json);

  @override
  final String method;
  final List<String> _availableMethods;
  @override
  @JsonKey(name: 'available_methods')
  List<String> get availableMethods {
    if (_availableMethods is EqualUnmodifiableListView)
      return _availableMethods;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_availableMethods);
  }

  @override
  String toString() {
    return 'TryAnotherWayData(method: $method, availableMethods: $availableMethods)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$TryAnotherWayDataImpl &&
            (identical(other.method, method) || other.method == method) &&
            const DeepCollectionEquality().equals(
              other._availableMethods,
              _availableMethods,
            ));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
    runtimeType,
    method,
    const DeepCollectionEquality().hash(_availableMethods),
  );

  /// Create a copy of TryAnotherWayData
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$TryAnotherWayDataImplCopyWith<_$TryAnotherWayDataImpl> get copyWith =>
      __$$TryAnotherWayDataImplCopyWithImpl<_$TryAnotherWayDataImpl>(
        this,
        _$identity,
      );

  @override
  Map<String, dynamic> toJson() {
    return _$$TryAnotherWayDataImplToJson(this);
  }
}

abstract class _TryAnotherWayData implements TryAnotherWayData {
  const factory _TryAnotherWayData({
    required final String method,
    @JsonKey(name: 'available_methods')
    required final List<String> availableMethods,
  }) = _$TryAnotherWayDataImpl;

  factory _TryAnotherWayData.fromJson(Map<String, dynamic> json) =
      _$TryAnotherWayDataImpl.fromJson;

  @override
  String get method;
  @override
  @JsonKey(name: 'available_methods')
  List<String> get availableMethods;

  /// Create a copy of TryAnotherWayData
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$TryAnotherWayDataImplCopyWith<_$TryAnotherWayDataImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

ForgotPasswordRequest _$ForgotPasswordRequestFromJson(
  Map<String, dynamic> json,
) {
  return _ForgotPasswordRequest.fromJson(json);
}

/// @nodoc
mixin _$ForgotPasswordRequest {
  String get identifier => throw _privateConstructorUsedError;

  /// Serializes this ForgotPasswordRequest to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of ForgotPasswordRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $ForgotPasswordRequestCopyWith<ForgotPasswordRequest> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $ForgotPasswordRequestCopyWith<$Res> {
  factory $ForgotPasswordRequestCopyWith(
    ForgotPasswordRequest value,
    $Res Function(ForgotPasswordRequest) then,
  ) = _$ForgotPasswordRequestCopyWithImpl<$Res, ForgotPasswordRequest>;
  @useResult
  $Res call({String identifier});
}

/// @nodoc
class _$ForgotPasswordRequestCopyWithImpl<
  $Res,
  $Val extends ForgotPasswordRequest
>
    implements $ForgotPasswordRequestCopyWith<$Res> {
  _$ForgotPasswordRequestCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of ForgotPasswordRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? identifier = null}) {
    return _then(
      _value.copyWith(
            identifier: null == identifier
                ? _value.identifier
                : identifier // ignore: cast_nullable_to_non_nullable
                      as String,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$ForgotPasswordRequestImplCopyWith<$Res>
    implements $ForgotPasswordRequestCopyWith<$Res> {
  factory _$$ForgotPasswordRequestImplCopyWith(
    _$ForgotPasswordRequestImpl value,
    $Res Function(_$ForgotPasswordRequestImpl) then,
  ) = __$$ForgotPasswordRequestImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({String identifier});
}

/// @nodoc
class __$$ForgotPasswordRequestImplCopyWithImpl<$Res>
    extends
        _$ForgotPasswordRequestCopyWithImpl<$Res, _$ForgotPasswordRequestImpl>
    implements _$$ForgotPasswordRequestImplCopyWith<$Res> {
  __$$ForgotPasswordRequestImplCopyWithImpl(
    _$ForgotPasswordRequestImpl _value,
    $Res Function(_$ForgotPasswordRequestImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of ForgotPasswordRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? identifier = null}) {
    return _then(
      _$ForgotPasswordRequestImpl(
        identifier: null == identifier
            ? _value.identifier
            : identifier // ignore: cast_nullable_to_non_nullable
                  as String,
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$ForgotPasswordRequestImpl implements _ForgotPasswordRequest {
  const _$ForgotPasswordRequestImpl({required this.identifier});

  factory _$ForgotPasswordRequestImpl.fromJson(Map<String, dynamic> json) =>
      _$$ForgotPasswordRequestImplFromJson(json);

  @override
  final String identifier;

  @override
  String toString() {
    return 'ForgotPasswordRequest(identifier: $identifier)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$ForgotPasswordRequestImpl &&
            (identical(other.identifier, identifier) ||
                other.identifier == identifier));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, identifier);

  /// Create a copy of ForgotPasswordRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$ForgotPasswordRequestImplCopyWith<_$ForgotPasswordRequestImpl>
  get copyWith =>
      __$$ForgotPasswordRequestImplCopyWithImpl<_$ForgotPasswordRequestImpl>(
        this,
        _$identity,
      );

  @override
  Map<String, dynamic> toJson() {
    return _$$ForgotPasswordRequestImplToJson(this);
  }
}

abstract class _ForgotPasswordRequest implements ForgotPasswordRequest {
  const factory _ForgotPasswordRequest({required final String identifier}) =
      _$ForgotPasswordRequestImpl;

  factory _ForgotPasswordRequest.fromJson(Map<String, dynamic> json) =
      _$ForgotPasswordRequestImpl.fromJson;

  @override
  String get identifier;

  /// Create a copy of ForgotPasswordRequest
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$ForgotPasswordRequestImplCopyWith<_$ForgotPasswordRequestImpl>
  get copyWith => throw _privateConstructorUsedError;
}

ResetPasswordRequest _$ResetPasswordRequestFromJson(Map<String, dynamic> json) {
  return _ResetPasswordRequest.fromJson(json);
}

/// @nodoc
mixin _$ResetPasswordRequest {
  String get token => throw _privateConstructorUsedError;
  @JsonKey(name: 'new_password')
  String get newPassword => throw _privateConstructorUsedError;

  /// Serializes this ResetPasswordRequest to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of ResetPasswordRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $ResetPasswordRequestCopyWith<ResetPasswordRequest> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $ResetPasswordRequestCopyWith<$Res> {
  factory $ResetPasswordRequestCopyWith(
    ResetPasswordRequest value,
    $Res Function(ResetPasswordRequest) then,
  ) = _$ResetPasswordRequestCopyWithImpl<$Res, ResetPasswordRequest>;
  @useResult
  $Res call({String token, @JsonKey(name: 'new_password') String newPassword});
}

/// @nodoc
class _$ResetPasswordRequestCopyWithImpl<
  $Res,
  $Val extends ResetPasswordRequest
>
    implements $ResetPasswordRequestCopyWith<$Res> {
  _$ResetPasswordRequestCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of ResetPasswordRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? token = null, Object? newPassword = null}) {
    return _then(
      _value.copyWith(
            token: null == token
                ? _value.token
                : token // ignore: cast_nullable_to_non_nullable
                      as String,
            newPassword: null == newPassword
                ? _value.newPassword
                : newPassword // ignore: cast_nullable_to_non_nullable
                      as String,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$ResetPasswordRequestImplCopyWith<$Res>
    implements $ResetPasswordRequestCopyWith<$Res> {
  factory _$$ResetPasswordRequestImplCopyWith(
    _$ResetPasswordRequestImpl value,
    $Res Function(_$ResetPasswordRequestImpl) then,
  ) = __$$ResetPasswordRequestImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({String token, @JsonKey(name: 'new_password') String newPassword});
}

/// @nodoc
class __$$ResetPasswordRequestImplCopyWithImpl<$Res>
    extends _$ResetPasswordRequestCopyWithImpl<$Res, _$ResetPasswordRequestImpl>
    implements _$$ResetPasswordRequestImplCopyWith<$Res> {
  __$$ResetPasswordRequestImplCopyWithImpl(
    _$ResetPasswordRequestImpl _value,
    $Res Function(_$ResetPasswordRequestImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of ResetPasswordRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? token = null, Object? newPassword = null}) {
    return _then(
      _$ResetPasswordRequestImpl(
        token: null == token
            ? _value.token
            : token // ignore: cast_nullable_to_non_nullable
                  as String,
        newPassword: null == newPassword
            ? _value.newPassword
            : newPassword // ignore: cast_nullable_to_non_nullable
                  as String,
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$ResetPasswordRequestImpl implements _ResetPasswordRequest {
  const _$ResetPasswordRequestImpl({
    required this.token,
    @JsonKey(name: 'new_password') required this.newPassword,
  });

  factory _$ResetPasswordRequestImpl.fromJson(Map<String, dynamic> json) =>
      _$$ResetPasswordRequestImplFromJson(json);

  @override
  final String token;
  @override
  @JsonKey(name: 'new_password')
  final String newPassword;

  @override
  String toString() {
    return 'ResetPasswordRequest(token: $token, newPassword: $newPassword)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$ResetPasswordRequestImpl &&
            (identical(other.token, token) || other.token == token) &&
            (identical(other.newPassword, newPassword) ||
                other.newPassword == newPassword));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, token, newPassword);

  /// Create a copy of ResetPasswordRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$ResetPasswordRequestImplCopyWith<_$ResetPasswordRequestImpl>
  get copyWith =>
      __$$ResetPasswordRequestImplCopyWithImpl<_$ResetPasswordRequestImpl>(
        this,
        _$identity,
      );

  @override
  Map<String, dynamic> toJson() {
    return _$$ResetPasswordRequestImplToJson(this);
  }
}

abstract class _ResetPasswordRequest implements ResetPasswordRequest {
  const factory _ResetPasswordRequest({
    required final String token,
    @JsonKey(name: 'new_password') required final String newPassword,
  }) = _$ResetPasswordRequestImpl;

  factory _ResetPasswordRequest.fromJson(Map<String, dynamic> json) =
      _$ResetPasswordRequestImpl.fromJson;

  @override
  String get token;
  @override
  @JsonKey(name: 'new_password')
  String get newPassword;

  /// Create a copy of ResetPasswordRequest
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$ResetPasswordRequestImplCopyWith<_$ResetPasswordRequestImpl>
  get copyWith => throw _privateConstructorUsedError;
}

SendOtpRequest _$SendOtpRequestFromJson(Map<String, dynamic> json) {
  return _SendOtpRequest.fromJson(json);
}

/// @nodoc
mixin _$SendOtpRequest {
  String get type => throw _privateConstructorUsedError;
  String get value => throw _privateConstructorUsedError;

  /// Serializes this SendOtpRequest to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of SendOtpRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $SendOtpRequestCopyWith<SendOtpRequest> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $SendOtpRequestCopyWith<$Res> {
  factory $SendOtpRequestCopyWith(
    SendOtpRequest value,
    $Res Function(SendOtpRequest) then,
  ) = _$SendOtpRequestCopyWithImpl<$Res, SendOtpRequest>;
  @useResult
  $Res call({String type, String value});
}

/// @nodoc
class _$SendOtpRequestCopyWithImpl<$Res, $Val extends SendOtpRequest>
    implements $SendOtpRequestCopyWith<$Res> {
  _$SendOtpRequestCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of SendOtpRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? type = null, Object? value = null}) {
    return _then(
      _value.copyWith(
            type: null == type
                ? _value.type
                : type // ignore: cast_nullable_to_non_nullable
                      as String,
            value: null == value
                ? _value.value
                : value // ignore: cast_nullable_to_non_nullable
                      as String,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$SendOtpRequestImplCopyWith<$Res>
    implements $SendOtpRequestCopyWith<$Res> {
  factory _$$SendOtpRequestImplCopyWith(
    _$SendOtpRequestImpl value,
    $Res Function(_$SendOtpRequestImpl) then,
  ) = __$$SendOtpRequestImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({String type, String value});
}

/// @nodoc
class __$$SendOtpRequestImplCopyWithImpl<$Res>
    extends _$SendOtpRequestCopyWithImpl<$Res, _$SendOtpRequestImpl>
    implements _$$SendOtpRequestImplCopyWith<$Res> {
  __$$SendOtpRequestImplCopyWithImpl(
    _$SendOtpRequestImpl _value,
    $Res Function(_$SendOtpRequestImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of SendOtpRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? type = null, Object? value = null}) {
    return _then(
      _$SendOtpRequestImpl(
        type: null == type
            ? _value.type
            : type // ignore: cast_nullable_to_non_nullable
                  as String,
        value: null == value
            ? _value.value
            : value // ignore: cast_nullable_to_non_nullable
                  as String,
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$SendOtpRequestImpl implements _SendOtpRequest {
  const _$SendOtpRequestImpl({required this.type, required this.value});

  factory _$SendOtpRequestImpl.fromJson(Map<String, dynamic> json) =>
      _$$SendOtpRequestImplFromJson(json);

  @override
  final String type;
  @override
  final String value;

  @override
  String toString() {
    return 'SendOtpRequest(type: $type, value: $value)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$SendOtpRequestImpl &&
            (identical(other.type, type) || other.type == type) &&
            (identical(other.value, value) || other.value == value));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, type, value);

  /// Create a copy of SendOtpRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$SendOtpRequestImplCopyWith<_$SendOtpRequestImpl> get copyWith =>
      __$$SendOtpRequestImplCopyWithImpl<_$SendOtpRequestImpl>(
        this,
        _$identity,
      );

  @override
  Map<String, dynamic> toJson() {
    return _$$SendOtpRequestImplToJson(this);
  }
}

abstract class _SendOtpRequest implements SendOtpRequest {
  const factory _SendOtpRequest({
    required final String type,
    required final String value,
  }) = _$SendOtpRequestImpl;

  factory _SendOtpRequest.fromJson(Map<String, dynamic> json) =
      _$SendOtpRequestImpl.fromJson;

  @override
  String get type;
  @override
  String get value;

  /// Create a copy of SendOtpRequest
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$SendOtpRequestImplCopyWith<_$SendOtpRequestImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

OtpTokenData _$OtpTokenDataFromJson(Map<String, dynamic> json) {
  return _OtpTokenData.fromJson(json);
}

/// @nodoc
mixin _$OtpTokenData {
  @JsonKey(name: 'otp_token')
  String get otpToken => throw _privateConstructorUsedError;

  /// Serializes this OtpTokenData to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of OtpTokenData
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $OtpTokenDataCopyWith<OtpTokenData> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $OtpTokenDataCopyWith<$Res> {
  factory $OtpTokenDataCopyWith(
    OtpTokenData value,
    $Res Function(OtpTokenData) then,
  ) = _$OtpTokenDataCopyWithImpl<$Res, OtpTokenData>;
  @useResult
  $Res call({@JsonKey(name: 'otp_token') String otpToken});
}

/// @nodoc
class _$OtpTokenDataCopyWithImpl<$Res, $Val extends OtpTokenData>
    implements $OtpTokenDataCopyWith<$Res> {
  _$OtpTokenDataCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of OtpTokenData
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? otpToken = null}) {
    return _then(
      _value.copyWith(
            otpToken: null == otpToken
                ? _value.otpToken
                : otpToken // ignore: cast_nullable_to_non_nullable
                      as String,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$OtpTokenDataImplCopyWith<$Res>
    implements $OtpTokenDataCopyWith<$Res> {
  factory _$$OtpTokenDataImplCopyWith(
    _$OtpTokenDataImpl value,
    $Res Function(_$OtpTokenDataImpl) then,
  ) = __$$OtpTokenDataImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({@JsonKey(name: 'otp_token') String otpToken});
}

/// @nodoc
class __$$OtpTokenDataImplCopyWithImpl<$Res>
    extends _$OtpTokenDataCopyWithImpl<$Res, _$OtpTokenDataImpl>
    implements _$$OtpTokenDataImplCopyWith<$Res> {
  __$$OtpTokenDataImplCopyWithImpl(
    _$OtpTokenDataImpl _value,
    $Res Function(_$OtpTokenDataImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of OtpTokenData
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? otpToken = null}) {
    return _then(
      _$OtpTokenDataImpl(
        otpToken: null == otpToken
            ? _value.otpToken
            : otpToken // ignore: cast_nullable_to_non_nullable
                  as String,
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$OtpTokenDataImpl implements _OtpTokenData {
  const _$OtpTokenDataImpl({
    @JsonKey(name: 'otp_token') required this.otpToken,
  });

  factory _$OtpTokenDataImpl.fromJson(Map<String, dynamic> json) =>
      _$$OtpTokenDataImplFromJson(json);

  @override
  @JsonKey(name: 'otp_token')
  final String otpToken;

  @override
  String toString() {
    return 'OtpTokenData(otpToken: $otpToken)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$OtpTokenDataImpl &&
            (identical(other.otpToken, otpToken) ||
                other.otpToken == otpToken));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, otpToken);

  /// Create a copy of OtpTokenData
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$OtpTokenDataImplCopyWith<_$OtpTokenDataImpl> get copyWith =>
      __$$OtpTokenDataImplCopyWithImpl<_$OtpTokenDataImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$OtpTokenDataImplToJson(this);
  }
}

abstract class _OtpTokenData implements OtpTokenData {
  const factory _OtpTokenData({
    @JsonKey(name: 'otp_token') required final String otpToken,
  }) = _$OtpTokenDataImpl;

  factory _OtpTokenData.fromJson(Map<String, dynamic> json) =
      _$OtpTokenDataImpl.fromJson;

  @override
  @JsonKey(name: 'otp_token')
  String get otpToken;

  /// Create a copy of OtpTokenData
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$OtpTokenDataImplCopyWith<_$OtpTokenDataImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

RegisterRequest _$RegisterRequestFromJson(Map<String, dynamic> json) {
  return _RegisterRequest.fromJson(json);
}

/// @nodoc
mixin _$RegisterRequest {
  @JsonKey(name: 'first_name')
  String get firstName => throw _privateConstructorUsedError;
  @JsonKey(name: 'last_name')
  String get lastName => throw _privateConstructorUsedError;
  String get email => throw _privateConstructorUsedError;
  String get password => throw _privateConstructorUsedError;
  @JsonKey(name: 'mobile_no')
  String? get mobileNo => throw _privateConstructorUsedError;
  @JsonKey(name: 'country_id')
  int? get countryId => throw _privateConstructorUsedError;
  @JsonKey(name: 'state_id')
  int? get stateId => throw _privateConstructorUsedError;
  @JsonKey(name: 'referral_id')
  String? get referralId => throw _privateConstructorUsedError;
  @JsonKey(name: 'captcha_token')
  String? get captchaToken => throw _privateConstructorUsedError;
  @JsonKey(name: 'captcha_answer')
  String? get captchaAnswer => throw _privateConstructorUsedError;
  @JsonKey(name: 'email_otp_token')
  String? get emailOtpToken => throw _privateConstructorUsedError;
  @JsonKey(name: 'email_otp_code')
  String? get emailOtpCode => throw _privateConstructorUsedError;
  @JsonKey(name: 'mobile_otp_token')
  String? get mobileOtpToken => throw _privateConstructorUsedError;
  @JsonKey(name: 'mobile_otp_code')
  String? get mobileOtpCode => throw _privateConstructorUsedError;

  /// Serializes this RegisterRequest to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of RegisterRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $RegisterRequestCopyWith<RegisterRequest> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $RegisterRequestCopyWith<$Res> {
  factory $RegisterRequestCopyWith(
    RegisterRequest value,
    $Res Function(RegisterRequest) then,
  ) = _$RegisterRequestCopyWithImpl<$Res, RegisterRequest>;
  @useResult
  $Res call({
    @JsonKey(name: 'first_name') String firstName,
    @JsonKey(name: 'last_name') String lastName,
    String email,
    String password,
    @JsonKey(name: 'mobile_no') String? mobileNo,
    @JsonKey(name: 'country_id') int? countryId,
    @JsonKey(name: 'state_id') int? stateId,
    @JsonKey(name: 'referral_id') String? referralId,
    @JsonKey(name: 'captcha_token') String? captchaToken,
    @JsonKey(name: 'captcha_answer') String? captchaAnswer,
    @JsonKey(name: 'email_otp_token') String? emailOtpToken,
    @JsonKey(name: 'email_otp_code') String? emailOtpCode,
    @JsonKey(name: 'mobile_otp_token') String? mobileOtpToken,
    @JsonKey(name: 'mobile_otp_code') String? mobileOtpCode,
  });
}

/// @nodoc
class _$RegisterRequestCopyWithImpl<$Res, $Val extends RegisterRequest>
    implements $RegisterRequestCopyWith<$Res> {
  _$RegisterRequestCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of RegisterRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? firstName = null,
    Object? lastName = null,
    Object? email = null,
    Object? password = null,
    Object? mobileNo = freezed,
    Object? countryId = freezed,
    Object? stateId = freezed,
    Object? referralId = freezed,
    Object? captchaToken = freezed,
    Object? captchaAnswer = freezed,
    Object? emailOtpToken = freezed,
    Object? emailOtpCode = freezed,
    Object? mobileOtpToken = freezed,
    Object? mobileOtpCode = freezed,
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
            password: null == password
                ? _value.password
                : password // ignore: cast_nullable_to_non_nullable
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
            captchaToken: freezed == captchaToken
                ? _value.captchaToken
                : captchaToken // ignore: cast_nullable_to_non_nullable
                      as String?,
            captchaAnswer: freezed == captchaAnswer
                ? _value.captchaAnswer
                : captchaAnswer // ignore: cast_nullable_to_non_nullable
                      as String?,
            emailOtpToken: freezed == emailOtpToken
                ? _value.emailOtpToken
                : emailOtpToken // ignore: cast_nullable_to_non_nullable
                      as String?,
            emailOtpCode: freezed == emailOtpCode
                ? _value.emailOtpCode
                : emailOtpCode // ignore: cast_nullable_to_non_nullable
                      as String?,
            mobileOtpToken: freezed == mobileOtpToken
                ? _value.mobileOtpToken
                : mobileOtpToken // ignore: cast_nullable_to_non_nullable
                      as String?,
            mobileOtpCode: freezed == mobileOtpCode
                ? _value.mobileOtpCode
                : mobileOtpCode // ignore: cast_nullable_to_non_nullable
                      as String?,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$RegisterRequestImplCopyWith<$Res>
    implements $RegisterRequestCopyWith<$Res> {
  factory _$$RegisterRequestImplCopyWith(
    _$RegisterRequestImpl value,
    $Res Function(_$RegisterRequestImpl) then,
  ) = __$$RegisterRequestImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({
    @JsonKey(name: 'first_name') String firstName,
    @JsonKey(name: 'last_name') String lastName,
    String email,
    String password,
    @JsonKey(name: 'mobile_no') String? mobileNo,
    @JsonKey(name: 'country_id') int? countryId,
    @JsonKey(name: 'state_id') int? stateId,
    @JsonKey(name: 'referral_id') String? referralId,
    @JsonKey(name: 'captcha_token') String? captchaToken,
    @JsonKey(name: 'captcha_answer') String? captchaAnswer,
    @JsonKey(name: 'email_otp_token') String? emailOtpToken,
    @JsonKey(name: 'email_otp_code') String? emailOtpCode,
    @JsonKey(name: 'mobile_otp_token') String? mobileOtpToken,
    @JsonKey(name: 'mobile_otp_code') String? mobileOtpCode,
  });
}

/// @nodoc
class __$$RegisterRequestImplCopyWithImpl<$Res>
    extends _$RegisterRequestCopyWithImpl<$Res, _$RegisterRequestImpl>
    implements _$$RegisterRequestImplCopyWith<$Res> {
  __$$RegisterRequestImplCopyWithImpl(
    _$RegisterRequestImpl _value,
    $Res Function(_$RegisterRequestImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of RegisterRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? firstName = null,
    Object? lastName = null,
    Object? email = null,
    Object? password = null,
    Object? mobileNo = freezed,
    Object? countryId = freezed,
    Object? stateId = freezed,
    Object? referralId = freezed,
    Object? captchaToken = freezed,
    Object? captchaAnswer = freezed,
    Object? emailOtpToken = freezed,
    Object? emailOtpCode = freezed,
    Object? mobileOtpToken = freezed,
    Object? mobileOtpCode = freezed,
  }) {
    return _then(
      _$RegisterRequestImpl(
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
        password: null == password
            ? _value.password
            : password // ignore: cast_nullable_to_non_nullable
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
        captchaToken: freezed == captchaToken
            ? _value.captchaToken
            : captchaToken // ignore: cast_nullable_to_non_nullable
                  as String?,
        captchaAnswer: freezed == captchaAnswer
            ? _value.captchaAnswer
            : captchaAnswer // ignore: cast_nullable_to_non_nullable
                  as String?,
        emailOtpToken: freezed == emailOtpToken
            ? _value.emailOtpToken
            : emailOtpToken // ignore: cast_nullable_to_non_nullable
                  as String?,
        emailOtpCode: freezed == emailOtpCode
            ? _value.emailOtpCode
            : emailOtpCode // ignore: cast_nullable_to_non_nullable
                  as String?,
        mobileOtpToken: freezed == mobileOtpToken
            ? _value.mobileOtpToken
            : mobileOtpToken // ignore: cast_nullable_to_non_nullable
                  as String?,
        mobileOtpCode: freezed == mobileOtpCode
            ? _value.mobileOtpCode
            : mobileOtpCode // ignore: cast_nullable_to_non_nullable
                  as String?,
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$RegisterRequestImpl implements _RegisterRequest {
  const _$RegisterRequestImpl({
    @JsonKey(name: 'first_name') required this.firstName,
    @JsonKey(name: 'last_name') required this.lastName,
    required this.email,
    required this.password,
    @JsonKey(name: 'mobile_no') this.mobileNo,
    @JsonKey(name: 'country_id') this.countryId,
    @JsonKey(name: 'state_id') this.stateId,
    @JsonKey(name: 'referral_id') this.referralId,
    @JsonKey(name: 'captcha_token') this.captchaToken,
    @JsonKey(name: 'captcha_answer') this.captchaAnswer,
    @JsonKey(name: 'email_otp_token') this.emailOtpToken,
    @JsonKey(name: 'email_otp_code') this.emailOtpCode,
    @JsonKey(name: 'mobile_otp_token') this.mobileOtpToken,
    @JsonKey(name: 'mobile_otp_code') this.mobileOtpCode,
  });

  factory _$RegisterRequestImpl.fromJson(Map<String, dynamic> json) =>
      _$$RegisterRequestImplFromJson(json);

  @override
  @JsonKey(name: 'first_name')
  final String firstName;
  @override
  @JsonKey(name: 'last_name')
  final String lastName;
  @override
  final String email;
  @override
  final String password;
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
  @JsonKey(name: 'captcha_token')
  final String? captchaToken;
  @override
  @JsonKey(name: 'captcha_answer')
  final String? captchaAnswer;
  @override
  @JsonKey(name: 'email_otp_token')
  final String? emailOtpToken;
  @override
  @JsonKey(name: 'email_otp_code')
  final String? emailOtpCode;
  @override
  @JsonKey(name: 'mobile_otp_token')
  final String? mobileOtpToken;
  @override
  @JsonKey(name: 'mobile_otp_code')
  final String? mobileOtpCode;

  @override
  String toString() {
    return 'RegisterRequest(firstName: $firstName, lastName: $lastName, email: $email, password: $password, mobileNo: $mobileNo, countryId: $countryId, stateId: $stateId, referralId: $referralId, captchaToken: $captchaToken, captchaAnswer: $captchaAnswer, emailOtpToken: $emailOtpToken, emailOtpCode: $emailOtpCode, mobileOtpToken: $mobileOtpToken, mobileOtpCode: $mobileOtpCode)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$RegisterRequestImpl &&
            (identical(other.firstName, firstName) ||
                other.firstName == firstName) &&
            (identical(other.lastName, lastName) ||
                other.lastName == lastName) &&
            (identical(other.email, email) || other.email == email) &&
            (identical(other.password, password) ||
                other.password == password) &&
            (identical(other.mobileNo, mobileNo) ||
                other.mobileNo == mobileNo) &&
            (identical(other.countryId, countryId) ||
                other.countryId == countryId) &&
            (identical(other.stateId, stateId) || other.stateId == stateId) &&
            (identical(other.referralId, referralId) ||
                other.referralId == referralId) &&
            (identical(other.captchaToken, captchaToken) ||
                other.captchaToken == captchaToken) &&
            (identical(other.captchaAnswer, captchaAnswer) ||
                other.captchaAnswer == captchaAnswer) &&
            (identical(other.emailOtpToken, emailOtpToken) ||
                other.emailOtpToken == emailOtpToken) &&
            (identical(other.emailOtpCode, emailOtpCode) ||
                other.emailOtpCode == emailOtpCode) &&
            (identical(other.mobileOtpToken, mobileOtpToken) ||
                other.mobileOtpToken == mobileOtpToken) &&
            (identical(other.mobileOtpCode, mobileOtpCode) ||
                other.mobileOtpCode == mobileOtpCode));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
    runtimeType,
    firstName,
    lastName,
    email,
    password,
    mobileNo,
    countryId,
    stateId,
    referralId,
    captchaToken,
    captchaAnswer,
    emailOtpToken,
    emailOtpCode,
    mobileOtpToken,
    mobileOtpCode,
  );

  /// Create a copy of RegisterRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$RegisterRequestImplCopyWith<_$RegisterRequestImpl> get copyWith =>
      __$$RegisterRequestImplCopyWithImpl<_$RegisterRequestImpl>(
        this,
        _$identity,
      );

  @override
  Map<String, dynamic> toJson() {
    return _$$RegisterRequestImplToJson(this);
  }
}

abstract class _RegisterRequest implements RegisterRequest {
  const factory _RegisterRequest({
    @JsonKey(name: 'first_name') required final String firstName,
    @JsonKey(name: 'last_name') required final String lastName,
    required final String email,
    required final String password,
    @JsonKey(name: 'mobile_no') final String? mobileNo,
    @JsonKey(name: 'country_id') final int? countryId,
    @JsonKey(name: 'state_id') final int? stateId,
    @JsonKey(name: 'referral_id') final String? referralId,
    @JsonKey(name: 'captcha_token') final String? captchaToken,
    @JsonKey(name: 'captcha_answer') final String? captchaAnswer,
    @JsonKey(name: 'email_otp_token') final String? emailOtpToken,
    @JsonKey(name: 'email_otp_code') final String? emailOtpCode,
    @JsonKey(name: 'mobile_otp_token') final String? mobileOtpToken,
    @JsonKey(name: 'mobile_otp_code') final String? mobileOtpCode,
  }) = _$RegisterRequestImpl;

  factory _RegisterRequest.fromJson(Map<String, dynamic> json) =
      _$RegisterRequestImpl.fromJson;

  @override
  @JsonKey(name: 'first_name')
  String get firstName;
  @override
  @JsonKey(name: 'last_name')
  String get lastName;
  @override
  String get email;
  @override
  String get password;
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
  @JsonKey(name: 'captcha_token')
  String? get captchaToken;
  @override
  @JsonKey(name: 'captcha_answer')
  String? get captchaAnswer;
  @override
  @JsonKey(name: 'email_otp_token')
  String? get emailOtpToken;
  @override
  @JsonKey(name: 'email_otp_code')
  String? get emailOtpCode;
  @override
  @JsonKey(name: 'mobile_otp_token')
  String? get mobileOtpToken;
  @override
  @JsonKey(name: 'mobile_otp_code')
  String? get mobileOtpCode;

  /// Create a copy of RegisterRequest
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$RegisterRequestImplCopyWith<_$RegisterRequestImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

CaptchaData _$CaptchaDataFromJson(Map<String, dynamic> json) {
  return _CaptchaData.fromJson(json);
}

/// @nodoc
mixin _$CaptchaData {
  String get type => throw _privateConstructorUsedError;
  String? get image => throw _privateConstructorUsedError;
  String? get token => throw _privateConstructorUsedError;
  @JsonKey(name: 'site_key')
  String? get siteKey => throw _privateConstructorUsedError;

  /// Serializes this CaptchaData to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of CaptchaData
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $CaptchaDataCopyWith<CaptchaData> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $CaptchaDataCopyWith<$Res> {
  factory $CaptchaDataCopyWith(
    CaptchaData value,
    $Res Function(CaptchaData) then,
  ) = _$CaptchaDataCopyWithImpl<$Res, CaptchaData>;
  @useResult
  $Res call({
    String type,
    String? image,
    String? token,
    @JsonKey(name: 'site_key') String? siteKey,
  });
}

/// @nodoc
class _$CaptchaDataCopyWithImpl<$Res, $Val extends CaptchaData>
    implements $CaptchaDataCopyWith<$Res> {
  _$CaptchaDataCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of CaptchaData
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? type = null,
    Object? image = freezed,
    Object? token = freezed,
    Object? siteKey = freezed,
  }) {
    return _then(
      _value.copyWith(
            type: null == type
                ? _value.type
                : type // ignore: cast_nullable_to_non_nullable
                      as String,
            image: freezed == image
                ? _value.image
                : image // ignore: cast_nullable_to_non_nullable
                      as String?,
            token: freezed == token
                ? _value.token
                : token // ignore: cast_nullable_to_non_nullable
                      as String?,
            siteKey: freezed == siteKey
                ? _value.siteKey
                : siteKey // ignore: cast_nullable_to_non_nullable
                      as String?,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$CaptchaDataImplCopyWith<$Res>
    implements $CaptchaDataCopyWith<$Res> {
  factory _$$CaptchaDataImplCopyWith(
    _$CaptchaDataImpl value,
    $Res Function(_$CaptchaDataImpl) then,
  ) = __$$CaptchaDataImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({
    String type,
    String? image,
    String? token,
    @JsonKey(name: 'site_key') String? siteKey,
  });
}

/// @nodoc
class __$$CaptchaDataImplCopyWithImpl<$Res>
    extends _$CaptchaDataCopyWithImpl<$Res, _$CaptchaDataImpl>
    implements _$$CaptchaDataImplCopyWith<$Res> {
  __$$CaptchaDataImplCopyWithImpl(
    _$CaptchaDataImpl _value,
    $Res Function(_$CaptchaDataImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of CaptchaData
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? type = null,
    Object? image = freezed,
    Object? token = freezed,
    Object? siteKey = freezed,
  }) {
    return _then(
      _$CaptchaDataImpl(
        type: null == type
            ? _value.type
            : type // ignore: cast_nullable_to_non_nullable
                  as String,
        image: freezed == image
            ? _value.image
            : image // ignore: cast_nullable_to_non_nullable
                  as String?,
        token: freezed == token
            ? _value.token
            : token // ignore: cast_nullable_to_non_nullable
                  as String?,
        siteKey: freezed == siteKey
            ? _value.siteKey
            : siteKey // ignore: cast_nullable_to_non_nullable
                  as String?,
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$CaptchaDataImpl implements _CaptchaData {
  const _$CaptchaDataImpl({
    required this.type,
    this.image,
    this.token,
    @JsonKey(name: 'site_key') this.siteKey,
  });

  factory _$CaptchaDataImpl.fromJson(Map<String, dynamic> json) =>
      _$$CaptchaDataImplFromJson(json);

  @override
  final String type;
  @override
  final String? image;
  @override
  final String? token;
  @override
  @JsonKey(name: 'site_key')
  final String? siteKey;

  @override
  String toString() {
    return 'CaptchaData(type: $type, image: $image, token: $token, siteKey: $siteKey)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$CaptchaDataImpl &&
            (identical(other.type, type) || other.type == type) &&
            (identical(other.image, image) || other.image == image) &&
            (identical(other.token, token) || other.token == token) &&
            (identical(other.siteKey, siteKey) || other.siteKey == siteKey));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, type, image, token, siteKey);

  /// Create a copy of CaptchaData
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$CaptchaDataImplCopyWith<_$CaptchaDataImpl> get copyWith =>
      __$$CaptchaDataImplCopyWithImpl<_$CaptchaDataImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$CaptchaDataImplToJson(this);
  }
}

abstract class _CaptchaData implements CaptchaData {
  const factory _CaptchaData({
    required final String type,
    final String? image,
    final String? token,
    @JsonKey(name: 'site_key') final String? siteKey,
  }) = _$CaptchaDataImpl;

  factory _CaptchaData.fromJson(Map<String, dynamic> json) =
      _$CaptchaDataImpl.fromJson;

  @override
  String get type;
  @override
  String? get image;
  @override
  String? get token;
  @override
  @JsonKey(name: 'site_key')
  String? get siteKey;

  /// Create a copy of CaptchaData
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$CaptchaDataImplCopyWith<_$CaptchaDataImpl> get copyWith =>
      throw _privateConstructorUsedError;
}
