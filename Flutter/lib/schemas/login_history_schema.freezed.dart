// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'login_history_schema.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
  'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models',
);

LoginHistoryListRequest _$LoginHistoryListRequestFromJson(
  Map<String, dynamic> json,
) {
  return _LoginHistoryListRequest.fromJson(json);
}

/// @nodoc
mixin _$LoginHistoryListRequest {
  @JsonKey(name: 'page_index')
  int get pageIndex => throw _privateConstructorUsedError;
  @JsonKey(name: 'page_size')
  int get pageSize => throw _privateConstructorUsedError;

  /// Serializes this LoginHistoryListRequest to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of LoginHistoryListRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $LoginHistoryListRequestCopyWith<LoginHistoryListRequest> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $LoginHistoryListRequestCopyWith<$Res> {
  factory $LoginHistoryListRequestCopyWith(
    LoginHistoryListRequest value,
    $Res Function(LoginHistoryListRequest) then,
  ) = _$LoginHistoryListRequestCopyWithImpl<$Res, LoginHistoryListRequest>;
  @useResult
  $Res call({
    @JsonKey(name: 'page_index') int pageIndex,
    @JsonKey(name: 'page_size') int pageSize,
  });
}

/// @nodoc
class _$LoginHistoryListRequestCopyWithImpl<
  $Res,
  $Val extends LoginHistoryListRequest
