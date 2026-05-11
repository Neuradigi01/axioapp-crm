# Flutter App — Coding Standards

Standards for writing, organizing, reviewing, and shipping Dart/Flutter code in this project.

---

## Tech Overview

| Area | Technology |
|------|-----------|
| Framework | Flutter 3.x (latest stable) |
| Language | Dart 3.x with null safety |
| State Management | Riverpod (flutter_riverpod) |
| Routing | GoRouter (go_router) |
| HTTP Client | Dio with interceptors |
| Models | freezed + json_serializable |
| Secure Storage | flutter_secure_storage |
| Preferences | shared_preferences |
| Push Notifications | firebase_messaging + flutter_local_notifications |
| Theming | Material 3 with custom ColorScheme |
| Image Loading | cached_network_image |
| File Picking | file_picker |

## Guiding Principles

1. **Readability over cleverness** — simple, clear code wins
2. **Strict typing** — no `dynamic`, no `Object` unless unavoidable
3. **Immutability** — prefer `final`, `const`, freezed models
4. **Thin screens** — UI logic only; business logic in providers
5. **Composition over inheritance** — small widgets composed together
6. **Fail fast** — validate early, handle errors centrally
7. **Consistency** — follow existing patterns, never invent new ones

---

## Dart Language Standards

### Null Safety
```dart
// GOOD — explicit nullability
String? userName;
final String email; // non-nullable, must be initialized

// BAD — never disable null safety or use dynamic
dynamic data; // FORBIDDEN
```

### Type Annotations
```dart
// GOOD — explicit types for public APIs
String getUserName(int userId) { ... }
List<UserProfile> get profiles => _profiles;

// OK — type inference for local variables when type is obvious
final user = await userApiService.getProfile();
final items = <String>[];

// BAD — no type, ambiguous
var x = getData(); // What type is this?
```

### Collections
```dart
// GOOD — typed, immutable where possible
final List<String> items = [];
final Map<String, int> counts = {};
const List<String> roles = ['Admin', 'User'];

// Use collection-if, collection-for
final widgets = [
  const Header(),
  if (isLoggedIn) const UserMenu(),
  for (final item in items) ItemWidget(item: item),
];
```

### Enums
```dart
// GOOD — enhanced enums with values
enum TicketStatus {
  open('Open'),
  inProgress('In Progress'),
  resolved('Resolved'),
  closed('Closed');

  const TicketStatus(this.label);
  final String label;
}

enum UserRole {
  user('User'),
  admin('Admin');

  const UserRole(this.value);
  final String value;
}
```

### Extensions
```dart
// Place in lib/shared/extensions/
extension StringExtension on String {
  String get masked => replaceRange(2, length - 2, '***');
}

extension DateTimeExtension on DateTime {
  String get formatted => '${day.toString().padLeft(2, '0')}/${month.toString().padLeft(2, '0')}/$year';
}
```

---

## File Organization Rules

### Feature-First Structure
```
lib/features/auth/
├── screens/
│   ├── login_screen.dart
│   ├── register_screen.dart
│   └── forgot_password_screen.dart
└── widgets/
    ├── otp_input_widget.dart
    └── auth_card_widget.dart
```

### File Naming
| Type | Pattern | Example |
|------|---------|---------|
| Screens | `*_screen.dart` | `login_screen.dart` |
| Feature widgets | `*_widget.dart` | `otp_input_widget.dart` |
| Shared widgets | `*_widget.dart` | `app_button_widget.dart` |
| API services | `*_api_service.dart` | `auth_api_service.dart` |
| Core services | `*_service.dart` | `auth_service.dart`, `theme_service.dart` |
| Providers | `*_provider.dart` | `auth_provider.dart` |
| Models | `*.dart` | `user_profile.dart` |
| Schemas | `*_schema.dart` | `auth_schema.dart` |
| Constants | `*.dart` | `app_constants.dart`, `messages.dart` |
| Utils | `*.dart` | `validators.dart`, `formatters.dart` |
| Extensions | `*_extension.dart` | `string_extension.dart` |

### One Class Per File Rule
- Each public class gets its own file
- Exception: closely related small classes in same file (e.g., request + response DTOs in same schema file)
- Private helper classes can live in the same file as their public class

