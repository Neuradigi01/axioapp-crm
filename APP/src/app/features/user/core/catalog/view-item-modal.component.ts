import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  computed,
  signal,
} from '@angular/core';
import { DatePipe } from '@angular/common';

import { InrPipe } from '../shared/pipes/inr.pipe';
import { CatalogItem } from './catalog-api.service';
import { deriveApiOrigin } from '@core/services/url.util';

/**
 * Read-only modal for a catalog item — opens on card click. Shows
 * everything the operator might want at a glance (image, SKU, price,
 * active state, custom fields, audit timestamps) without the edit
 * form fields. "Edit" hands off to the existing add/edit modal.
 */
@Component({
  selector: 'app-view-item-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, InrPipe],
  templateUrl: './view-item-modal.component.html',
})
export class ViewItemModalComponent {
  private readonly _item = signal<CatalogItem | null>(null);
  private readonly apiOrigin = deriveApiOrigin();

  @Input() set item(value: CatalogItem | null) {
    this._item.set(value);
  }

  @Output() readonly close = new EventEmitter<void>();
  @Output() readonly edit = new EventEmitter<CatalogItem>();

  protected readonly current = computed<CatalogItem | null>(() => this._item());

  protected readonly imageHref = computed<string | null>(() => {
    const stored = this._item()?.image_url;
    return stored ? `${this.apiOrigin}${stored}` : null;
  });

  protected readonly customEntries = computed<Array<[string, unknown]>>(() => {
    const data = this._item()?.custom_data ?? {};
    return Object.entries(data);
  });

  protected onEdit(): void {
    const item = this._item();
    if (item) this.edit.emit(item);
  }
}
