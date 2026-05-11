/// Dynamic route lookup service.
///
/// Populated on app initialization from `/api/routes/config`.
/// Provides path resolution by route key so screens never hardcode paths.
class RoutesHelperService {
  final Map<String, String> _routeMap = {};

  /// Loads route definitions from the backend response.
  void loadRoutes(Map<String, String> routes) {
    _routeMap
      ..clear()
      ..addAll(routes);
  }

  /// Returns the path for a given route key, or `null` if not found.
  String? getPath(String routeKey) => _routeMap[routeKey];

  /// Whether a route key exists in the loaded routes.
  bool hasRoute(String routeKey) => _routeMap.containsKey(routeKey);

  /// Returns all loaded route keys.
  List<String> get routeKeys => _routeMap.keys.toList();

  /// Clears all loaded routes (e.g., on logout).
  void clear() => _routeMap.clear();
}