### Import Order (Enforced)
```dart
// 1. Dart SDK
import 'dart:async';
import 'dart:io';

// 2. Flutter SDK
import 'package:flutter/material.dart';

// 3. Third-party packages
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

// 4. Project imports (use package imports, not relative)
import 'package:app/core/constants/app_constants.dart';
import 'package:app/services/auth_api_service.dart';
import 'package:app/models/user_profile.dart';
```

**Rule:** Always use `package:app/...` imports, NEVER relative imports (`../`).

---

## Widget Standards

### Widget Declaration
```dart
// GOOD — ConsumerWidget for Riverpod integration
class LoginScreen extends ConsumerWidget {
  const LoginScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // ...
  }
}

// GOOD — ConsumerStatefulWidget when lifecycle needed
class RegisterScreen extends ConsumerStatefulWidget {
  const RegisterScreen({super.key});

  @override
  ConsumerState<RegisterScreen> createState() => _RegisterScreenState();
}
```

### Const Constructors
```dart
// GOOD — const wherever possible
const SizedBox(height: 16);
const Text('Hello');
const EdgeInsets.all(16);

// Widget with const constructor
class AppButton extends StatelessWidget {
  const AppButton({super.key, required this.label, required this.onPressed});
  
  final String label;
  final VoidCallback onPressed;
  // ...
}
```

### Widget Decomposition
```dart
// BAD — monster build method
@override
Widget build(BuildContext context, WidgetRef ref) {
  return Column(children: [
    // 200 lines of nested widgets...
  ]);
}

// GOOD — extract into private methods or separate widgets
@override
Widget build(BuildContext context, WidgetRef ref) {
  return Column(children: [
    _buildHeader(context),
    _buildForm(context, ref),
    _buildActions(context, ref),
  ]);
}

Widget _buildHeader(BuildContext context) {
  return // ...
}
```

**Rule:** If a `build` method exceeds ~80 lines, decompose it.

---

## State Management (Riverpod)

### Provider Types
```dart
// Simple state
final isLoadingProvider = StateProvider<bool>((ref) => false);

// Async data fetching
final userProfileProvider = FutureProvider.autoDispose<UserProfile>((ref) async {
  final apiService = ref.read(userApiServiceProvider);
  return apiService.getProfile();
});

// Complex state with notifier
final authProvider = StateNotifierProvider<AuthNotifier, AuthState>((ref) {
  return AuthNotifier(ref);
});

// Family — parameterized providers
final ticketDetailProvider = FutureProvider.autoDispose.family<TicketDetail, int>((ref, ticketId) async {
  final apiService = ref.read(ticketApiServiceProvider);
  return apiService.getTicket(ticketId);
});
```

### Provider Naming
```dart
// Pattern: <feature><Entity><Type>Provider
final authStateProvider = ...;          // Auth state
final userProfileProvider = ...;        // User profile data
final ticketListProvider = ...;         // Ticket list
final loginFormProvider = ...;          // Login form state
```

### Provider Location
- Feature-specific providers: `lib/providers/<feature>_provider.dart`
- Service providers (DI): `lib/providers/service_providers.dart`
- Keep related providers in same file

---

## HTTP / API Standards

### API Service Pattern
```dart
class AuthApiService {
  AuthApiService(this._apiHelper);
  final ApiHelper _apiHelper;

  Future<ApiResponse> login(LoginRequest request) {
    return _apiHelper.post('/auth/login', data: request.toJson());
  }

  Future<ApiResponse> getProfile() {
    return _apiHelper.get('/user/profile');
  }

  Future<ApiResponse> updateProfile(ProfileUpdateRequest request) {
    return _apiHelper.put('/user/profile', data: request.toJson());
  }
}
```

**Rules:**
- One API service per feature domain
- All calls go through `ApiHelper` (which wraps Dio)
- Return `ApiResponse` — let providers handle success/failure
- Never use Dio directly in screens or providers

### ApiResponse Handling
```dart
// In provider/notifier
final response = await authApiService.login(request);
if (response.success) {
  // Handle success
  final data = response.data;
} else {
  // Handle failure — show response.message
}
```

### Error Handling
- Global interceptor handles 401 (token expired → logout)
- Global interceptor handles 403 (forbidden)
- Global interceptor handles network errors
- Screen-level: only handle specific business errors
- **Never** wrap API calls in try-catch in screens — let the provider/interceptor handle it

---

