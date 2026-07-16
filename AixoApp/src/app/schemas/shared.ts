export interface IDashboardTile {
  label: string;
  value: string | number;
  icon: string;
  color: string;
}

export interface IConfirmDialogData {
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  color?: 'warn' | 'primary';
}

export interface IPageEvent {
  page_index: number;
  page_size: number;
}
