import 'package:template_app/core/constants/api_endpoints.dart';
import 'package:template_app/core/network/api_helper.dart';
import 'package:template_app/core/network/api_response.dart';

/// API service for location endpoints (countries, states).
class LocationApiService {
  LocationApiService(this._apiHelper);
  final ApiHelper _apiHelper;

  /// Fetches the list of all active countries.
  Future<ApiResponse> getCountries() async {
    return _apiHelper.get(ApiEndpoints.countries);
  }

  /// Fetches the list of states for a given country.
  Future<ApiResponse> getStates(int countryId) async {
    return _apiHelper.get(ApiEndpoints.states(countryId));
  }
}