## Form Standards

### Form Structure
```dart
class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _identifierController = TextEditingController();
  final _passwordController = TextEditingController();

  @override
  void dispose() {
    _identifierController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Form(
      key: _formKey,
      child: Column(children: [
        TextFormField(
          controller: _identifierController,
          validator: Validators.required,
          decoration: const InputDecoration(labelText: 'Username or Email'),
        ),
        // ...
      ]),
    );
  }

  void _handleSubmit() {
    if (!_formKey.currentState!.validate()) return;
    // Proceed with API call
  }
}
```

### Validators
```dart
// lib/utils/validators.dart — centralized
class Validators {
  static String? required(String? value) {
    if (value == null || value.trim().isEmpty) return 'This field is required';
    return null;
  }

  static String? email(String? value) {
    if (value == null || value.trim().isEmpty) return 'Email is required';
    if (!RegExp(r'^[^@]+@[^@]+\.[^@]+$').hasMatch(value)) return 'Invalid email';
    return null;
  }

  static String? minLength(int min) => (String? value) {
    if (value == null || value.length < min) return 'Minimum $min characters';
    return null;
  };

  static String? match(TextEditingController controller, String fieldName) => (String? value) {
    if (value != controller.text) return '$fieldName does not match';
    return null;
  };
}
```

---

## Navigation Standards

### Route Definition
```dart
// Use GoRouter with ShellRoute for layouts
GoRouter(
  routes: [
    // Auth routes — no shell
    GoRoute(path: '/login', builder: (_, __) => const LoginScreen()),
    
    // User routes — with shell (drawer + appbar)
    ShellRoute(
      builder: (_, __, child) => UserLayout(child: child),
      routes: [
        GoRoute(path: '/dashboard', builder: (_, __) => const DashboardScreen()),
        GoRoute(path: '/profile', builder: (_, __) => const ProfileScreen()),
      ],
    ),
  ],
);
```

### Navigation
```dart
// GOOD — use GoRouter methods
context.go('/dashboard');           // Replace current route
context.push('/tickets/123');       // Push on stack
context.pop();                      // Go back

// GOOD — use named routes via RoutesHelper
context.go(RoutesHelper.getPath('user_dashboard'));

// BAD — never hardcode paths in screens
context.go('/user/dashboard');      // FORBIDDEN
```

---

## Error Handling Standards

### Global Error Handling
- Dio interceptor catches all HTTP errors
- `ApiHelper` wraps responses into `ApiResponse`
- Unhandled Flutter errors caught by `FlutterError.onError`
- Zone-level error catching in `main.dart`

### Screen-Level Error Display
```dart
// Use snackbar for transient errors
ScaffoldMessenger.of(context).showSnackBar(
  SnackBar(content: Text(response.message)),
);

// Use inline error for form-specific errors
if (!response.success) {
  setState(() => _errorMessage = response.message);
}
```

### Loading States
```dart
// In provider — use AsyncValue
final profileAsync = ref.watch(userProfileProvider);

profileAsync.when(
  data: (profile) => ProfileView(profile: profile),
  loading: () => const Center(child: CircularProgressIndicator()),
  error: (error, stack) => ErrorWidget(message: error.toString()),
);
```

---

## Git Workflow

### Commit Messages
Follow conventional commits format:
```
feat: add login screen with 2FA support
fix: resolve token refresh race condition
refactor: extract OTP input into shared widget
style: update login card proportions
```

### Branch Naming
```
feature/flutter-auth-login
feature/flutter-user-dashboard
fix/flutter-token-refresh
```

---

## Code Review Checklist

- [ ] No `dynamic` types
- [ ] No hardcoded strings (use constants/messages)
- [ ] No hardcoded colors (use theme)
- [ ] No hardcoded route paths (use RoutesHelper)
- [ ] No direct Dio/http calls (use API services)
- [ ] Const constructors used where possible
- [ ] Controllers disposed in `dispose()`
- [ ] Loading states handled (loading, error, data)
- [ ] Form validation in place
- [ ] Riverpod providers for state (not setState for complex state)
- [ ] Package imports (not relative)
- [ ] Import order correct (dart → flutter → packages → project)
- [ ] Widget decomposition (no 200-line build methods)
- [ ] Accessibility: semantic labels on icons/images
- [ ] Responsive: works on different screen sizes
