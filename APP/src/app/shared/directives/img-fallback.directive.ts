import { Directive, ElementRef, HostListener, inject, input } from '@angular/core';

@Directive({
  selector: 'img[appImgFallback]',
  standalone: true,
})
export class ImgFallbackDirective {
  readonly appImgFallback = input.required<string>();

  private readonly el = inject(ElementRef);

  @HostListener('error')
  onError(): void {
    this.el.nativeElement.src = this.appImgFallback();
  }
}
