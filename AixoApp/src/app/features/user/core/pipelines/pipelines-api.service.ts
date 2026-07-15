import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';

/**
 * Wire shapes mirror `api/src/app/core/pipelines/schemas.py`. Keep
 * these in lock-step with the backend — the board's column ordering,
 * stage colors, and is_won/is_lost flags all flow from these fields.
 */
export interface PipelineStage {
  id: string;
  pipeline_id: string;
  key: string;
  name: string;
  color: string | null;
  display_order: number;
  is_won: boolean;
  is_lost: boolean;
}

export interface Pipeline {
  id: string;
  org_id: string;
  key: string;
  name: string;
  created_at: string;
  stages: PipelineStage[];
}

export interface StageUpdate {
  name?: string;
  color?: string | null;
  display_order?: number;
}

export interface StageCreate {
  name: string;
  color?: string;
  after_stage_key?: string;
}

/**
 * Minimal "card" shape the kanban + list components require. The
 * caller's actual lead / order / contact item type extends this — the
 * board only cares about `id` (for tracking + emitted events) and
 * `pipeline_stage` (to bucket into the right column).
 */
export interface PipelineItem {
  id: string;
  pipeline_stage: string;
  [key: string]: unknown;
}

/** Emitted by both board and list when the user changes a card's stage. */
export interface ItemMovedEvent {
  itemId: string;
  fromStage: string;
  toStage: string;
}

@Injectable({ providedIn: 'root' })
export class PipelinesApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/pipelines`;

  list(): Observable<Pipeline[]> {
    return this.http.get<Pipeline[]>(this.base);
  }

  getByKey(key: string): Observable<Pipeline> {
    return this.http.get<Pipeline>(`${this.base}/${key}`);
  }

  createStage(pipelineKey: string, payload: StageCreate): Observable<PipelineStage> {
    return this.http.post<PipelineStage>(`${this.base}/${pipelineKey}/stages`, payload);
  }

  updateStage(
    pipelineKey: string,
    stageId: string,
    payload: StageUpdate,
  ): Observable<PipelineStage> {
    return this.http.patch<PipelineStage>(`${this.base}/${pipelineKey}/stages/${stageId}`, payload);
  }

  /**
   * Delete a stage. `moveLeadsTo`, when supplied, names the relocation
   * target stage's key — the backend returns 409 with
   * `{cards_in_stage, must_provide}` if the stage holds cards and no
   * target was given. Callers should catch that 409 to surface the
   * relocation modal, then retry with `moveLeadsTo` filled in.
   */
  deleteStage(pipelineKey: string, stageId: string, moveLeadsTo?: string): Observable<void> {
    let url = `${this.base}/${pipelineKey}/stages/${stageId}`;
    if (moveLeadsTo) {
      url += `?move_leads_to=${encodeURIComponent(moveLeadsTo)}`;
    }
    return this.http.delete<void>(url);
  }
}
