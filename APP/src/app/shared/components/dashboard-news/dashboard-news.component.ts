import { Component, ChangeDetectionStrategy, inject, signal, OnInit } from '@angular/core';
import { DatePipe } from '@angular/common';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { NewsApiService } from '@app/services/news-api.service';
import { INews } from '@app/schemas/news';
import { TruncatePipe } from '@shared/pipes/truncate.pipe';

@Component({
  selector: 'app-dashboard-news',
  templateUrl: './dashboard-news.component.html',
  styleUrl: './dashboard-news.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatCardModule, MatIconModule, DatePipe, TruncatePipe],
})
export class DashboardNewsComponent implements OnInit {
  private readonly newsApi = inject(NewsApiService);

  readonly newsItems = signal<INews[]>([]);
  readonly expandedId = signal<number | null>(null);

  async ngOnInit(): Promise<void> {
    try {
      const res = await this.newsApi.getActiveNews();
      if (res.success && res.data) {
        this.newsItems.set(res.data);
      }
    } catch {
      // Silently fail — news is supplementary
    }
  }

  toggleExpand(id: number): void {
    this.expandedId.update((current) => (current === id ? null : id));
  }

  isExpanded(id: number): boolean {
    return this.expandedId() === id;
  }
}
