import { Directive, ElementRef, HostListener, inject, input } from '@angular/core';
import { NumericType } from '@app/core/constants/app.types';

@Directive({
  selector: '[appOnlyNumeric]',
  standalone: true,
})
export class OnlyNumericDirective {
  readonly appOnlyNumeric = input<NumericType>('UInt');

  private readonly el = inject(ElementRef);

  @HostListener('keydown', ['$event'])
  onKeyDown(event: KeyboardEvent): void {
    if (
      event.key === 'Backspace' ||
      event.key === 'Delete' ||
      event.key === 'Tab' ||
      event.key === 'Escape' ||
      event.key === 'Enter' ||
      event.key === 'ArrowLeft' ||
      event.key === 'ArrowRight' ||
      event.key === 'ArrowUp' ||
      event.key === 'ArrowDown' ||
      event.key === 'Home' ||
      event.key === 'End' ||
      (event.ctrlKey && ['a', 'c', 'v', 'x', 'z'].includes(event.key.toLowerCase()))
    ) {
      return;
    }

    const type = this.appOnlyNumeric();
    const value: string = this.el.nativeElement.value;
    const selectionStart: number = this.el.nativeElement.selectionStart ?? 0;

    if (event.key >= '0' && event.key <= '9') {
      return;
    }

    if (event.key === '-' && (type === 'Int' || type === 'Decimal')) {
      if (selectionStart === 0 && !value.includes('-')) {
        return;
      }
    }

    if (event.key === '.' && (type === 'UDecimal' || type === 'Decimal')) {
      if (!value.includes('.')) {
        return;
      }
    }

    event.preventDefault();
  }

  @HostListener('paste', ['$event'])
  onPaste(event: ClipboardEvent): void {
    const clipboardData = event.clipboardData?.getData('text') ?? '';
    const sanitized = this.sanitize(clipboardData);

    if (sanitized !== clipboardData) {
      event.preventDefault();
      const input = this.el.nativeElement as HTMLInputElement;
      const start = input.selectionStart ?? 0;
      const end = input.selectionEnd ?? 0;
      const currentValue = input.value;
      const newValue = currentValue.substring(0, start) + sanitized + currentValue.substring(end);
      input.value = this.sanitize(newValue);
      input.dispatchEvent(new Event('input'));
    }
  }

  @HostListener('input')
  onInput(): void {
    const input = this.el.nativeElement as HTMLInputElement;
    const sanitized = this.sanitize(input.value);
    if (sanitized !== input.value) {
      input.value = sanitized;
    }
  }

  private sanitize(value: string): string {
    const type = this.appOnlyNumeric();

    switch (type) {
      case 'UInt':
        return value.replace(/[^0-9]/g, '');
      case 'Int':
        return this.sanitizeSigned(value, false);
      case 'UDecimal':
        return this.sanitizeDecimal(value, false);
      case 'Decimal':
        return this.sanitizeSigned(value, true);
    }
  }

  private sanitizeSigned(value: string, allowDecimal: boolean): string {
    const hasNegative = value.startsWith('-');
    let cleaned = allowDecimal ? this.sanitizeDecimal(value.replace(/-/g, ''), false) : value.replace(/-/g, '').replace(/[^0-9]/g, '');
    if (hasNegative) {
      cleaned = '-' + cleaned;
    }
    return cleaned;
  }

  private sanitizeDecimal(value: string, _signed: boolean): string {
    let result = value.replace(/[^0-9.]/g, '');
    const dotIndex = result.indexOf('.');
    if (dotIndex !== -1) {
      result = result.substring(0, dotIndex + 1) + result.substring(dotIndex + 1).replace(/\./g, '');
    }
    return result;
  }
}
