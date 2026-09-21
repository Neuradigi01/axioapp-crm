/**
 * Types for the Sending Domains tab (tasks/email-sending-domains Step 7).
 *
 * Mirrors the backend ``DomainOut`` / ``ClaimDomainIn`` Pydantic schemas
 * from ``core/email_sender_setup/schemas.py``. Fields that the backend
 * deliberately omits (``mailgun_domain_id``, ``org_id``) are absent here
 * too — the UI must not depend on them.
 */

/**
 * One row of the ``dns_records`` JSONB blob, matching Mailgun's
 * ``sending_dns_records`` / ``receiving_dns_records`` item shape.
 *
 * ``priority`` is populated only for MX records; treat any other type
 * as null. ``valid`` is Mailgun's own verdict string (``"valid"`` /
 * ``"invalid"`` / ``"unknown"``) — the UI colour-codes it verbatim
 * without translating the value.
 */
export interface DnsRecord {
  record_type: string | null;
  name: string | null;
  value: string | null;
  priority: string | null;
  valid: string | null;
  cached: unknown[] | null;
  is_active: boolean | null;
}

export interface DnsRecordsBlob {
  sending: DnsRecord[];
  receiving: DnsRecord[];
}

export type SendingDomainStatus = 'pending' | 'verified' | 'demoted' | 'released';

/**
 * Server response shape for ``GET /api/v1/sender-domains`` and every
 * single-domain endpoint (``POST /``, ``POST /{id}/verify``).
 */
export interface SendingDomain {
  id: string;
  domain: string;
  verification_status: SendingDomainStatus;
  dns_records: DnsRecordsBlob;
  mx_verified: boolean;
  spf_verified: boolean;
  dkim_verified: boolean;
  dmarc_verified: boolean;
  last_verified_at: string | null;
  region: 'us' | 'eu';
  created_at: string;
}

/**
 * Payload for ``POST /api/v1/sender-domains``. Backend validates the
 * domain shape via the same RFC-1035 regex used in ``ClaimDomainIn``.
 */
export interface ClaimDomainRequest {
  domain: string;
  region: 'us' | 'eu';
}

// ---------------------------------------------------------------------------
// tasks/email-inbound-forwarding Step 5 — Inbound Addresses tab.
//
// Mirrors the backend ``ForwardedAddressOut`` / ``CreateForwardedAddressIn``
// / ``UpdateForwardedAddressIn`` schemas from
// ``core/channel_endpoints/schemas.py``. The raw ``forwarding_token``
// deliberately does NOT appear here — frontends see only the composed
// ``forwarding_address`` (``f-<token>@<inbound-domain>``).
// ---------------------------------------------------------------------------

export interface AssigneeRef {
  id: string;
  name: string;
}

export interface ForwardedAddress {
  id: string;
  label: string;
  forwarding_address: string;
  auto_create_contact: boolean;
  default_assignee: AssigneeRef | null;
  is_active: boolean;
  last_inbound_at: string | null;
  created_at: string;
}

export interface CreateForwardedAddressRequest {
  label: string;
  auto_create_contact?: boolean;
  default_assignee_user_id?: string | null;
}

export interface UpdateForwardedAddressRequest {
  label?: string;
  auto_create_contact?: boolean;
  default_assignee_user_id?: string | null;
}
