import { Directive, HostListener, inject, input } from '@angular/core';
import { BreakpointObserver, Breakpoints } from '@angular/cdk/layout';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';

@Directive({
  selector: '[appPreventContextMenu]',
  standalone: true,
})
export class PreventContextMenuDirective {
  readonly onlyForHandset = input(true);

  private readonly breakpointObserver = inject(BreakpointObserver);
  private readonly isHandset = toSignal(
    this.breakpointObserver.observe([Breakpoints.Handset]).pipe(map((result) => result.matches)),
    { initialValue: false }
  );

  @HostListener('contextmenu', ['$event'])
  onContextMenu(event: MouseEvent): void {
    if (!this.onlyForHandset() || this.isHandset()) {
      event.preventDefault();
    }
  }
}
