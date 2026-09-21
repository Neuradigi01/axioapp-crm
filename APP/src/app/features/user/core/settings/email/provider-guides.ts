/**
 * Provider forwarding guides — verbatim step lists sourced from Step 1
 * discovery ([`tasks/email-inbound-forwarding/PROVIDER-GUIDES.md`]).
 *
 * Each guide's ``steps`` array is displayed one-per-line in the wizard's
 * Step 3, followed by a link to the provider's own doc so the operator
 * can bail into the source if the CRM's summary drifts. Wording is
 * quoted from the vendor's own doc — do NOT paraphrase without a fresh
 * discovery re-fetch (Rule zero from ``DISCOVERY_RULES.md``).
 *
 * Two providers ship with placeholder step lists that the wizard
 * surfaces alongside a "Docs still catching up" banner: Outlook.com
 * personal (Microsoft's URL 404'd during discovery — see
 * ``DISCOVERY-NOTES.md`` gap #2) and Custom IMAP (no canonical URL —
 * gap #3). Both link to a generic "reach out to support" CTA rather
 * than fabricated steps.
 */

export interface ProviderGuide {
  key: string;
  title: string;
  steps: string[];
  docsUrl: string | null;
  /** True when the guide is a placeholder — the wizard renders a
   * "docs pending" banner instead of the normal step numbering. */
  placeholder: boolean;
}

export const PROVIDER_GUIDES: Record<string, ProviderGuide> = {
  gmail: {
    key: 'gmail',
    title: 'Gmail (personal)',
    steps: [
      "In Gmail, click Settings → 'Forwarding and POP/IMAP' (or 'Forwarding').",
      "In the 'Forwarding' section, click 'Add a forwarding address'.",
      'Paste the address above into the field and click Next → Proceed → OK.',
      'Gmail will send a verification email to the forwarding address. Open your CRM inbox and click the verification link — the code shows up there under Conversations.',
      "Refresh the Gmail settings page. Under 'Forwarding' select 'Forward a copy of incoming mail to' and choose 'Keep Gmail's copy in the Inbox'.",
      'At the bottom of the page click Save Changes.',
    ],
    docsUrl: 'https://support.google.com/mail/answer/10957',
    placeholder: false,
  },
  google_workspace: {
    key: 'google_workspace',
    title: 'Google Workspace (admin)',
    steps: [
      'Open the Google Admin console → Apps → Google Workspace → Gmail → Routing.',
      'Select the top-level organizational unit on the left.',
      "Scroll to 'Email forwarding using recipient address map' and click Configure (or Add Another Rule).",
      'Give the address map a descriptive name (e.g. "Support inbox → CRM").',
      "In step 1 of the Add setting box, click Add. In 'Address' enter the original recipient (e.g. support@yourcompany.com); in 'Map to address' paste the CRM address above.",
      "Check 'Also route to original destination' if you want a copy to stay in the support mailbox as well.",
      "Optionally check 'Add X-Gm-Original-To header' to preserve the original recipient info in message headers.",
      'Save the setting. Changes propagate within a few minutes.',
    ],
    docsUrl:
      'https://knowledge.workspace.google.com/admin/gmail/advanced/redirect-or-forward-gmail-messages-to-another-user',
    placeholder: false,
  },
  outlook_com: {
    key: 'outlook_com',
    title: 'Outlook.com (personal)',
    steps: [
      "Open Outlook.com → Settings (gear) → 'View all Outlook settings' → Mail → Forwarding.",
      "Turn on 'Enable forwarding' and paste the CRM address above.",
      "Check 'Keep a copy of forwarded messages' if you want mail to stay in Outlook.com too.",
      'Save. Microsoft may prompt for a verification link — click through the confirmation email in the CRM inbox.',
    ],
    docsUrl: null,
    placeholder: true,
  },
  outlook_365: {
    key: 'outlook_365',
    title: 'Microsoft 365 / Exchange (admin)',
    steps: [
      'Open the Exchange admin center (EAC) → Mail flow → Rules.',
      "Click '+ Add rule' → 'Create a new rule'.",
      "Give the rule a name (e.g. 'CRM support forwarding'). Under 'Apply this rule if…' choose 'The recipient is…' and pick the mailbox to forward from.",
      "Under 'Do the following…' choose 'Redirect the message to…' (or 'Bcc the message to…' if you want to keep a copy) and paste the CRM address above.",
      "Set the rule mode to Enforce and save. If the outbound spam policy blocks external forwarding, first exempt the CRM inbound domain in Defender → Anti-spam outbound → 'Automatic forwarding rules' → 'On'.",
    ],
    docsUrl:
      'https://learn.microsoft.com/en-us/exchange/policy-and-compliance/mail-flow-rules/mail-flow-rules',
    placeholder: false,
  },
  zoho: {
    key: 'zoho',
    title: 'Zoho Mail',
    steps: [
      "Log in to Zoho Mail → Settings → Mail Accounts. Select the mailbox you're forwarding from.",
      "Scroll to the 'Forwards' section. Enter the CRM address above and save.",
      'Zoho sends a confirmation email to the CRM address. Open the CRM inbox, copy the code, come back to Mail Accounts → click the Verify icon → paste the code → click Confirm.',
      "Optionally check 'Delete original email copy after forwarding' if you don't want a copy to stay in Zoho.",
      'Note: Zoho auto-disables forwarding after 10 consecutive delivery failures — if the CRM inbox goes silent, re-verify here first.',
    ],
    docsUrl: 'https://www.zoho.com/mail/help/email-forwarding.html',
    placeholder: false,
  },
  custom: {
    key: 'custom',
    title: 'Custom mail server (IMAP / cPanel / Sieve)',
    steps: [
      "Not on the shipped provider list? Reach out to CRM support with your mail provider's name and we'll walk you through the forwarding-rule syntax.",
      'In the meantime, if you administer your own server: create a server-side forward / redirect rule from your support mailbox to the CRM address above. The rule should NOT keep a local copy if you want the CRM to be the single source of truth.',
    ],
    docsUrl: null,
    placeholder: true,
  },
};

export const PROVIDER_ORDER: string[] = [
  'gmail',
  'google_workspace',
  'outlook_com',
  'outlook_365',
  'zoho',
  'custom',
];
