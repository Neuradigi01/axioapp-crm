-- ---------------------------------------------------------------------------
-- Mailgun inbound smoke — cleanup script
--
-- Context
--   The 2026-09-02 morning smoke (see SMOKE-RESULTS.md) POSTed synthetic
--   signed payloads at the live webhook to verify SPF-fail spoofing,
--   auto-responder detection, and dedup. Those inbound rows persisted
--   into the shared dev DB (`crm_local`) and now render in the
--   Conversations inbox as if they were real customer emails.
--
-- Fixtures leaked by the smoke
--   - Sender @bad.com               (SPF-fail attacker test)
--   - Sender @bigco.com             (CEO-fraud spoof victim contact)
--   - Sender @ex.com                (customer / vacationer / spoof-victim
--                                    baseline replies)
--   - Sender-from `acme.example`    (synthetic SMTP sender created by
--                                    the smoke's _make_sender())
--
-- How to run
--   1. Run the PREVIEW block first. Verify every row it returns is a
--      smoke artifact (contact email or from-address matches one of the
--      test patterns above). None of these domains map to real
--      customers.
--   2. If the preview looks right, uncomment the DELETE block at the
--      bottom and run it inside a single BEGIN/COMMIT so you can
--      ROLLBACK if the count surprises you.
--
-- Blast radius
--   Filter scopes to the two smoke-target orgs only:
--     - Ajay's Workspace          41f9ede9-41b3-44ce-b489-3004566d4068
--     - Mailgun smoke target org  e3684043-a281-45a8-8108-57413a57a08e
--   AND requires the message's From/sender to match a test domain.
--   Cascades: tbl_messages + tbl_conversation_tag_assignments both
--   have `ON DELETE CASCADE` on tbl_conversations.id — no orphan rows.
--   tbl_contacts is intentionally NOT touched here (they're independent
--   records; a separate SELECT at the bottom lists them for review).
-- ---------------------------------------------------------------------------


-- =====================
-- PREVIEW — safe to run
-- =====================

WITH smoke_orgs AS (
    SELECT unnest(ARRAY[
        '41f9ede9-41b3-44ce-b489-3004566d4068'::uuid,  -- Ajay's Workspace
        'e3684043-a281-45a8-8108-57413a57a08e'::uuid   -- smoke target
    ]) AS org_id
),
smoke_conversations AS (
    SELECT DISTINCT c.id, c.org_id, c.channel, c.contact_id,
                    c.last_message_at, c.created_at
    FROM tbl_conversations c
    JOIN tbl_messages m ON m.conversation_id = c.id
    WHERE c.org_id IN (SELECT org_id FROM smoke_orgs)
      AND c.channel = 'email'
      AND (
              m.payload->>'from'   ILIKE '%@bad.com%'
           OR m.payload->>'from'   ILIKE '%@bigco.com%'
           OR m.payload->>'from'   ILIKE '%@ex.com%'
           OR m.payload->>'from'   ILIKE '%@acme.example%'
           OR m.payload->>'sender' ILIKE '%@bad.com%'
           OR m.payload->>'sender' ILIKE '%@bigco.com%'
           OR m.payload->>'sender' ILIKE '%@ex.com%'
           OR m.payload->>'sender' ILIKE '%@acme.example%'
      )
)
SELECT sc.org_id,
       sc.id AS conversation_id,
       sc.last_message_at,
       (SELECT count(*) FROM tbl_messages m WHERE m.conversation_id = sc.id) AS msg_count,
       (SELECT string_agg(DISTINCT COALESCE(m.payload->>'from', m.payload->>'sender'), ', ')
          FROM tbl_messages m WHERE m.conversation_id = sc.id) AS senders
FROM smoke_conversations sc
ORDER BY sc.last_message_at DESC;


-- Contacts created by the smoke (for review — NOT auto-deleted).
-- These are safe to delete manually if you also want the contact
-- records gone.
SELECT id, org_id, full_name, email, created_at
FROM tbl_contacts
WHERE org_id IN (
        '41f9ede9-41b3-44ce-b489-3004566d4068'::uuid,
        'e3684043-a281-45a8-8108-57413a57a08e'::uuid
      )
  AND (
       email ILIKE '%@bad.com'
    OR email ILIKE '%@bigco.com'
    OR email ILIKE '%@ex.com'
    OR email ILIKE '%@acme.example'
  )
ORDER BY created_at DESC;


-- ===================================
-- DELETE — uncomment AFTER preview OK
-- ===================================
--
-- BEGIN;
--
-- WITH smoke_orgs AS (
--     SELECT unnest(ARRAY[
--         '41f9ede9-41b3-44ce-b489-3004566d4068'::uuid,
--         'e3684043-a281-45a8-8108-57413a57a08e'::uuid
--     ]) AS org_id
-- ),
-- smoke_conversations AS (
--     SELECT DISTINCT c.id
--     FROM tbl_conversations c
--     JOIN tbl_messages m ON m.conversation_id = c.id
--     WHERE c.org_id IN (SELECT org_id FROM smoke_orgs)
--       AND c.channel = 'email'
--       AND (
--               m.payload->>'from'   ILIKE '%@bad.com%'
--            OR m.payload->>'from'   ILIKE '%@bigco.com%'
--            OR m.payload->>'from'   ILIKE '%@ex.com%'
--            OR m.payload->>'from'   ILIKE '%@acme.example%'
--            OR m.payload->>'sender' ILIKE '%@bad.com%'
--            OR m.payload->>'sender' ILIKE '%@bigco.com%'
--            OR m.payload->>'sender' ILIKE '%@ex.com%'
--            OR m.payload->>'sender' ILIKE '%@acme.example%'
--       )
-- )
-- DELETE FROM tbl_conversations
--  WHERE id IN (SELECT id FROM smoke_conversations)
-- RETURNING id, org_id, contact_id, last_message_at;
--
-- -- ROLLBACK; -- if the RETURNING output shows anything unexpected
-- COMMIT;
