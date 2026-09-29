# Step 4: Public-file patterns

**Status:** COMPLETED (2026-09-29)
**Depends on:** Step 1
**Blocks:** Step 5

## Goal

Each module declares which of its storage keys logged-out visitors may load through `/files/…`. Core hard-codes no pack paths, and every undeclared key stays private.

## Scope

- **`shared/storage/public_patterns.py` (new)** holds `PublicFilePattern.parse` / `.matches` and `is_public_key`.
  - Patterns have one token per segment:
    - `{uuid}` matches a segment that is a UUID.
    - `*` matches any single segment, and is allowed only as the last segment.
    - Any other token is a literal lowercase folder name.
  - A key matches only when it has exactly the same number of segments as the pattern.
  - A pattern must be scoped to an org and end in `*`.
- **`core/module_registry.py`**:
  - `ModuleDescriptor.public_files: list[str]` is validated in `__post_init__`, so a bad pattern fails at import.
  - `registry.public_file_patterns()` collects the patterns from every module.
- **Declarations**, each in its module's `module.py`:
  - catalog: `catalog/{uuid}/*`
  - ai_assistants: `{uuid}/ai_assistants/{uuid}/profile/*`
  - furniture inventory: `{uuid}/inventory/{uuid}/*`
  - furniture field_ops: `{uuid}/field_visits/{uuid}/*`
  - furniture custom_orders: `{uuid}/custom_orders/{uuid}/*`
  - real_estate property: `{uuid}/property/{uuid}/*`

This deviates from the plan's earlier `register_public_prefix()` idea. A field on the existing descriptor is the registry pattern modules already use, and it avoids adding a second registry.

## Test

`tests/shared/test_public_file_patterns.py`:
- Invalid patterns are rejected: unscoped, a non-final `*`, `**`, uppercase, `..` and empty segments.
- A descriptor with a bad pattern raises an error.
- Every real image key shape written by the six modules is public.
- These keys are not public:
  - call recordings, imports (both layouts), `messages/`, `quarantine/`
  - the AI `.bin` knowledge file
  - a key with "profile" in the wrong position, or with extra nesting
  - an org segment that isn't a UUID
  - a traversal key, or an empty key
