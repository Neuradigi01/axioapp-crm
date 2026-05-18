import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import {
  Campaign,
  CampaignStatus,
  CampaignsApiService,
} from './campaigns-api.service';
import { CreateCampaignModalComponent } from './create-campaign-modal.component';
import { extractApiError } from '@core/services/api-error.util';

interface ChannelStyle {
  label: string;
  cls: string;
}

const CHANNEL_STYLES: Record<string, ChannelStyle> = {
  whatsapp: {
    label: 'WhatsApp',
    cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  },
  sms: { label: 'SMS', cls: 'bg-zinc-100 text-zinc-700 ring-zinc-200' },
  email: {
    label: 'Email',
    cls: 'bg-violet-50 text-violet-700 ring-violet-200',
  },
  facebook: {
    label: 'Facebook',
    cls: 'bg-blue-50 text-blue-700 ring-blue-200',
  },
  instagram: {
    label: 'Instagram',
    cls: 'bg-gradient-to-r from-fuchsia-500 to-amber-400 text-white ring-fuchsia-200',
  },
  web: { label: 'Web', cls: 'bg-sky-50 text-sky-700 ring-sky-200' },
};

const STATUS_STYLES: Record<CampaignStatus, { label: string; cls: string }> = {
  draft: {
    label: 'Draft',
    cls: 'bg-zinc-100 text-zinc-700 ring-zinc-200',
  },
  scheduled: {
    label: 'Scheduled',
    cls: 'bg-amber-50 text-amber-700 ring-amber-200',
  },
  running: {
    label: 'Running',
    cls: 'bg-sky-50 text-sky-700 ring-sky-200',
  },
  done: {
    label: 'Done',
    cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  },
  failed: {
    label: 'Failed',
    cls: 'bg-rose-50 text-rose-700 ring-rose-200',
  },
};

/**
 * Campaigns page â€” cards grid + "New campaign" button + delete + start.
 *
 * Each card carries: name Â· status pill Â· channel pill Â· audience
 * fingerprint Â· schedule time (if any) Â· "Start" button for drafts Â·
 * "View" link to the detail page.
 */
@Component({
  selector: 'app-campaigns-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, RouterLink, CreateCampaignModalComponent],
  templateUrl: './campaigns.page.html',
})
export class CampaignsPageComponent {
  private readonly api = inject(CampaignsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly items = signal<Campaign[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly modalOpen = signal(false);
  protected readonly busyId = signal<string | null>(null);

  constructor() {
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list(1, 100)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.items.set(resp.items);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.loading.set(false);
          this.loadError.set(
            extractApiError(err) ?? 'Could not load campaigns.',
          );
        },
      });
  }

  protected openModal(): void {
    this.modalOpen.set(true);
  }

  protected onCreated(campaign: Campaign): void {
    this.modalOpen.set(false);
    this.items.update((rows) => [campaign, ...rows]);
  }

  protected onCancel(): void {
    this.modalOpen.set(false);
  }

  protected start(c: Campaign): void {
    this.busyId.set(c.id);
    this.api
      .start(c.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.busyId.set(null);
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.busyId.set(null);
          this.loadError.set(
            extractApiError(err) ?? 'Could not start campaign.',
          );
        },
      });
  }

  protected remove(c: Campaign): void {
    const ok = window.confirm(`Delete campaign "${c.name}"?`);
    if (!ok) return;
    this.busyId.set(c.id);
    this.api
      .delete(c.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.busyId.set(null);
          this.items.update((rows) => rows.filter((r) => r.id !== c.id));
        },
        error: (err: HttpErrorResponse) => {
          this.busyId.set(null);
          this.loadError.set(
            extractApiError(err) ?? 'Could not delete campaign.',
          );
        },
      });
  }

  protected channelStyle(channel: string): ChannelStyle {
    return CHANNEL_STYLES[channel] ?? CHANNEL_STYLES['web'];
  }

  protected statusStyle(s: CampaignStatus): { label: string; cls: string } {
    return STATUS_STYLES[s];
  }

  protected audiencePreview(c: Campaign): string {
    const parts: string[] = [];
    if (c.audience_filter?.q) parts.push(`q="${c.audience_filter.q}"`);
    if (c.audience_filter?.source)
      parts.push(`source=${c.audience_filter.source}`);
    if (c.audience_filter?.tag) parts.push(`tag=${c.audience_filter.tag}`);
    return parts.length ? parts.join(' Â· ') : 'Everyone';
  }

  protected formatDate(iso: string | null): string {
    if (!iso) return 'â€”';
    return new Date(iso).toLocaleString();
  }

}
