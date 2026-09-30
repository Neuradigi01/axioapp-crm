import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, Subject, tap } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { TokenStorageService } from '../auth/token-storage.service';
import { ToastHostService } from './toast-host.service';

export interface Notification {
  id: string;
  org_id: string;
  user_id: string;
  type: string;
  title: string;
  body: string | null;
  payload: Record<string, unknown>;
  read_at: string | null;
  created_at: string;
}

/** Non-persisted live event pushed over the same socket (server frame
 *  `{kind: "event", type, payload}`). Never shown in the bell — pages
 *  subscribe to `events$` to refresh live (e.g. the inbox reacting to
 *  `conversation.updated`). */
export interface LiveEvent {
  type: string;
  payload: Record<string, unknown>;
}

export interface ReadAllResponse {
  marked: number;
}

/**
 * REST + WebSocket client for notifications.
 *
 * Responsibilities:
 *   - Owns the singleton `recent` + `unreadCount` signals every UI
 *     surface (header bell badge, popover list, toast queue) reads.
 *   - `start()` opens a WebSocket to `/api/v1/notifications/stream`
 *     and fetches the initial unread count via REST. Called from the
 *     header on init.
 *   - `stop()` closes the socket and cancels pending reconnect.
 *   - Exponential-backoff reconnect: 1s → 2s → 4s → 8s → … capped at
 *     30 s. Resets on a clean connection.
 *   - On every incoming WS message → push a toast, prepend to
 *     `recent`, increment `unreadCount`.
 *   - REST helpers: `list`, `markRead`, `markAllRead`.
 *
 * Service is `providedIn: 'root'` so the same instance backs the
 * header bell badge and the popover (no double-WS, no state drift).
 */
@Injectable({ providedIn: 'root' })
export class NotificationsApiService {
  private readonly http = inject(HttpClient);
  private readonly tokens = inject(TokenStorageService);
  private readonly toastHost = inject(ToastHostService);

  private readonly base = `${environment.apiBaseUrl}/notifications`;

  /** REST-loaded recent list — popover renders from this. */
  readonly recent = signal<Notification[]>([]);
  /** Count of unread notifications. Derived from `recent` + WS pushes. */
  private readonly _unread = signal<number>(0);
  readonly unreadCount = computed(() => this._unread());
  readonly connected = signal<boolean>(false);
  private readonly liveEvents = new Subject<LiveEvent>();
  /** Live (non-notification) events — see `LiveEvent`. */
  readonly events$ = this.liveEvents.asObservable();

  private ws: WebSocket | null = null;
  private started = false;
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private intentionallyClosing = false;

  /** Open the WebSocket + load initial state. Idempotent. */
  start(): void {
    if (this.started) return;
    this.started = true;
    this.refreshInitial();
    this.openSocket();
  }

  /** Close socket + reset state. Called on logout. */
  stop(): void {
    this.started = false;
    this.intentionallyClosing = true;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws !== null) {
      this.ws.close();
      this.ws = null;
    }
    this.recent.set([]);
    this._unread.set(0);
    this.connected.set(false);
  }

  list(limit = 20): Observable<Notification[]> {
    return this.http.get<Notification[]>(`${this.base}?limit=${limit}`).pipe(
      tap((rows) => {
        this.recent.set(rows);
        this._unread.set(rows.filter((r) => r.read_at === null).length);
      }),
    );
  }

  markRead(id: string): Observable<Notification> {
    return this.http.patch<Notification>(`${this.base}/${id}/read`, {}).pipe(
      tap((updated) => {
        this.recent.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
        this._unread.set(this.recent().filter((r) => r.read_at === null).length);
      }),
    );
  }

  markAllRead(): Observable<ReadAllResponse> {
    return this.http.post<ReadAllResponse>(`${this.base}/read-all`, {}).pipe(
      tap(() => {
        const now = new Date().toISOString();
        this.recent.update((rows) =>
          rows.map((r) => (r.read_at === null ? { ...r, read_at: now } : r)),
        );
        this._unread.set(0);
      }),
    );
  }

  // --- Internals ---

  private refreshInitial(): void {
    this.list(20).subscribe({
      error: () => {
        /* leave signals empty — the user might be logged out */
      },
    });
  }

  private openSocket(): void {
    const token = this.tokens.getAccess();
    if (!token) {
      // No JWT yet — try again shortly. The header always mounts after
      // login so this is a defensive fallback.
      this.scheduleReconnect();
      return;
    }
    const wsUrl = this.toWsUrl(`${this.base}/stream?token=${encodeURIComponent(token)}`);
    let socket: WebSocket;
    try {
      socket = new WebSocket(wsUrl);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = socket;
    this.intentionallyClosing = false;

    socket.onopen = () => {
      this.connected.set(true);
      this.reconnectAttempts = 0;
    };

    socket.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as Notification | (LiveEvent & { kind: 'event' });
        if ('kind' in data && data.kind === 'event') {
          this.liveEvents.next({ type: data.type, payload: data.payload ?? {} });
          return;
        }
        this.onIncoming(data as Notification);
      } catch {
        /* malformed frame — ignore */
      }
    };

    socket.onerror = () => {
      // onclose will fire after onerror; we handle reconnect there.
    };

    socket.onclose = () => {
      this.connected.set(false);
      this.ws = null;
      if (!this.intentionallyClosing && this.started) {
        this.scheduleReconnect();
      }
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null) return;
    // 1s, 2s, 4s, 8s, 16s, capped at 30s.
    const base = 1_000;
    const cap = 30_000;
    const delay = Math.min(cap, base * 2 ** this.reconnectAttempts);
    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (this.started) this.openSocket();
    }, delay);
  }

  private onIncoming(n: Notification): void {
    this.recent.update((rows) => {
      // Deduplicate against the initial REST snapshot.
      if (rows.some((r) => r.id === n.id)) return rows;
      return [n, ...rows].slice(0, 20);
    });
    if (n.read_at === null) {
      this._unread.update((c) => c + 1);
    }
    this.toastHost.push({
      title: n.title,
      body: n.body ?? undefined,
      href: this.deeplinkFor(n),
    });
  }

  /** Pull `payload.deeplink` if the server provided one. */
  private deeplinkFor(n: Notification): string | undefined {
    const dl = (n.payload as { deeplink?: unknown }).deeplink;
    return typeof dl === 'string' ? dl : undefined;
  }

  private toWsUrl(httpUrl: string): string {
    if (httpUrl.startsWith('https://')) return 'wss://' + httpUrl.slice('https://'.length);
    if (httpUrl.startsWith('http://')) return 'ws://' + httpUrl.slice('http://'.length);
    return httpUrl;
  }
}
