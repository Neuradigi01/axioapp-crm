// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'tfa_schema.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
  'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models',
);

SendSetupOtpRequest _$SendSetupOtpRequestFromJson(Map<String, dynamic> json) {
  return _SendSetupOtpRequest.fromJson(json);
}

/// @nodoc
mixin _$SendSetupOtpRequest {
  String get method => throw _privateConstructorUsedError;

  /// Serializes this SendSetupOtpRequest to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of SendSetupOtpRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $SendSetupOtpRequestCopyWith<SendSetupOtpRequest> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $SendSetupOtpRequestCopyWith<$Res> {
  factory $SendSetupOtpRequestCopyWith(
    SendSetupOtpRequest value,
    $Res Function(SendSetupOtpRequest) then,
  ) = _$SendSetupOtpRequestCopyWithImpl<$Res, SendSetupOtpRequest>;
  @useResult
  $Res call({String method});
}

/// @nodoc
class _$SendSetupOtpRequestCopyWithImpl<$Res, $Val extends SendSetupOtpRequest>
    implements $SendSetupOtpRequestCopyWith<$Res> {
  _$SendSetupOtpRequestCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of SendSetupOtpRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? method = null}) {
    return _then(
      _value.copyWith(
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
abstract class _$$SendSetupOtpRequestImplCopyWith<$Res>
    implements $SendSetupOtpRequestCopyWith<$Res> {
  factory _$$SendSetupOtpRequestImplCopyWith(
    _$SendSetupOtpRequestImpl value,
    $Res Function(_$SendSetupOtpRequestImpl) then,
  ) = __$$SendSetupOtpRequestImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({String method});
}

/// @nodoc
class __$$SendSetupOtpRequestImplCopyWithImpl<$Res>
    extends _$SendSetupOtpRequestCopyWithImpl<$Res, _$SendSetupOtpRequestImpl>
    implements _$$SendSetupOtpRequestImplCopyWith<$Res> {
  __$$SendSetupOtpRequestImplCopyWithImpl(
    _$SendSetupOtpRequestImpl _value,
    $Res Function(_$SendSetupOtpRequestImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of SendSetupOtpRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? method = null}) {
    return _then(
      _$SendSetupOtpRequestImpl(
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
class _$SendSetupOtpRequestImpl implements _SendSetupOtpRequest {
  const _$SendSetupOtpRequestImpl({required this.method});

  factory _$SendSetupOtpRequestImpl.fromJson(Map<String, dynamic> json) =>
      _$$SendSetupOtpRequestImplFromJson(json);

  @override
  final String method;

  @override
  String toString() {
    return 'SendSetupOtpRequest(method: $method)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$SendSetupOtpRequestImpl &&
            (identical(other.method, method) || other.method == method));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, method);

  /// Create a copy of SendSetupOtpRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$SendSetupOtpRequestImplCopyWith<_$SendSetupOtpRequestImpl> get copyWith =>
      __$$SendSetupOtpRequestImplCopyWithImpl<_$SendSetupOtpRequestImpl>(
        this,
        _$identity,
      );

  @override
  Map<String, dynamic> toJson() {
    return _$$SendSetupOtpRequestImplToJson(this);
  }
}

abstract class _SendSetupOtpRequest implements SendSetupOtpRequest {
  const factory _SendSetupOtpRequest({required final String method}) =
      _$SendSetupOtpRequestImpl;

  factory _SendSetupOtpRequest.fromJson(Map<String, dynamic> json) =
      _$SendSetupOtpRequestImpl.fromJson;

  @override
  String get method;

  /// Create a copy of SendSetupOtpRequest
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$SendSetupOtpRequestImplCopyWith<_$SendSetupOtpRequestImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

VerifyAndEnableRequest _$VerifyAndEnableRequestFromJson(
  Map<String, dynamic> json,
) {
  return _VerifyAndEnableRequest.fromJson(json);
}

/// @nodoc
mixin _$VerifyAndEnableRequest {
  String get code => throw _privateConstructorUsedError;
  String get method => throw _privateConstructorUsedError;

  /// Serializes this VerifyAndEnableRequest to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of VerifyAndEnableRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $VerifyAndEnableRequestCopyWith<VerifyAndEnableRequest> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $VerifyAndEnableRequestCopyWith<$Res> {
  factory $VerifyAndEnableRequestCopyWith(
    VerifyAndEnableRequest value,
    $Res Function(VerifyAndEnableRequest) then,
  ) = _$VerifyAndEnableRequestCopyWithImpl<$Res, VerifyAndEnableRequest>;
  @useResult
  $Res call({String code, String method});
}

/// @nodoc
class _$VerifyAndEnableRequestCopyWithImpl<
  $Res,
  $Val extends VerifyAndEnableRequest
>
    implements $VerifyAndEnableRequestCopyWith<$Res> {
  _$VerifyAndEnableRequestCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of VerifyAndEnableRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? code = null, Object? method = null}) {
    return _then(
      _value.copyWith(
            code: null == code
                ? _value.code
                : code // ignore: cast_nullable_to_non_nullable
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
abstract class _$$VerifyAndEnableRequestImplCopyWith<$Res>
    implements $VerifyAndEnableRequestCopyWith<$Res> {
  factory _$$VerifyAndEnableRequestImplCopyWith(
    _$VerifyAndEnableRequestImpl value,
    $Res Function(_$VerifyAndEnableRequestImpl) then,
  ) = __$$VerifyAndEnableRequestImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({String code, String method});
}

/// @nodoc
class __$$VerifyAndEnableRequestImplCopyWithImpl<$Res>
    extends
        _$VerifyAndEnableRequestCopyWithImpl<$Res, _$VerifyAndEnableRequestImpl>
    implements _$$VerifyAndEnableRequestImplCopyWith<$Res> {
  __$$VerifyAndEnableRequestImplCopyWithImpl(
    _$VerifyAndEnableRequestImpl _value,
    $Res Function(_$VerifyAndEnableRequestImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of VerifyAndEnableRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? code = null, Object? method = null}) {
    return _then(
      _$VerifyAndEnableRequestImpl(
        code: null == code
            ? _value.code
            : code // ignore: cast_nullable_to_non_nullable
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
class _$VerifyAndEnableRequestImpl implements _VerifyAndEnableRequest {
  const _$VerifyAndEnableRequestImpl({
    required this.code,
    required this.method,
  });

  factory _$VerifyAndEnableRequestImpl.fromJson(Map<String, dynamic> json) =>
      _$$VerifyAndEnableRequestImplFromJson(json);

  @override
  final String code;
  @override
  final String method;

  @override
  String toString() {
    return 'VerifyAndEnableRequest(code: $code, method: $method)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$VerifyAndEnableRequestImpl &&
            (identical(other.code, code) || other.code == code) &&
            (identical(other.method, method) || other.method == method));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, code, method);

  /// Create a copy of VerifyAndEnableRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$VerifyAndEnableRequestImplCopyWith<_$VerifyAndEnableRequestImpl>
  get copyWith =>
      __$$VerifyAndEnableRequestImplCopyWithImpl<_$VerifyAndEnableRequestImpl>(
        this,
        _$identity,
      );

  @override
  Map<String, dynamic> toJson() {
    return _$$VerifyAndEnableRequestImplToJson(this);
  }
}

abstract class _VerifyAndEnableRequest implements VerifyAndEnableRequest {
  const factory _VerifyAndEnableRequest({
    required final String code,
    required final String method,
  }) = _$VerifyAndEnableRequestImpl;

  factory _VerifyAndEnableRequest.fromJson(Map<String, dynamic> json) =
      _$VerifyAndEnableRequestImpl.fromJson;

  @override
  String get code;
  @override
  String get method;

  /// Create a copy of VerifyAndEnableRequest
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$VerifyAndEnableRequestImplCopyWith<_$VerifyAndEnableRequestImpl>
  get copyWith => throw _privateConstructorUsedError;
}

ChangeMethodRequest _$ChangeMethodRequestFromJson(Map<String, dynamic> json) {
  return _ChangeMethodRequest.fromJson(json);
}

/// @nodoc
mixin _$ChangeMethodRequest {
  @JsonKey(name: 'new_method')
  String get newMethod => throw _privateConstructorUsedError;

  /// Serializes this ChangeMethodRequest to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of ChangeMethodRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $ChangeMethodRequestCopyWith<ChangeMethodRequest> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $ChangeMethodRequestCopyWith<$Res> {
  factory $ChangeMethodRequestCopyWith(
    ChangeMethodRequest value,
    $Res Function(ChangeMethodRequest) then,
  ) = _$ChangeMethodRequestCopyWithImpl<$Res, ChangeMethodRequest>;
  @useResult
  $Res call({@JsonKey(name: 'new_method') String newMethod});
}

/// @nodoc
class _$ChangeMethodRequestCopyWithImpl<$Res, $Val extends ChangeMethodRequest>
    implements $ChangeMethodRequestCopyWith<$Res> {
  _$ChangeMethodRequestCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of ChangeMethodRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? newMethod = null}) {
    return _then(
      _value.copyWith(
            newMethod: null == newMethod
                ? _value.newMethod
                : newMethod // ignore: cast_nullable_to_non_nullable
                      as String,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$ChangeMethodRequestImplCopyWith<$Res>
    implements $ChangeMethodRequestCopyWith<$Res> {
  factory _$$ChangeMethodRequestImplCopyWith(
    _$ChangeMethodRequestImpl value,
    $Res Function(_$ChangeMethodRequestImpl) then,
  ) = __$$ChangeMethodRequestImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({@JsonKey(name: 'new_method') String newMethod});
}

/// @nodoc
class __$$ChangeMethodRequestImplCopyWithImpl<$Res>
    extends _$ChangeMethodRequestCopyWithImpl<$Res, _$ChangeMethodRequestImpl>
    implements _$$ChangeMethodRequestImplCopyWith<$Res> {
  __$$ChangeMethodRequestImplCopyWithImpl(
    _$ChangeMethodRequestImpl _value,
    $Res Function(_$ChangeMethodRequestImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of ChangeMethodRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? newMethod = null}) {
    return _then(
      _$ChangeMethodRequestImpl(
        newMethod: null == newMethod
            ? _value.newMethod
            : newMethod // ignore: cast_nullable_to_non_nullable
                  as String,
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$ChangeMethodRequestImpl implements _ChangeMethodRequest {
  const _$ChangeMethodRequestImpl({
    @JsonKey(name: 'new_method') required this.newMethod,
  });

  factory _$ChangeMethodRequestImpl.fromJson(Map<String, dynamic> json) =>
      _$$ChangeMethodRequestImplFromJson(json);

  @override
  @JsonKey(name: 'new_method')
  final String newMethod;

  @override
  String toString() {
    return 'ChangeMethodRequest(newMethod: $newMethod)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$ChangeMethodRequestImpl &&
            (identical(other.newMethod, newMethod) ||
                other.newMethod == newMethod));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, newMethod);

  /// Create a copy of ChangeMethodRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$ChangeMethodRequestImplCopyWith<_$ChangeMethodRequestImpl> get copyWith =>
      __$$ChangeMethodRequestImplCopyWithImpl<_$ChangeMethodRequestImpl>(
        this,
        _$identity,
      );

  @override
  Map<String, dynamic> toJson() {
    return _$$ChangeMethodRequestImplToJson(this);
  }
}

abstract class _ChangeMethodRequest implements ChangeMethodRequest {
  const factory _ChangeMethodRequest({
    @JsonKey(name: 'new_method') required final String newMethod,
  }) = _$ChangeMethodRequestImpl;

  factory _ChangeMethodRequest.fromJson(Map<String, dynamic> json) =
      _$ChangeMethodRequestImpl.fromJson;

  @override
  @JsonKey(name: 'new_method')
  String get newMethod;

  /// Create a copy of ChangeMethodRequest
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$ChangeMethodRequestImplCopyWith<_$ChangeMethodRequestImpl> get copyWith =>
      throw _privateConstructorUsedError;
}
