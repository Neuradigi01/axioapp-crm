import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:template_app/models/location.dart';
import 'package:template_app/providers/service_providers.dart';

/// Provides the cached list of all countries.
///
/// Fetches once and caches. Use `ref.invalidate(countriesProvider)` to refresh.
final countriesProvider = FutureProvider<List<Country>>((ref) async {
  final locationApi = ref.read(locationApiServiceProvider);
  final response = await locationApi.getCountries();

  if (!response.success || response.data == null) {
    return [];
  }

  final list = response.data as List;
  return list
      .map((item) => Country.fromJson(item as Map<String, dynamic>))
      .toList();
});

/// Provides the list of states for a given [countryId].
///
/// Uses `.family` so each country ID has its own cached state list.
final statesProvider = FutureProvider.family<List<StateModel>, int>(
  (ref, countryId) async {
    final locationApi = ref.read(locationApiServiceProvider);
    final response = await locationApi.getStates(countryId);

    if (!response.success || response.data == null) {
      return [];
    }

    final list = response.data as List;
    return list
        .map((item) => StateModel.fromJson(item as Map<String, dynamic>))
        .toList();
  },
);
