// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'location.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
  'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models',
);

Country _$CountryFromJson(Map<String, dynamic> json) {
  return _Country.fromJson(json);
}

/// @nodoc
mixin _$Country {
  int get id => throw _privateConstructorUsedError;
  String get name => throw _privateConstructorUsedError;
  String get iso2 => throw _privateConstructorUsedError;
  String get iso3 => throw _privateConstructorUsedError;
  @JsonKey(name: 'calling_code')
  String get callingCode => throw _privateConstructorUsedError;
  String get currency => throw _privateConstructorUsedError;
  @JsonKey(name: 'currency_code')
  String get currencyCode => throw _privateConstructorUsedError;
  String get capital => throw _privateConstructorUsedError;

  /// Serializes this Country to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of Country
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $CountryCopyWith<Country> get copyWith => throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $CountryCopyWith<$Res> {
  factory $CountryCopyWith(Country value, $Res Function(Country) then) =
      _$CountryCopyWithImpl<$Res, Country>;
  @useResult
  $Res call({
    int id,
    String name,
    String iso2,
    String iso3,
    @JsonKey(name: 'calling_code') String callingCode,
    String currency,
    @JsonKey(name: 'currency_code') String currencyCode,
    String capital,
  });
}

/// @nodoc
class _$CountryCopyWithImpl<$Res, $Val extends Country>
    implements $CountryCopyWith<$Res> {
  _$CountryCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of Country
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? name = null,
    Object? iso2 = null,
    Object? iso3 = null,
    Object? callingCode = null,
    Object? currency = null,
    Object? currencyCode = null,
    Object? capital = null,
  }) {
    return _then(
      _value.copyWith(
            id: null == id
                ? _value.id
                : id // ignore: cast_nullable_to_non_nullable
                      as int,
            name: null == name
                ? _value.name
                : name // ignore: cast_nullable_to_non_nullable
                      as String,
            iso2: null == iso2
                ? _value.iso2
                : iso2 // ignore: cast_nullable_to_non_nullable
                      as String,
            iso3: null == iso3
                ? _value.iso3
                : iso3 // ignore: cast_nullable_to_non_nullable
                      as String,
            callingCode: null == callingCode
                ? _value.callingCode
                : callingCode // ignore: cast_nullable_to_non_nullable
                      as String,
            currency: null == currency
                ? _value.currency
                : currency // ignore: cast_nullable_to_non_nullable
                      as String,
            currencyCode: null == currencyCode
                ? _value.currencyCode
                : currencyCode // ignore: cast_nullable_to_non_nullable
                      as String,
            capital: null == capital
                ? _value.capital
                : capital // ignore: cast_nullable_to_non_nullable
                      as String,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$CountryImplCopyWith<$Res> implements $CountryCopyWith<$Res> {
  factory _$$CountryImplCopyWith(
    _$CountryImpl value,
    $Res Function(_$CountryImpl) then,
  ) = __$$CountryImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({
    int id,
    String name,
    String iso2,
    String iso3,
    @JsonKey(name: 'calling_code') String callingCode,
    String currency,
    @JsonKey(name: 'currency_code') String currencyCode,
    String capital,
  });
}

/// @nodoc
class __$$CountryImplCopyWithImpl<$Res>
    extends _$CountryCopyWithImpl<$Res, _$CountryImpl>
    implements _$$CountryImplCopyWith<$Res> {
  __$$CountryImplCopyWithImpl(
    _$CountryImpl _value,
    $Res Function(_$CountryImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of Country
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? name = null,
    Object? iso2 = null,
    Object? iso3 = null,
    Object? callingCode = null,
    Object? currency = null,
    Object? currencyCode = null,
    Object? capital = null,
  }) {
    return _then(
      _$CountryImpl(
        id: null == id
            ? _value.id
            : id // ignore: cast_nullable_to_non_nullable
                  as int,
        name: null == name
            ? _value.name
            : name // ignore: cast_nullable_to_non_nullable
                  as String,
        iso2: null == iso2
            ? _value.iso2
            : iso2 // ignore: cast_nullable_to_non_nullable
                  as String,
        iso3: null == iso3
            ? _value.iso3
            : iso3 // ignore: cast_nullable_to_non_nullable
                  as String,
        callingCode: null == callingCode
            ? _value.callingCode
            : callingCode // ignore: cast_nullable_to_non_nullable
                  as String,
        currency: null == currency
            ? _value.currency
            : currency // ignore: cast_nullable_to_non_nullable
                  as String,
        currencyCode: null == currencyCode
            ? _value.currencyCode
            : currencyCode // ignore: cast_nullable_to_non_nullable
                  as String,
        capital: null == capital
            ? _value.capital
            : capital // ignore: cast_nullable_to_non_nullable
                  as String,
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$CountryImpl implements _Country {
  const _$CountryImpl({
    required this.id,
    required this.name,
    this.iso2 = '',
    this.iso3 = '',
    @JsonKey(name: 'calling_code') this.callingCode = '',
    this.currency = '',
    @JsonKey(name: 'currency_code') this.currencyCode = '',
    this.capital = '',
  });

  factory _$CountryImpl.fromJson(Map<String, dynamic> json) =>
      _$$CountryImplFromJson(json);

  @override
  final int id;
  @override
  final String name;
  @override
  @JsonKey()
  final String iso2;
  @override
  @JsonKey()
  final String iso3;
  @override
  @JsonKey(name: 'calling_code')
  final String callingCode;
  @override
  @JsonKey()
  final String currency;
  @override
  @JsonKey(name: 'currency_code')
  final String currencyCode;
  @override
  @JsonKey()
  final String capital;

  @override
  String toString() {
    return 'Country(id: $id, name: $name, iso2: $iso2, iso3: $iso3, callingCode: $callingCode, currency: $currency, currencyCode: $currencyCode, capital: $capital)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$CountryImpl &&
            (identical(other.id, id) || other.id == id) &&
            (identical(other.name, name) || other.name == name) &&
            (identical(other.iso2, iso2) || other.iso2 == iso2) &&
            (identical(other.iso3, iso3) || other.iso3 == iso3) &&
            (identical(other.callingCode, callingCode) ||
                other.callingCode == callingCode) &&
            (identical(other.currency, currency) ||
                other.currency == currency) &&
            (identical(other.currencyCode, currencyCode) ||
                other.currencyCode == currencyCode) &&
            (identical(other.capital, capital) || other.capital == capital));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
    runtimeType,
    id,
    name,
    iso2,
    iso3,
    callingCode,
    currency,
    currencyCode,
    capital,
  );

  /// Create a copy of Country
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$CountryImplCopyWith<_$CountryImpl> get copyWith =>
      __$$CountryImplCopyWithImpl<_$CountryImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$CountryImplToJson(this);
  }
}

abstract class _Country implements Country {
  const factory _Country({
    required final int id,
    required final String name,
    final String iso2,
    final String iso3,
    @JsonKey(name: 'calling_code') final String callingCode,
    final String currency,
    @JsonKey(name: 'currency_code') final String currencyCode,
    final String capital,
  }) = _$CountryImpl;

  factory _Country.fromJson(Map<String, dynamic> json) = _$CountryImpl.fromJson;

  @override
  int get id;
  @override
  String get name;
  @override
  String get iso2;
  @override
  String get iso3;
  @override
  @JsonKey(name: 'calling_code')
  String get callingCode;
  @override
  String get currency;
  @override
  @JsonKey(name: 'currency_code')
  String get currencyCode;
  @override
  String get capital;

  /// Create a copy of Country
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$CountryImplCopyWith<_$CountryImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

StateModel _$StateModelFromJson(Map<String, dynamic> json) {
  return _StateModel.fromJson(json);
}

/// @nodoc
mixin _$StateModel {
  int get id => throw _privateConstructorUsedError;
  @JsonKey(name: 'country_id')
  int get countryId => throw _privateConstructorUsedError;
  String get name => throw _privateConstructorUsedError;
  String get code => throw _privateConstructorUsedError;
  @JsonKey(name: 'adm1_code')
  String get adm1Code => throw _privateConstructorUsedError;

  /// Serializes this StateModel to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of StateModel
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $StateModelCopyWith<StateModel> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $StateModelCopyWith<$Res> {
  factory $StateModelCopyWith(
    StateModel value,
    $Res Function(StateModel) then,
  ) = _$StateModelCopyWithImpl<$Res, StateModel>;
  @useResult
  $Res call({
    int id,
    @JsonKey(name: 'country_id') int countryId,
    String name,
    String code,
    @JsonKey(name: 'adm1_code') String adm1Code,
  });
}

/// @nodoc
class _$StateModelCopyWithImpl<$Res, $Val extends StateModel>
    implements $StateModelCopyWith<$Res> {
  _$StateModelCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of StateModel
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? countryId = null,
    Object? name = null,
    Object? code = null,
    Object? adm1Code = null,
  }) {
    return _then(
      _value.copyWith(
            id: null == id
                ? _value.id
                : id // ignore: cast_nullable_to_non_nullable
                      as int,
            countryId: null == countryId
                ? _value.countryId
                : countryId // ignore: cast_nullable_to_non_nullable
                      as int,
            name: null == name
                ? _value.name
                : name // ignore: cast_nullable_to_non_nullable
                      as String,
            code: null == code
                ? _value.code
                : code // ignore: cast_nullable_to_non_nullable
                      as String,
            adm1Code: null == adm1Code
                ? _value.adm1Code
                : adm1Code // ignore: cast_nullable_to_non_nullable
                      as String,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$StateModelImplCopyWith<$Res>
    implements $StateModelCopyWith<$Res> {
  factory _$$StateModelImplCopyWith(
    _$StateModelImpl value,
    $Res Function(_$StateModelImpl) then,
  ) = __$$StateModelImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({
    int id,
    @JsonKey(name: 'country_id') int countryId,
    String name,
    String code,
    @JsonKey(name: 'adm1_code') String adm1Code,
  });
}

/// @nodoc
class __$$StateModelImplCopyWithImpl<$Res>
    extends _$StateModelCopyWithImpl<$Res, _$StateModelImpl>
    implements _$$StateModelImplCopyWith<$Res> {
  __$$StateModelImplCopyWithImpl(
    _$StateModelImpl _value,
    $Res Function(_$StateModelImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of StateModel
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? countryId = null,
    Object? name = null,
    Object? code = null,
    Object? adm1Code = null,
  }) {
    return _then(
      _$StateModelImpl(
        id: null == id
            ? _value.id
            : id // ignore: cast_nullable_to_non_nullable
                  as int,
        countryId: null == countryId
            ? _value.countryId
            : countryId // ignore: cast_nullable_to_non_nullable
                  as int,
        name: null == name
            ? _value.name
            : name // ignore: cast_nullable_to_non_nullable
                  as String,
        code: null == code
            ? _value.code
            : code // ignore: cast_nullable_to_non_nullable
                  as String,
        adm1Code: null == adm1Code
            ? _value.adm1Code
            : adm1Code // ignore: cast_nullable_to_non_nullable
                  as String,
      ),
    );
  }
}

/// @nodoc
@JsonSerializable()
class _$StateModelImpl implements _StateModel {
  const _$StateModelImpl({
    required this.id,
    @JsonKey(name: 'country_id') required this.countryId,
    required this.name,
    this.code = '',
    @JsonKey(name: 'adm1_code') this.adm1Code = '',
  });

  factory _$StateModelImpl.fromJson(Map<String, dynamic> json) =>
      _$$StateModelImplFromJson(json);

  @override
  final int id;
  @override
  @JsonKey(name: 'country_id')
  final int countryId;
  @override
  final String name;
  @override
  @JsonKey()
  final String code;
  @override
  @JsonKey(name: 'adm1_code')
  final String adm1Code;

  @override
  String toString() {
    return 'StateModel(id: $id, countryId: $countryId, name: $name, code: $code, adm1Code: $adm1Code)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$StateModelImpl &&
            (identical(other.id, id) || other.id == id) &&
            (identical(other.countryId, countryId) ||
                other.countryId == countryId) &&
            (identical(other.name, name) || other.name == name) &&
            (identical(other.code, code) || other.code == code) &&
            (identical(other.adm1Code, adm1Code) ||
                other.adm1Code == adm1Code));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode =>
      Object.hash(runtimeType, id, countryId, name, code, adm1Code);

  /// Create a copy of StateModel
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$StateModelImplCopyWith<_$StateModelImpl> get copyWith =>
      __$$StateModelImplCopyWithImpl<_$StateModelImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$StateModelImplToJson(this);
  }
}

abstract class _StateModel implements StateModel {
  const factory _StateModel({
    required final int id,
    @JsonKey(name: 'country_id') required final int countryId,
    required final String name,
    final String code,
    @JsonKey(name: 'adm1_code') final String adm1Code,
  }) = _$StateModelImpl;

  factory _StateModel.fromJson(Map<String, dynamic> json) =
      _$StateModelImpl.fromJson;

  @override
  int get id;
  @override
  @JsonKey(name: 'country_id')
  int get countryId;
  @override
  String get name;
  @override
  String get code;
  @override
  @JsonKey(name: 'adm1_code')
  String get adm1Code;

  /// Create a copy of StateModel
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$StateModelImplCopyWith<_$StateModelImpl> get copyWith =>
      throw _privateConstructorUsedError;
}
