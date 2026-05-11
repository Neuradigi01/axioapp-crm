import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/theme/app_dimensions.dart';

/// Represents an attachment with name, size, and download URL.
class AttachmentItem {
  const AttachmentItem({
    required this.name,
    required this.url,
    this.sizeBytes,
  });

  final String name;
  final String url;
  final int? sizeBytes;
}

/// Displays a list of attachments with name, size, and download action.
///
/// Each item shows a file icon, the file name and size, and a download
/// button that opens the file URL in the system browser/viewer.
class AppAttachmentList extends StatelessWidget {
  const AppAttachmentList({
    super.key,
    required this.attachments,
  });

  final List<AttachmentItem> attachments;

  String _formatFileSize(int bytes) {
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }

  Future<void> _openAttachment(String url) async {
    final uri = Uri.parse(url);
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (attachments.isEmpty) return const SizedBox.shrink();

    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          'Attachments (${attachments.length})',
          style: theme.textTheme.titleSmall,
        ),
        const SizedBox(height: AppDimensions.sm),
        ...attachments.map((attachment) {
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
                          attachment.name,
                          style: theme.textTheme.bodyMedium,
                          overflow: TextOverflow.ellipsis,
                          maxLines: 1,
                        ),
                        if (attachment.sizeBytes != null)
                          Text(
                            _formatFileSize(attachment.sizeBytes!),
                            style: theme.textTheme.bodySmall?.copyWith(
                              color: colorScheme.onSurfaceVariant,
                            ),
                          ),
                      ],
                    ),
                  ),
                  IconButton(
                    onPressed: () => _openAttachment(attachment.url),
                    icon: Icon(
                      Icons.download,
                      size: 20,
                      color: colorScheme.primary,
                    ),
                    constraints: const BoxConstraints(
                      minWidth: 32,
                      minHeight: 32,
                    ),
                    padding: EdgeInsets.zero,
                    tooltip: 'Download',
                  ),
                ],
              ),
            ),
          );
        }),
      ],
    );
  }
}
