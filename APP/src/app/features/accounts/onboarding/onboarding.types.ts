/**
 * Shapes for the onboarding pack picker.
 *
 * `CatalogTile` mirrors the backend's `CatalogTile` schema (see
 * `api/src/app/core/packs/schemas.py`). Real packs surface as
 * `status="available"`; "Coming soon" placeholders as
 * `status="coming_soon"`.
 */

export type PackStatus = 'available' | 'coming_soon';

export interface CatalogTile {
  pack_id: string;
  name: string;
  description: string;
  icon: string;
  status: PackStatus;
  default_currency: string;
  default_tax_rate: number;
  modules_preview: string[];
  display_order: number;
}

export interface CatalogResponse {
  packs: CatalogTile[];
}
