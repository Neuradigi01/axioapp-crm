// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'login_history_schema.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$LoginHistoryListRequestImpl _$$LoginHistoryListRequestImplFromJson(
  Map<String, dynamic> json,
) => _$LoginHistoryListRequestImpl(
  pageIndex: (json['page_index'] as num?)?.toInt() ?? 1,
  pageSize: (json['page_size'] as num?)?.toInt() ?? 10,
);

Map<String, dynamic> _$$LoginHistoryListRequestImplToJson(
  _$LoginHistoryListRequestImpl instance,
) => <String, dynamic>{
  'page_index': instance.pageIndex,
  'page_size': instance.pageSize,
};

_$LogoutSessionRequestImpl _$$LogoutSessionRequestImplFromJson(
  Map<String, dynamic> json,
) => _$LogoutSessionRequestImpl(tokenId: (json['token_id'] as num).toInt());

Map<String, dynamic> _$$LogoutSessionRequestImplToJson(
  _$LogoutSessionRequestImpl instance,
) => <String, dynamic>{'token_id': instance.tokenId};
