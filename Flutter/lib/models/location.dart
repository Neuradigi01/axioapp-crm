import 'package:freezed_annotation/freezed_annotation.dart';

part 'location.freezed.dart';
part 'location.g.dart';

@freezed
class Country with _$Country {
  const factory Country({
    required int id,
    required String name,
    @Default('') String iso2,
    @Default('') String iso3,
    @JsonKey(name: 'calling_code') @Default('') String callingCode,
    @Default('') String currency,
    @JsonKey(name: 'currency_code') @Default('') String currencyCode,
    @Default('') String capital,
  }) = _Country;

  factory Country.fromJson(Map<String, dynamic> json) =>
      _$CountryFromJson(json);
}

@freezed
class StateModel with _$StateModel {
  const factory StateModel({
    required int id,
    @JsonKey(name: 'country_id') required int countryId,
    required String name,
    @Default('') String code,
    @JsonKey(name: 'adm1_code') @Default('') String adm1Code,
  }) = _StateModel;

  factory StateModel.fromJson(Map<String, dynamic> json) =>
      _$StateModelFromJson(json);
}
