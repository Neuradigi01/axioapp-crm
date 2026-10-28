// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'location.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$CountryImpl _$$CountryImplFromJson(Map<String, dynamic> json) =>
    _$CountryImpl(
      id: (json['id'] as num).toInt(),
      name: json['name'] as String,
      iso2: json['iso2'] as String? ?? '',
      iso3: json['iso3'] as String? ?? '',
      callingCode: json['calling_code'] as String? ?? '',
      currency: json['currency'] as String? ?? '',
      currencyCode: json['currency_code'] as String? ?? '',
      capital: json['capital'] as String? ?? '',
    );

Map<String, dynamic> _$$CountryImplToJson(_$CountryImpl instance) =>
    <String, dynamic>{
      'id': instance.id,
      'name': instance.name,
      'iso2': instance.iso2,
      'iso3': instance.iso3,
      'calling_code': instance.callingCode,
      'currency': instance.currency,
      'currency_code': instance.currencyCode,
      'capital': instance.capital,
    };

_$StateModelImpl _$$StateModelImplFromJson(Map<String, dynamic> json) =>
    _$StateModelImpl(
      id: (json['id'] as num).toInt(),
      countryId: (json['country_id'] as num).toInt(),
      name: json['name'] as String,
      code: json['code'] as String? ?? '',
      adm1Code: json['adm1_code'] as String? ?? '',
    );

Map<String, dynamic> _$$StateModelImplToJson(_$StateModelImpl instance) =>
    <String, dynamic>{
      'id': instance.id,
      'country_id': instance.countryId,
      'name': instance.name,
      'code': instance.code,
      'adm1_code': instance.adm1Code,
    };
