import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/constants/messages.dart';
import '../../../core/theme/app_dimensions.dart';
import '../../../models/user_profile.dart';
import '../../../providers/location_provider.dart';
import '../../../providers/service_providers.dart';
import '../../../providers/user_provider.dart';
import '../../../schemas/user_schema.dart';
import '../../../shared/widgets/app_button.dart';
import '../../../shared/widgets/app_card.dart';
import '../../../shared/widgets/app_confirm_dialog.dart';
import '../../../shared/widgets/app_error_widget.dart';
import '../../../shared/widgets/app_loading_indicator.dart';
import '../../../shared/widgets/app_snackbar.dart';
import '../../../shared/widgets/app_text_field.dart';
import '../../../shared/widgets/country_state_picker.dart';
import '../../../utils/validators.dart';
import '../widgets/profile_image_widget.dart';

/// Profile view & edit screen with image upload/remove.
class ProfileScreen extends ConsumerStatefulWidget {
  const ProfileScreen({super.key});

  @override
  ConsumerState<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends ConsumerState<ProfileScreen> {
  final _formKey = GlobalKey<FormState>();

  final _firstNameController = TextEditingController();
  final _lastNameController = TextEditingController();
  final _emailController = TextEditingController();
  final _mobileController = TextEditingController();
  final _userIdController = TextEditingController();
  final _referralIdController = TextEditingController();
  final _joiningDateController = TextEditingController();

  CountryItem? _selectedCountry;
  StateItem? _selectedState;

  bool _isSaving = false;
  bool _isUploadingImage = false;
  bool _isFormPopulated = false;

  @override
  void dispose() {
    _firstNameController.dispose();
    _lastNameController.dispose();
    _emailController.dispose();
    _mobileController.dispose();
    _userIdController.dispose();
    _referralIdController.dispose();
    _joiningDateController.dispose();
    super.dispose();
  }

  /// Populates form fields from the loaded profile data.
  void _populateForm(UserProfile profile, List<CountryItem> countryItems) {
    _firstNameController.text = profile.firstName;
    _lastNameController.text = profile.lastName;
    _emailController.text = profile.email;
    _mobileController.text = profile.mobileNo ?? '';
    _userIdController.text = profile.userId;
    _referralIdController.text = profile.referralId ?? '';
    _joiningDateController.text = profile.joiningDate ?? '';

    // Pre-select country
    if (profile.countryId != null) {
      final match = countryItems.where((c) => c.id == profile.countryId);
      if (match.isNotEmpty) {
        _selectedCountry = match.first;
      }
    }

    _isFormPopulated = true;
  }

  /// Pre-select state after states load for the user's country.
  void _tryPopulateState(UserProfile profile, List<StateItem> stateItems) {
    if (profile.stateId != null && _selectedState == null) {
      final match = stateItems.where((s) => s.id == profile.stateId);
      if (match.isNotEmpty) {
        _selectedState = match.first;
      }
    }
  }

  void _onCountryChanged(CountryItem? country) {
    setState(() {
      _selectedCountry = country;
      _selectedState = null;
    });
  }

  void _onStateChanged(StateItem? state) {
    setState(() => _selectedState = state);
  }

  // ── Save Profile ──────────────────────────────────────────────────────────

  Future<void> _onSave() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() => _isSaving = true);

