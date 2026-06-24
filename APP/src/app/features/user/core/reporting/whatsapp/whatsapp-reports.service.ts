import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';

/** Range presets the backend accepts on every analytics endpoint. */
export type ReportRange = '7d' | '30d' | '90d';

/** Volume granularity — hour rejected for 90d (server-side validation). */
export type ReportGranularity = 'day' | 'hour';

/** Response-time grouping — `team` / `channel` reserved for future
 *  multi-team / multi-channel expansion (server returns empty groups). */
export type ResponseTimeGroupBy = 'agent' | 'team' | 'channel';

export interface VolumeBucket {
  bucket_start: string;
  sent: number;
  received: number;
  failed: number;
  ai_sent: number;
}

export interface VolumeReport {
  range: ReportRange;
  granularity: ReportGranularity;
  buckets: VolumeBucket[];
  total_sent: number;
  total_received: number;
  total_failed: number;
  total_ai_sent: number;
}

export interface ResponseTimeBucket {
  label: string;
  seconds_lt: number;
  count: number;
}

export interface ResponseTimeGroup {
  key: string;
  label: string;
  median_seconds: number | null;
  p95_seconds: number | null;
  sample_size: number;
}

export interface ResponseTimeReport {
  range: ReportRange;
  groupby: ResponseTimeGroupBy;
  overall_median_seconds: number | null;
  overall_p95_seconds: number | null;
  sample_size: number;
  distribution: ResponseTimeBucket[];
  groups: ResponseTimeGroup[];
}

export interface OutcomeSlice {
  key: string;
  label: string;
  count: number;
}

export interface OutcomesReport {
  range: ReportRange;
  by_status: OutcomeSlice[];
  by_tag: OutcomeSlice[];
  total: number;
}

export interface LeaderboardRow {
  user_id: string;
  name: string;
  replies: number;
  conversations_handled: number;
  median_response_seconds: number | null;
  p95_response_seconds: number | null;
}

export interface LeaderboardReport {
  range: ReportRange;
  rows: LeaderboardRow[];
}

/** Step 21 — campaign funnel + failures + cost + quality timeline + AI metrics. */

export interface FunnelStage {
  key: string;
  label: string;
  count: number;
}

export interface CampaignFunnelReport {
  campaign_id: string;
  name: string;
  status: string;
  started_at: string | null;
  stages: FunnelStage[];
  delivery_median_seconds: number | null;
  delivery_p95_seconds: number | null;
}

export interface FailureBucket {
  reason: string;
  label: string;
  count: number;
}

export interface CampaignFailuresReport {
  campaign_id: string;
  total_failed: number;
  buckets: FailureBucket[];
  sample_errors: string[];
}

export interface CostLine {
  category: string;
  count: number;
  rate: number;
  currency: string;
  total: number;
}

export interface CostReport {
  range: ReportRange;
  region: string;
  currency: string;
  lines: CostLine[];
  total: number;
  is_estimate: boolean;
}

export interface QualityEvent {
  occurred_at: string;
  event_type: string;
  old_value: string | null;
  new_value: string | null;
}

export interface QualityVolumePoint {
  bucket_start: string;
  sent: number;
}

export interface QualityTimelineReport {
  range: ReportRange;
  events: QualityEvent[];
  volume: QualityVolumePoint[];
}

export interface AIMetricsReport {
  range: ReportRange;
  ai_replies: number;
  human_replies: number;
  ai_response_rate: number;
  ai_handled_conversations: number;
  escalated_conversations: number;
  escalation_rate: number;
  ai_only_completed: number;
  escalation_reasons: Record<string, number>;
}

/**
 * WhatsApp analytics API client (whatsapp-platform-upgrade Step 20).
 *
 * All endpoints sit behind `whatsapp.analytics.read`; the sidebar
 * entry is hidden when the user lacks the permission so callers
 * here can assume the user is authorised.
 */
@Injectable({ providedIn: 'root' })
export class WhatsAppReportsService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/reports/whatsapp`;

  getVolume(
    range: ReportRange,
    granularity: ReportGranularity,
  ): Observable<VolumeReport> {
    const params = new HttpParams()
      .set('range', range)
      .set('granularity', granularity);
    return this.http.get<VolumeReport>(`${this.base}/volume`, { params });
  }

  getResponseTime(
    range: ReportRange,
    groupby: ResponseTimeGroupBy = 'agent',
  ): Observable<ResponseTimeReport> {
    const params = new HttpParams().set('range', range).set('groupby', groupby);
    return this.http.get<ResponseTimeReport>(`${this.base}/response-time`, {
      params,
    });
  }

  getOutcomes(range: ReportRange): Observable<OutcomesReport> {
    const params = new HttpParams().set('range', range);
    return this.http.get<OutcomesReport>(`${this.base}/outcomes`, { params });
  }

  getAgentLeaderboard(range: ReportRange): Observable<LeaderboardReport> {
    const params = new HttpParams().set('range', range);
    return this.http.get<LeaderboardReport>(
      `${this.base}/agent-leaderboard`,
      { params },
    );
  }

  /** Step 21 — per-campaign funnel + time-to-delivery percentiles. */
  getCampaignFunnel(campaignId: string): Observable<CampaignFunnelReport> {
    return this.http.get<CampaignFunnelReport>(
      `${environment.apiBaseUrl}/reports/campaigns/${campaignId}/funnel`,
    );
  }

  /** Step 21 — per-campaign failure-reason breakdown. */
  getCampaignFailures(
    campaignId: string,
  ): Observable<CampaignFailuresReport> {
    return this.http.get<CampaignFailuresReport>(
      `${environment.apiBaseUrl}/reports/campaigns/${campaignId}/failures`,
    );
  }

  /** Step 21 — estimated WhatsApp cost for the org in the window. */
  getCost(range: ReportRange, region = 'IN'): Observable<CostReport> {
    const params = new HttpParams().set('range', range).set('region', region);
    return this.http.get<CostReport>(`${this.base}/cost`, { params });
  }

  /** Step 21 — phone-quality events + daily send volume. */
  getQualityTimeline(range: ReportRange): Observable<QualityTimelineReport> {
    const params = new HttpParams().set('range', range);
    return this.http.get<QualityTimelineReport>(
      `${this.base}/quality-timeline`,
      { params },
    );
  }

  /** Step 21 — AI response + escalation + completion-proxy metrics. */
  getAIMetrics(range: ReportRange): Observable<AIMetricsReport> {
    const params = new HttpParams().set('range', range);
    return this.http.get<AIMetricsReport>(`${this.base}/ai-metrics`, {
      params,
    });
  }
}

/** Pretty-print a seconds value as "5s" / "2m 30s" / "1h 12m" / "1d 4h".
 *  Used by the leaderboard + response-time widget for compact labels.
 *  Returns "—" for null + non-finite inputs. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) {
    return '—';
  }
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return sec ? `${m}m ${sec}s` : `${m}m`;
  }
  if (s < 86400) {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return m ? `${h}h ${m}m` : `${h}h`;
  }
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  return h ? `${d}d ${h}h` : `${d}d`;
}
