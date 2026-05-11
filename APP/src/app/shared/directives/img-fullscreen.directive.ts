import { Directive, ElementRef, HostListener, inject, OnDestroy, Renderer2 } from '@angular/core';

@Directive({
  selector: 'img[appImgFullscreen]',
  standalone: true,
})
export class ImgFullscreenDirective implements OnDestroy {
  private readonly el = inject(ElementRef);
  private readonly renderer = inject(Renderer2);

  private overlay: HTMLDivElement | null = null;
  private escListener: (() => void) | null = null;

  constructor() {
    this.renderer.setStyle(this.el.nativeElement, 'cursor', 'pointer');
  }

  @HostListener('click')
  onClick(): void {
    this.openFullscreen();
  }

  ngOnDestroy(): void {
    this.closeFullscreen();
  }

  private openFullscreen(): void {
    if (this.overlay) {
      return;
    }

    this.overlay = this.renderer.createElement('div') as HTMLDivElement;
    this.renderer.setStyle(this.overlay, 'position', 'fixed');
    this.renderer.setStyle(this.overlay, 'top', '0');
    this.renderer.setStyle(this.overlay, 'left', '0');
    this.renderer.setStyle(this.overlay, 'width', '100vw');
    this.renderer.setStyle(this.overlay, 'height', '100vh');
    this.renderer.setStyle(this.overlay, 'background', 'rgba(0, 0, 0, 0.9)');
    this.renderer.setStyle(this.overlay, 'display', 'flex');
    this.renderer.setStyle(this.overlay, 'align-items', 'center');
    this.renderer.setStyle(this.overlay, 'justify-content', 'center');
    this.renderer.setStyle(this.overlay, 'z-index', '9999');
    this.renderer.setStyle(this.overlay, 'cursor', 'pointer');

    const img = this.renderer.createElement('img') as HTMLImageElement;
    this.renderer.setAttribute(img, 'src', this.el.nativeElement.src);
    this.renderer.setAttribute(img, 'alt', this.el.nativeElement.alt || '');
    this.renderer.setStyle(img, 'max-width', '90vw');
    this.renderer.setStyle(img, 'max-height', '90vh');
    this.renderer.setStyle(img, 'object-fit', 'contain');

    this.renderer.appendChild(this.overlay, img);
    this.renderer.appendChild(document.body, this.overlay);

    this.renderer.listen(this.overlay, 'click', () => this.closeFullscreen());
    this.escListener = this.renderer.listen('document', 'keydown.escape', () => this.closeFullscreen());
  }

  private closeFullscreen(): void {
    if (this.overlay) {
      this.renderer.removeChild(document.body, this.overlay);
      this.overlay = null;
    }
    if (this.escListener) {
      this.escListener();
      this.escListener = null;
    }
  }
}