    try {
      final userApi = ref.read(userApiServiceProvider);
      final request = ProfileUpdateRequest(
        firstName: _firstNameController.text.trim(),
        lastName: _lastNameController.text.trim(),
        email: _emailController.text.trim(),
        mobileNo: _mobileController.text.trim().isNotEmpty
            ? _mobileController.text.trim()
            : null,
        countryId: _selectedCountry?.id,
        stateId: _selectedState?.id,
      );

      final response = await userApi.updateProfile(request);

      if (!mounted) return;

      if (response.success) {
        ref.invalidate(userProfileProvider);
        AppSnackbar.show(
          context,
          message: Messages.profileUpdated,
          type: SnackbarType.success,
        );
      } else {
        AppSnackbar.show(
          context,
          message: response.message.isNotEmpty
              ? response.message
              : Messages.profileUpdateFailed,
          type: SnackbarType.error,
        );
      }
    } catch (_) {
      if (!mounted) return;
      AppSnackbar.show(
        context,
        message: Messages.errorGeneric,
        type: SnackbarType.error,
      );
    } finally {
      if (mounted) {
        setState(() => _isSaving = false);
      }
    }
  }

  // ── Profile Image ─────────────────────────────────────────────────────────

  Future<void> _onUploadImage(String filePath) async {
    setState(() => _isUploadingImage = true);

    try {
      final userApi = ref.read(userApiServiceProvider);
      final response = await userApi.uploadProfileImage(filePath);

      if (!mounted) return;

      if (response.success) {
        ref.invalidate(userProfileProvider);
        AppSnackbar.show(
          context,
          message: Messages.profileImageUpdated,
          type: SnackbarType.success,
        );
      } else {
        AppSnackbar.show(
          context,
          message: response.message.isNotEmpty
              ? response.message
              : Messages.profileUpdateFailed,
          type: SnackbarType.error,
        );
      }
    } catch (_) {
      if (!mounted) return;
      AppSnackbar.show(
        context,
        message: Messages.errorGeneric,
        type: SnackbarType.error,
      );
    } finally {
      if (mounted) {
        setState(() => _isUploadingImage = false);
      }
    }
  }

  Future<void> _onRemoveImage() async {
    final confirmed = await AppConfirmDialog.show(
      context,
      title: 'Remove Photo',
      message: 'Are you sure you want to remove your profile photo?',
      confirmLabel: 'Remove',
      isDestructive: true,
    );

    if (!confirmed || !mounted) return;

    setState(() => _isUploadingImage = true);

    try {
      final userApi = ref.read(userApiServiceProvider);
      final response = await userApi.removeProfileImage();

      if (!mounted) return;

      if (response.success) {
        ref.invalidate(userProfileProvider);
        AppSnackbar.show(
          context,
          message: Messages.profileImageRemoved,
          type: SnackbarType.success,
        );
      } else {
        AppSnackbar.show(
          context,
          message: response.message.isNotEmpty
              ? response.message
              : Messages.profileUpdateFailed,
          type: SnackbarType.error,
        );
      }
    } catch (_) {
      if (!mounted) return;
      AppSnackbar.show(
        context,
        message: Messages.errorGeneric,
        type: SnackbarType.error,
      );
    } finally {
      if (mounted) {
        setState(() => _isUploadingImage = false);
      }
    }
  }

  // ── Build ─────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final profileAsync = ref.watch(userProfileProvider);
    final countriesAsync = ref.watch(countriesProvider);

    return profileAsync.when(
      loading: () =>
          const AppLoadingIndicator(message: 'Loading profile...'),
      error: (error, _) => AppErrorWidget(
        message: 'Failed to load profile.',
        onRetry: () => ref.invalidate(userProfileProvider),
      ),
      data: (profile) {
        if (profile == null) {
          return AppErrorWidget(
            message: 'Failed to load profile.',
            onRetry: () => ref.invalidate(userProfileProvider),
          );
        }

        // Map countries to picker items
        final countryItems = countriesAsync.maybeWhen(
          data: (countries) => countries
              .map((c) => CountryItem(id: c.id, name: c.name))
              .toList(),
          orElse: () => <CountryItem>[],
        );
        final isLoadingCountries = countriesAsync.isLoading;

        // Populate form once when data first arrives
        if (!_isFormPopulated && countryItems.isNotEmpty) {
          _populateForm(profile, countryItems);
        } else if (!_isFormPopulated && !isLoadingCountries) {
          // Countries failed to load — populate without country
          _populateForm(profile, countryItems);
        }

        // States for selected country
        final statesAsync = _selectedCountry != null
            ? ref.watch(statesProvider(_selectedCountry!.id))
            : null;

        final stateItems = statesAsync?.maybeWhen(
              data: (states) => states
                  .map((s) => StateItem(id: s.id, name: s.name))
                  .toList(),
              orElse: () => <StateItem>[],
            ) ??
            <StateItem>[];
        final isLoadingStates = statesAsync?.isLoading ?? false;

        // Pre-select state when states finish loading
        if (stateItems.isNotEmpty) {
          _tryPopulateState(profile, stateItems);
        }

        return _buildForm(
          profile: profile,
          countryItems: countryItems,
          stateItems: stateItems,
          isLoadingCountries: isLoadingCountries,
          isLoadingStates: isLoadingStates,
        );
      },
    );
  }

  Widget _buildForm({
    required UserProfile profile,
    required List<CountryItem> countryItems,
    required List<StateItem> stateItems,
    required bool isLoadingCountries,
    required bool isLoadingStates,
  }) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(AppDimensions.md),
      child: Center(
        child: ConstrainedBox(
          constraints:
              const BoxConstraints(maxWidth: AppDimensions.formMaxWidth),
          child: AppCard(
            title: 'My Profile',
            child: Form(
              key: _formKey,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  // Profile image
                  ProfileImageWidget(
                    firstName: profile.firstName,
                    lastName: profile.lastName,
                    profileImage: profile.profileImage,
                    isUploading: _isUploadingImage,
                    onUpload: _onUploadImage,
                    onRemove: _onRemoveImage,
                  ),
                  const SizedBox(height: AppDimensions.lg),

                  // User ID (read-only)
                  AppTextField(
                    controller: _userIdController,
                    label: 'User ID',
                    prefixIcon: Icons.badge_outlined,
                    enabled: false,
                  ),
                  const SizedBox(height: AppDimensions.md),

                  // First Name
                  AppTextField(
                    controller: _firstNameController,
                    label: 'First Name',
                    prefixIcon: Icons.person_outline,
                    validator: Validators.required,
                    textInputAction: TextInputAction.next,
                  ),
                  const SizedBox(height: AppDimensions.md),

                  // Last Name
                  AppTextField(
                    controller: _lastNameController,
                    label: 'Last Name',
                    prefixIcon: Icons.person_outline,
                    validator: Validators.required,
                    textInputAction: TextInputAction.next,
                  ),
                  const SizedBox(height: AppDimensions.md),

                  // Email
                  AppTextField(
                    controller: _emailController,
                    label: 'Email',
                    prefixIcon: Icons.email_outlined,
                    validator: Validators.email,
                    keyboardType: TextInputType.emailAddress,
                    textInputAction: TextInputAction.next,
                  ),
                  const SizedBox(height: AppDimensions.md),

                  // Mobile
                  AppTextField(
                    controller: _mobileController,
                    label: 'Mobile Number',
                    prefixIcon: Icons.phone_outlined,
                    keyboardType: TextInputType.phone,
                    textInputAction: TextInputAction.next,
                  ),
                  const SizedBox(height: AppDimensions.md),

                  // Country & State picker
                  CountryStatePicker(
                    countries: countryItems,
                    states: stateItems,
                    selectedCountry: _selectedCountry,
                    selectedState: _selectedState,
                    onCountryChanged: _onCountryChanged,
                    onStateChanged: _onStateChanged,
                    isLoadingCountries: isLoadingCountries,
                    isLoadingStates: isLoadingStates,
                  ),
                  const SizedBox(height: AppDimensions.md),

                  // Referral ID (read-only)
                  AppTextField(
                    controller: _referralIdController,
                    label: 'Referral ID',
                    prefixIcon: Icons.card_giftcard_outlined,
                    enabled: false,
                  ),
                  const SizedBox(height: AppDimensions.md),

                  // Joining Date (read-only)
                  AppTextField(
                    controller: _joiningDateController,
                    label: 'Joining Date',
                    prefixIcon: Icons.calendar_today_outlined,
                    enabled: false,
                  ),
                  const SizedBox(height: AppDimensions.lg),

                  // Save button
                  AppButton(
                    label: 'Save Changes',
                    onPressed: _isSaving ? null : _onSave,
                    isLoading: _isSaving,
                    icon: Icons.save_outlined,
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
