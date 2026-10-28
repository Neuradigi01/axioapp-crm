import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../../core/constants/messages.dart';
import '../../core/theme/app_dimensions.dart';

/// File picker button with selected file list and remove capability.
///
/// Opens the platform file picker, validates size, and reports changes
/// via [onFilesChanged]. Shows selected files with remove buttons.
class AppFileUpload extends StatefulWidget {
  const AppFileUpload({
    super.key,
    required this.onFilesChanged,
    this.maxFiles = 5,
    this.maxFileSizeMB = 10,
    this.allowedExtensions,
    this.label = 'Attach Files',
  });

  final ValueChanged<List<PlatformFile>> onFilesChanged;
  final int maxFiles;
  final int maxFileSizeMB;
  final List<String>? allowedExtensions;
  final String label;

  @override
  State<AppFileUpload> createState() => _AppFileUploadState();
}

class _AppFileUploadState extends State<AppFileUpload> {
  final List<PlatformFile> _selectedFiles = [];

  int get _maxSizeBytes => widget.maxFileSizeMB * 1024 * 1024;

  Future<void> _pickFiles() async {
    if (_selectedFiles.length >= widget.maxFiles) {
      _showSnackBar(Messages.fileMaxCount);
      return;
    }

    final result = await FilePicker.platform.pickFiles(
      allowMultiple: true,
      type: widget.allowedExtensions != null ? FileType.custom : FileType.any,
      allowedExtensions: widget.allowedExtensions,
    );

    if (result == null || result.files.isEmpty) return;

    final remainingSlots = widget.maxFiles - _selectedFiles.length;
    final filesToAdd = result.files.take(remainingSlots);

    final List<PlatformFile> validFiles = [];
    for (final file in filesToAdd) {
      if ((file.size) > _maxSizeBytes) {
        if (mounted) {
          _showSnackBar(
            '${file.name}: ${Messages.fileTooLarge} (max ${widget.maxFileSizeMB}MB)',
          );
        }
        continue;
      }
      validFiles.add(file);
    }

    if (validFiles.isNotEmpty) {
      setState(() => _selectedFiles.addAll(validFiles));
      widget.onFilesChanged(List.unmodifiable(_selectedFiles));
    }

    if (result.files.length > remainingSlots && mounted) {
      _showSnackBar(Messages.fileMaxCount);
    }
  }

  void _removeFile(int index) {
    setState(() => _selectedFiles.removeAt(index));
    widget.onFilesChanged(List.unmodifiable(_selectedFiles));
  }

  void _showSnackBar(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  String _formatFileSize(int bytes) {
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        OutlinedButton.icon(
          onPressed: _selectedFiles.length >= widget.maxFiles ? null : _pickFiles,
          icon: const Icon(Icons.attach_file, size: AppDimensions.iconSize),
          label: Text(
            '${widget.label} (${_selectedFiles.length}/${widget.maxFiles})',
          ),
        ),
        if (_selectedFiles.isNotEmpty) ...[
          const SizedBox(height: AppDimensions.sm),
          ...List.generate(_selectedFiles.length, (index) {
            final file = _selectedFiles[index];
            return Padding(
              padding: const EdgeInsets.only(bottom: AppDimensions.xs),
              child: Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: AppDimensions.sm,
                  vertical: AppDimensions.xs,
                ),
                decoration: BoxDecoration(
                  color: colorScheme.surfaceContainerLow,
                  borderRadius: BorderRadius.circular(AppDimensions.radiusSm),
                  border: Border.all(color: colorScheme.outlineVariant),
                ),
                child: Row(
                  children: [
                    Icon(
                      Icons.insert_drive_file_outlined,
                      size: 20,
                      color: colorScheme.onSurfaceVariant,
                    ),
                    const SizedBox(width: AppDimensions.sm),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            file.name,
                            style: theme.textTheme.bodyMedium,
                            overflow: TextOverflow.ellipsis,
                            maxLines: 1,
                          ),
                          Text(
                            _formatFileSize(file.size),
                            style: theme.textTheme.bodySmall?.copyWith(
                              color: colorScheme.onSurfaceVariant,
                            ),
                          ),
                        ],
                      ),
                    ),
                    IconButton(
                      onPressed: () => _removeFile(index),
                      icon: Icon(
                        Icons.close,
                        size: 18,
                        color: colorScheme.error,
                      ),
                      constraints: const BoxConstraints(
                        minWidth: 32,
                        minHeight: 32,
                      ),
                      padding: EdgeInsets.zero,
                      tooltip: 'Remove',
                    ),
                  ],
                ),
              ),
            );
          }),
        ],
      ],
    );
  }
}
