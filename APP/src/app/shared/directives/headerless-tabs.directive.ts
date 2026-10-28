import { AfterViewInit, Directive, ElementRef, inject } from '@angular/core';

@Directive({
  selector: '[appHeaderlessTabs]',
  standalone: true,
})
export class HeaderlessTabsDirective implements AfterViewInit {
  private readonly el = inject(ElementRef);

  ngAfterViewInit(): void {
    const header = this.el.nativeElement.querySelector('.mat-mdc-tab-header');
    if (header) {
      header.style.display = 'none';
    }
  }
}
