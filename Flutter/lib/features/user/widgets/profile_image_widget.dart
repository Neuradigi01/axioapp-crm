import 'package:cached_network_image/cached_network_image.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../../../core/config/app_config.dart';
import '../../../core/theme/app_dimensions.dart';

/// Large circle avatar with camera overlay for uploading/removing profile image.
class ProfileImageWidget extends StatelessWidget {
  const ProfileImageWidget({
    super.key,
    required this.firstName,
    required this.lastName,
    this.profileImage,
    required this.isUploading,
    required this.onUpload,
    required this.onRemove,
  });

  final String firstName;
  final String lastName;
  final String? profileImage;
  final bool isUploading;
  final ValueChanged<String> onUpload;
  final VoidCallback onRemove;

  String get _initials {
    final first = firstName.isNotEmpty ? firstName[0] : '';
    final last = lastName.isNotEmpty ? lastName[0] : '';
    return '$first$last'.toUpperCase();
  }

  bool get _hasImage =>
      profileImage != null && profileImage!.isNotEmpty;

  Future<void> _showOptions(BuildContext context) async {
    final result = await showModalBottomSheet<String>(
      context: context,
      builder: (ctx) {
        final theme = Theme.of(ctx);
        return SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ListTile(
                leading: const Icon(Icons.photo_camera_outlined),
                title: const Text('Upload Photo'),
                onTap: () => Navigator.of(ctx).pop('upload'),
              ),
              if (_hasImage)
                ListTile(
                  leading: Icon(
                    Icons.delete_outline,
                    color: theme.colorScheme.error,
                  ),
                  title: Text(
                    'Remove Photo',
                    style: TextStyle(color: theme.colorScheme.error),
                  ),
                  onTap: () => Navigator.of(ctx).pop('remove'),
                ),
            ],
          ),
        );
      },
    );

    if (result == 'upload') {
      await _pickAndUpload();
    } else if (result == 'remove') {
      onRemove();
    }
  }

  Future<void> _pickAndUpload() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.image,
      allowMultiple: false,
    );

    if (result != null && result.files.single.path != null) {
      onUpload(result.files.single.path!);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Center(
      child: Stack(
        children: [
          // Avatar
          CircleAvatar(
            radius: AppDimensions.avatarSizeXl / 2,
            backgroundColor: theme.colorScheme.primaryContainer,
            child: isUploading
                ? CircularProgressIndicator(
                    strokeWidth: 3,
                    color: theme.colorScheme.primary,
                  )
                : _buildAvatarContent(theme),
          ),

          // Camera button overlay
          Positioned(
            bottom: 0,
            right: 0,
            child: Material(
              elevation: AppDimensions.elevationMedium,
              shape: const CircleBorder(),
              color: theme.colorScheme.primary,
              child: InkWell(
                customBorder: const CircleBorder(),
                onTap: isUploading ? null : () => _showOptions(context),
                child: Padding(
                  padding: const EdgeInsets.all(AppDimensions.sm),
                  child: Icon(
                    Icons.camera_alt_outlined,
                    size: 20,
                    color: theme.colorScheme.onPrimary,
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAvatarContent(ThemeData theme) {
    if (_hasImage) {
      final imageUrl = '${AppConfig.apiBaseUrl}${profileImage!}';
      return ClipOval(
        child: CachedNetworkImage(
          imageUrl: imageUrl,
          width: AppDimensions.avatarSizeXl,
          height: AppDimensions.avatarSizeXl,
          fit: BoxFit.cover,
          placeholder: (_, __) => _buildInitials(theme),
          errorWidget: (_, __, ___) => _buildInitials(theme),
        ),
      );
    }

    return _buildInitials(theme);
  }

  Widget _buildInitials(ThemeData theme) {
    return Container(
      width: AppDimensions.avatarSizeXl,
      height: AppDimensions.avatarSizeXl,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: theme.colorScheme.primary,
        shape: BoxShape.circle,
      ),
      child: Text(
        _initials,
        style: theme.textTheme.headlineMedium?.copyWith(
          color: theme.colorScheme.onPrimary,
          fontWeight: FontWeight.bold,
        ),
      ),
    );
  }
}
