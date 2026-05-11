import { Component, ChangeDetectionStrategy, input, output, contentChild, signal, TemplateRef } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import { NgTemplateOutlet } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { FormCardComponent } from '../form-card/form-card.component';
import { IPageEvent } from '@app/schemas/shared';

@Component({
  selector: 'app-page-layout',
  templateUrl: './page-layout.component.html',
  styleUrl: './page-layout.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    NgTemplateOutlet,
    MatButtonModule,
    MatIconModule,
    MatPaginatorModule,
    FormCardComponent,
  ],
})
export class PageLayoutComponent {
  readonly formGroup = input<FormGroup>(new FormGroup({}));
  readonly data = input<unknown[]>([]);
  readonly dataCount = input<number>(0);
  readonly isFiltered = input<boolean>(false);
  readonly pageTitle = input<string>('');
  readonly pageSubtitle = input<string>('');
  readonly tableId = input<string>('');
  readonly pageSize = input<number>(10);
  readonly pageSizeOptions = input<number[]>([10, 25, 50, 100]);
  readonly showExport = input<boolean>(true);

  readonly submitEvent = output<void>();
  readonly clearEvent = output<void>();
  readonly pageEvent = output<IPageEvent>();
  readonly exportEvent = output<void>();

  readonly requiredFiltersTemplate = contentChild<TemplateRef<unknown>>('requiredFilters');
  readonly filtersTemplate = contentChild<TemplateRef<unknown>>('filters');
  readonly tableHeaderTemplate = contentChild<TemplateRef<unknown>>('tableHeader');
  readonly tableBodyTemplate = contentChild<TemplateRef<unknown>>('tableBody');

  readonly showFilters = signal(true);
  readonly currentPageIndex = signal(0);

  getSrNo(index: number): number {
    return this.currentPageIndex() * this.pageSize() + index + 1;
  }

  onSubmit(): void {
    this.currentPageIndex.set(0);
    this.submitEvent.emit();
  }

  onClear(): void {
    this.currentPageIndex.set(0);
    this.clearEvent.emit();
  }

  onPageChange(event: PageEvent): void {
    this.currentPageIndex.set(event.pageIndex);
    this.pageEvent.emit({
      page_index: event.pageIndex,
      page_size: event.pageSize,
    });
  }

  onExport(): void {
    this.exportEvent.emit();
  }

  toggleFilters(): void {
    this.showFilters.update((v) => !v);
  }
}