>
    implements $LoginHistoryListRequestCopyWith<$Res> {
  _$LoginHistoryListRequestCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of LoginHistoryListRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? pageIndex = null, Object? pageSize = null}) {
    return _then(
      _value.copyWith(
            pageIndex: null == pageIndex
                ? _value.pageIndex
                : pageIndex // ignore: cast_nullable_to_non_nullable
                      as int,
            pageSize: null == pageSize
                ? _value.pageSize
                : pageSize // ignore: cast_nullable_to_non_nullable
                      as int,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$LoginHistoryListRequestImplCopyWith<$Res>
    implements $LoginHistoryListRequestCopyWith<$Res> {
  factory _$$LoginHistoryListRequestImplCopyWith(
    _$LoginHistoryListRequestImpl value,
    $Res Function(_$LoginHistoryListRequestImpl) then,
  ) = __$$LoginHistoryListRequestImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({
    @JsonKey(name: 'page_index') int pageIndex,
    @JsonKey(name: 'page_size') int pageSize,
  });
}

/// @nodoc
class __$$LoginHistoryListRequestImplCopyWithImpl<$Res>
    extends
        _$LoginHistoryListRequestCopyWithImpl<
          $Res,
          _$LoginHistoryListRequestImpl
        >
    implements _$$LoginHistoryListRequestImplCopyWith<$Res> {
  __$$LoginHistoryListRequestImplCopyWithImpl(
    _$LoginHistoryListRequestImpl _value,
    $Res Function(_$LoginHistoryListRequestImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of LoginHistoryListRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? pageIndex = null, Object? pageSize = null}) {
    return _then(
      _$LoginHistoryListRequestImpl(
        pageIndex: null == pageIndex
            ? _value.pageIndex
            : pageIndex // ignore: cast_nullable_to_non_nullable
                  as int,
        pageSize: null == pageSize
            ? _value.pageSize
            : pageSize // ignore: cast_nullable_to_non_nullable
                  as int,
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$LoginHistoryListRequestImpl implements _LoginHistoryListRequest {
  const _$LoginHistoryListRequestImpl({
    @JsonKey(name: 'page_index') this.pageIndex = 1,
    @JsonKey(name: 'page_size') this.pageSize = 10,
  });

  factory _$LoginHistoryListRequestImpl.fromJson(Map<String, dynamic> json) =>
      _$$LoginHistoryListRequestImplFromJson(json);

  @override
  @JsonKey(name: 'page_index')
  final int pageIndex;
  @override
  @JsonKey(name: 'page_size')
  final int pageSize;

  @override
  String toString() {
    return 'LoginHistoryListRequest(pageIndex: $pageIndex, pageSize: $pageSize)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$LoginHistoryListRequestImpl &&
            (identical(other.pageIndex, pageIndex) ||
                other.pageIndex == pageIndex) &&
            (identical(other.pageSize, pageSize) ||
                other.pageSize == pageSize));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, pageIndex, pageSize);

  /// Create a copy of LoginHistoryListRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$LoginHistoryListRequestImplCopyWith<_$LoginHistoryListRequestImpl>
  get copyWith =>
      __$$LoginHistoryListRequestImplCopyWithImpl<
        _$LoginHistoryListRequestImpl
      >(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$LoginHistoryListRequestImplToJson(this);
  }
}

abstract class _LoginHistoryListRequest implements LoginHistoryListRequest {
  const factory _LoginHistoryListRequest({
    @JsonKey(name: 'page_index') final int pageIndex,
    @JsonKey(name: 'page_size') final int pageSize,
  }) = _$LoginHistoryListRequestImpl;

  factory _LoginHistoryListRequest.fromJson(Map<String, dynamic> json) =
      _$LoginHistoryListRequestImpl.fromJson;

  @override
  @JsonKey(name: 'page_index')
  int get pageIndex;
  @override
  @JsonKey(name: 'page_size')
  int get pageSize;

  /// Create a copy of LoginHistoryListRequest
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$LoginHistoryListRequestImplCopyWith<_$LoginHistoryListRequestImpl>
  get copyWith => throw _privateConstructorUsedError;
}

LogoutSessionRequest _$LogoutSessionRequestFromJson(Map<String, dynamic> json) {
  return _LogoutSessionRequest.fromJson(json);
}

/// @nodoc
mixin _$LogoutSessionRequest {
  @JsonKey(name: 'token_id')
  int get tokenId => throw _privateConstructorUsedError;

  /// Serializes this LogoutSessionRequest to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of LogoutSessionRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $LogoutSessionRequestCopyWith<LogoutSessionRequest> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $LogoutSessionRequestCopyWith<$Res> {
  factory $LogoutSessionRequestCopyWith(
    LogoutSessionRequest value,
    $Res Function(LogoutSessionRequest) then,
  ) = _$LogoutSessionRequestCopyWithImpl<$Res, LogoutSessionRequest>;
  @useResult
  $Res call({@JsonKey(name: 'token_id') int tokenId});
}

/// @nodoc
class _$LogoutSessionRequestCopyWithImpl<
  $Res,
  $Val extends LogoutSessionRequest
>
    implements $LogoutSessionRequestCopyWith<$Res> {
  _$LogoutSessionRequestCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of LogoutSessionRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? tokenId = null}) {
    return _then(
      _value.copyWith(
            tokenId: null == tokenId
                ? _value.tokenId
                : tokenId // ignore: cast_nullable_to_non_nullable
                      as int,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$LogoutSessionRequestImplCopyWith<$Res>
    implements $LogoutSessionRequestCopyWith<$Res> {
  factory _$$LogoutSessionRequestImplCopyWith(
    _$LogoutSessionRequestImpl value,
    $Res Function(_$LogoutSessionRequestImpl) then,
  ) = __$$LogoutSessionRequestImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({@JsonKey(name: 'token_id') int tokenId});
}

/// @nodoc
class __$$LogoutSessionRequestImplCopyWithImpl<$Res>
    extends _$LogoutSessionRequestCopyWithImpl<$Res, _$LogoutSessionRequestImpl>
    implements _$$LogoutSessionRequestImplCopyWith<$Res> {
  __$$LogoutSessionRequestImplCopyWithImpl(
    _$LogoutSessionRequestImpl _value,
    $Res Function(_$LogoutSessionRequestImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of LogoutSessionRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? tokenId = null}) {
    return _then(
      _$LogoutSessionRequestImpl(
        tokenId: null == tokenId
            ? _value.tokenId
            : tokenId // ignore: cast_nullable_to_non_nullable
                  as int,
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$LogoutSessionRequestImpl implements _LogoutSessionRequest {
  const _$LogoutSessionRequestImpl({
    @JsonKey(name: 'token_id') required this.tokenId,
  });

  factory _$LogoutSessionRequestImpl.fromJson(Map<String, dynamic> json) =>
      _$$LogoutSessionRequestImplFromJson(json);

  @override
  @JsonKey(name: 'token_id')
  final int tokenId;

  @override
  String toString() {
    return 'LogoutSessionRequest(tokenId: $tokenId)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$LogoutSessionRequestImpl &&
            (identical(other.tokenId, tokenId) || other.tokenId == tokenId));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, tokenId);

  /// Create a copy of LogoutSessionRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$LogoutSessionRequestImplCopyWith<_$LogoutSessionRequestImpl>
  get copyWith =>
      __$$LogoutSessionRequestImplCopyWithImpl<_$LogoutSessionRequestImpl>(
        this,
        _$identity,
      );

  @override
  Map<String, dynamic> toJson() {
    return _$$LogoutSessionRequestImplToJson(this);
  }
}

abstract class _LogoutSessionRequest implements LogoutSessionRequest {
  const factory _LogoutSessionRequest({
    @JsonKey(name: 'token_id') required final int tokenId,
  }) = _$LogoutSessionRequestImpl;

  factory _LogoutSessionRequest.fromJson(Map<String, dynamic> json) =
      _$LogoutSessionRequestImpl.fromJson;

  @override
  @JsonKey(name: 'token_id')
  int get tokenId;

  /// Create a copy of LogoutSessionRequest
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$LogoutSessionRequestImplCopyWith<_$LogoutSessionRequestImpl>
  get copyWith => throw _privateConstructorUsedError;
}
