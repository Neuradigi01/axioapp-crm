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
