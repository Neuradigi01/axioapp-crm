import 'package:flutter/widgets.dart';

import 'package:template_app/core/constants/messages.dart';

/// Centralized form validators.
///
/// All validators return `null` on success and an error message on failure.
/// Use directly as [TextFormField.validator] or compose with other validators.
class Validators {
  Validators._();

  /// Validates that the field is not empty.
  static String? required(String? value) {
    if (value == null || value.trim().isEmpty) return Messages.fieldRequired;
    return null;
  }

  /// Validates email format.
  static String? email(String? value) {
    if (value == null || value.trim().isEmpty) return Messages.fieldRequired;
    if (!RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(value.trim())) {
      return Messages.invalidEmail;
    }
    return null;
  }

  /// Returns a validator that checks minimum length.
  static String? Function(String?) minLength(int min) {
    return (String? value) {
      if (value == null || value.trim().isEmpty) return Messages.fieldRequired;
      if (value.length < min) return 'Must be at least $min characters';
      return null;
    };
  }

  /// Returns a validator that checks if value matches a controller's text.
  static String? Function(String?) match(
    TextEditingController controller,
    String fieldName,
  ) {
    return (String? value) {
      if (value == null || value.trim().isEmpty) return Messages.fieldRequired;
      if (value != controller.text) return '$fieldName does not match';
      return null;
    };
  }

  /// Validates a mobile/phone number (digits, optional leading +, 7–15 digits).
  static String? mobile(String? value) {
    if (value == null || value.trim().isEmpty) return Messages.fieldRequired;
    final cleaned = value.trim().replaceAll(RegExp(r'[\s\-()]'), '');
    if (!RegExp(r'^\+?\d{7,15}$').hasMatch(cleaned)) {
      return Messages.invalidPhoneNumber;
    }
    return null;
  }

  /// Returns a validator that enforces password rules (min 8 chars).
  static String? password(String? value) {
    if (value == null || value.trim().isEmpty) return Messages.fieldRequired;
    if (value.length < 8) return Messages.passwordTooShort;
    return null;
  }

  /// Returns a validator that checks password confirmation matches.
  static String? Function(String?) confirmPassword(
    TextEditingController passwordController,
  ) {
    return (String? value) {
      if (value == null || value.trim().isEmpty) return Messages.fieldRequired;
      if (value != passwordController.text) {
        return Messages.passwordsDoNotMatch;
      }
      return null;
    };
  }
}
