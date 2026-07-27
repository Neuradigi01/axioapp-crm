# Step 11 — Conversations refresh

**Goal:** Restyle the three-pane conversations UI (channel nav + thread list + thread pane) with channel-branded bubbles inside a neutral chrome.
**Track:** Design Refresh — Track 4 (Page pass)
**Status:** Pending
**Depends on:** Steps 1, 5, 6, 7

---

## AIXO patterns

### Three-pane layout
- Left pane (240px, `bg-surface`, `border-subtle` right): channel list (All / WhatsApp / Messenger / Instagram / Telegram / SMS / Email) — each row: channel icon + name + unread mono count badge. Active row: `bg-accent-soft` `text-accent`.
- Middle pane (320px, `bg-surface`, `border-subtle` right): thread list. Each thread row: avatar (40px, channel-color dot overlay) + name + preview 12.5px text-muted + timestamp mono 11px text-faint + unread badge.
- Right pane (flex-1, `bg-bg`): message thread. Header: contact info + call/video/info icon buttons right. Body: scrollable messages. Footer: composer (textarea + attach + send).

### Channel-branded bubbles (only inside the message thread body — chrome stays neutral)
| Channel | Incoming bg | Outgoing bg | Text |
|---|---|---|---|
| WhatsApp | `#202C33` (dark) / `#FFFFFF` (light) | `#005C4B` / `#D9FDD3` | white on outgoing dark |
| Messenger | `#3A3B3C` / `#F0F2F5` | `#0866FF` | white on outgoing |
| Instagram | `#262626` / `#EFEFEF` | gradient `#DD2A7B → #962FBF` | white on outgoing |
| Telegram | `#182533` / `#EEFFDE` | `#2AABEE` / `#EEFFDE` | text-default |
| SMS / Email | `bg-surface-2` / `bg-app` | `bg-accent-soft` | text-default |

Bubbles: `rounded-2xl` 14px with the "tail" corner reduced (e.g. `rounded-tl-md` on incoming, `rounded-tr-md` on outgoing). Max-width 68% of pane. Time stamp mono 10.5px inside bubble bottom-right.

### Composer
- `bg-surface` `border-subtle` top-border only. Textarea 40px min-height, grows to 120px. Attach button (paperclip) + emoji button left, Send button (accent, arrow icon) right. Ctrl/Cmd+Enter to send.

### Empty state (no thread selected)
- Center of right pane: channel logo (large, opacity 0.6) + "Select a conversation" 14px muted + optional "Start a new one" accent link.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/conversations/conversations-shell/*.{ts,html,scss}` | modified |
| `APP/src/app/features/user/core/conversations/channel-list/*.{ts,html}` | modified |
| `APP/src/app/features/user/core/conversations/thread-list/*.{ts,html}` | modified |
| `APP/src/app/features/user/core/conversations/thread-pane/*.{ts,html,scss}` | modified — bubbles + composer |

**~8–10 files (split by pane if it exceeds 10).**

## Verification

- Three-pane layout renders correctly at desktop; mobile falls back to single pane with back navigation.
- Message bubbles carry channel branding on the correct side.
- Composer sends and receives correctly (existing behavior).
- Dark + light both look right.

## Out of scope

- Backend / provider wiring.
- WhatsApp Cloud API / Baileys sidecar work (separate track).
