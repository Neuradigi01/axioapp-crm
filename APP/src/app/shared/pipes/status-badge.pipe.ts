import { Pipe, PipeTransform } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { BADGE_MAP } from '@core/constants/app.constants';

@Pipe({
  name: 'statusBadge',
  pure: true,
})
export class StatusBadgePipe implements PipeTransform {
  constructor(private readonly sanitizer: DomSanitizer) {}

  transform(value: string | boolean | null | undefined): SafeHtml {
    if (value === null || value === undefined) {
      return '';
    }

    const label = typeof value === 'boolean' ? (value ? 'Active' : 'Inactive') : value;

    const key = label.toLowerCase();
    const config = BADGE_MAP[key];

    if (!config) {
      return this.sanitizer.bypassSecurityTrustHtml(
        `<span class="status-badge">${this.escapeHtml(label)}</span>`,
      );
    }

    const style = `
      display: inline-flex;
      align-items: center;
      padding: 4px 12px;
      border-radius: 9999px;
      font-size: 0.8rem;
      font-weight: 500;
      line-height: 1.4;
      color: ${config.color};
      background-color: ${config.bgVar};
    `
      .replace(/\s+/g, ' ')
      .trim();

    return this.sanitizer.bypassSecurityTrustHtml(
      `<span class="status-badge" style="${style}">${this.escapeHtml(label)}</span>`,
    );
  }

  private escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}
