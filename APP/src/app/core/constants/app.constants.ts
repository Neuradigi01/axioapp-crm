// ── Roles ────────────────────────────────────────────────────────────

export const ROLE_USER = 'User';
export const ROLE_ADMIN = 'Admin';

// ── Theme ────────────────────────────────────────────────────────────

export const THEME_LIGHT = 'light';
export const THEME_DARK = 'dark';

// ── Local storage keys ──────────────────────────────────────────────

export const STORAGE_KEY_TOKEN = 'auth_token';
export const STORAGE_KEY_THEME = 'app_theme';
export const STORAGE_KEY_ADMIN_IMPERSONATION = 'impersonating_admin_token';
export const STORAGE_KEY_FCM_TOKEN = 'fcm_token';

// ── Snackbar defaults ───────────────────────────────────────────────

export const SNACKBAR_DURATION = 4000;
export const SNACKBAR_DURATION_LONG = 6000;
export const SNACKBAR_ACTION = 'Close';

// ── Two-factor constants ────────────────────────────────────────────

export const TFA_METHOD_LABELS: Record<string, string> = {
  authenticator: 'Authenticator App',
  email: 'Email OTP',
  sms: 'SMS OTP',
};

export const TFA_METHOD_ICONS: Record<string, string> = {
  authenticator: 'security',
  email: 'email',
  sms: 'sms',
};

export const OTP_EXPIRY_SECONDS = 300;
export const RESEND_COOLDOWN_SECONDS = 30;

// ── Action verification ─────────────────────────────────────────────

export const ACTION_TOKEN_HEADER = 'X-Action-Token';
export const ACTION_2FA_ERROR_CODE = '2FA_REQUIRED';

// ── File upload defaults ────────────────────────────────────────────

export const FILE_UPLOAD_MAX_FILES = 5;
export const FILE_UPLOAD_MAX_SIZE_BYTES = 10 * 1024 * 1024; // 10 MB
export const FILE_UPLOAD_ALLOWED_EXTENSIONS = [
  'jpg',
  'jpeg',
  'png',
  'gif',
  'bmp',
  'webp',
  'pdf',
  'doc',
  'docx',
  'xls',
  'xlsx',
  'csv',
  'txt',
  'rtf',
  'zip',
  'rar',
];

export const FILE_TYPE_ICONS: Record<string, string> = {
  image: 'image',
  pdf: 'picture_as_pdf',
  doc: 'description',
  xls: 'table_chart',
  zip: 'folder_zip',
  text: 'article',
  default: 'insert_drive_file',
};

// ── Ticket status options ───────────────────────────────────────────

export const TICKET_STATUS_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'Open', label: 'Open' },
  { value: 'In Progress', label: 'In Progress' },
  { value: 'Resolved', label: 'Resolved' },
  { value: 'Closed', label: 'Closed' },
];

export const TICKET_PRIORITY_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'Low', label: 'Low' },
  { value: 'Normal', label: 'Normal' },
  { value: 'High', label: 'High' },
  { value: 'Urgent', label: 'Urgent' },
];

// ── Status badge mapping ────────────────────────────────────────────

import { IBadgeConfig } from '@app/schemas/common';

export const BADGE_MAP: Record<string, IBadgeConfig> = {
  active: { color: 'var(--badge-active-color)', bgVar: 'var(--badge-active-bg)' },
  inactive: { color: 'var(--badge-inactive-color)', bgVar: 'var(--badge-inactive-bg)' },
  open: { color: 'var(--badge-open-color)', bgVar: 'var(--badge-open-bg)' },
  'in progress': { color: 'var(--badge-in-progress-color)', bgVar: 'var(--badge-in-progress-bg)' },
  resolved: { color: 'var(--badge-resolved-color)', bgVar: 'var(--badge-resolved-bg)' },
  closed: { color: 'var(--badge-closed-color)', bgVar: 'var(--badge-closed-bg)' },
  subscribed: { color: 'var(--badge-active-color)', bgVar: 'var(--badge-active-bg)' },
  unsubscribed: { color: 'var(--badge-inactive-color)', bgVar: 'var(--badge-inactive-bg)' },
  general: { color: 'var(--badge-open-color)', bgVar: 'var(--badge-open-bg)' },
  support: { color: 'var(--badge-in-progress-color)', bgVar: 'var(--badge-in-progress-bg)' },
  feedback: { color: 'var(--badge-resolved-color)', bgVar: 'var(--badge-resolved-bg)' },
  user: { color: 'var(--badge-open-color)', bgVar: 'var(--badge-open-bg)' },
  admin: { color: 'var(--badge-in-progress-color)', bgVar: 'var(--badge-in-progress-bg)' },
  all: { color: 'var(--badge-resolved-color)', bgVar: 'var(--badge-resolved-bg)' },
};

// ── Newsletter status options ─────────────────────────────────────

export const NEWSLETTER_STATUS_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'subscribed', label: 'Subscribed' },
  { value: 'unsubscribed', label: 'Unsubscribed' },
];

// ── News options ──────────────────────────────────────────────────

export const NEWS_STATUS_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'active', label: 'Active' },
  { value: 'inactive', label: 'Inactive' },
];

export const NEWS_USER_TYPE_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'User', label: 'User' },
  { value: 'Admin', label: 'Admin' },
  { value: 'All', label: 'All Users' },
];

export const NEWS_USER_TYPE_FORM_OPTIONS = [
  { value: 'User', label: 'User' },
  { value: 'Admin', label: 'Admin' },
  { value: 'All', label: 'All' },
];

// ── Popup options ─────────────────────────────────────────────────

export const POPUP_STATUS_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'active', label: 'Active' },
  { value: 'inactive', label: 'Inactive' },
];

// ── Route management options ──────────────────────────────────────

export const ROUTE_USER_TYPE_OPTIONS = [
  { value: 'Admin', label: 'Admin' },
  { value: 'User', label: 'User' },
  { value: 'Any', label: 'Any' },
];

// ── Contact Us type options ────────────────────────────────────────

export const CONTACT_TYPE_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'General', label: 'General' },
  { value: 'Support', label: 'Support' },
  { value: 'Feedback', label: 'Feedback' },
];
