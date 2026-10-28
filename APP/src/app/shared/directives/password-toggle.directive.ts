import { Directive, signal, computed } from '@angular/core';

@Directive({
  selector: '[appPasswordToggle]',
  exportAs: 'passwordToggle',
  standalone: true,
})
export class PasswordToggleDirective {
  readonly hidden = signal(true);
  readonly icon = computed(() => (this.hidden() ? 'visibility' : 'visibility_off'));
  readonly type = computed(() => (this.hidden() ? 'password' : 'text'));
  readonly ariaLabel = computed(() => (this.hidden() ? 'Show password' : 'Hide password'));

  toggle(): void {
    this.hidden.update((v) => !v);
  }
}
