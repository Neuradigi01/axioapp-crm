/**
 * Wire shapes for the Property module, mirrored from the backend's
 * `PropertyOut` / `PropertyImageOut` / `PropertyListOut` schemas
 * (see `packs/real_estate/modules/property/schemas.py`). Kept
 * hand-typed for now because the codegen sweep does not currently
 * include the pack modules — flip this to `components['schemas'][…]`
 * once codegen is extended.
 */

export type PropertyStatus = 'draft' | 'published' | 'unpublished' | 'archived' | 'sold';

export type PropertyTypeKey =
  | 'apartment'
  | 'villa'
  | 'plot'
  | 'commercial_office'
  | 'commercial_shop'
  | 'warehouse'
  | 'farmhouse'
  | 'pg_hostel'
  | 'other';

export type PropertyCategoryKey =
  | 'residential_sale'
  | 'residential_rent'
  | 'commercial_sale'
  | 'commercial_rent'
  | 'land_sale';

export interface PropertyImage {
  id: string;
  image_url: string | null;
  image_path: string;
  display_order: number;
  is_featured: boolean;
  created_at: string;
}

export interface Property {
  id: string;
  org_id: string;
  owner_id: string;
  title: string;
  slug: string;
  description: string | null;
  property_type: PropertyTypeKey;
  category: PropertyCategoryKey;
  price: string | number | null;
  currency: string;
  address_line: string | null;
  city: string | null;
  state: string | null;
  country: string | null;
  pincode: string | null;
  bedrooms: number | null;
  bathrooms: number | null;
  area_value: string | number | null;
  area_unit: string | null;
  amenities: string[];
  contact_person: string | null;
  contact_phone: string | null;
  contact_email: string | null;
  status: PropertyStatus;
  published_at: string | null;
  archived_at: string | null;
  sold_at: string | null;
  custom_data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  images: PropertyImage[];
  featured_image_url: string | null;
}

export interface PropertyListFilters {
  statuses?: PropertyStatus[];
  property_type?: PropertyTypeKey;
  category?: PropertyCategoryKey;
  city?: string;
  search?: string;
  owner_id?: string;
  min_price?: number;
  max_price?: number;
  sort_by?: 'created_at' | 'updated_at' | 'price' | 'title';
  sort_desc?: boolean;
}

export interface PropertyListResponse {
  items: Property[];
  total: number;
  page: number;
  page_size: number;
  status_counts: Partial<Record<PropertyStatus, number>>;
}

export interface PropertyCreate {
  title: string;
  property_type: PropertyTypeKey;
  category: PropertyCategoryKey;
  description?: string | null;
  price?: number | null;
  currency?: string | null;
  address_line?: string | null;
  city?: string | null;
  state?: string | null;
  country?: string | null;
  pincode?: string | null;
  bedrooms?: number | null;
  bathrooms?: number | null;
  area_value?: number | null;
  area_unit?: string | null;
  amenities?: string[];
  contact_person?: string | null;
  contact_phone?: string | null;
  contact_email?: string | null;
  custom_data?: Record<string, unknown>;
}

export type PropertyUpdate = Partial<PropertyCreate>;

export interface PublicUrlResponse {
  url: string;
  token: string;
}

/** Tabs shown on the owner dashboard, in display order.
 * ``all`` is a client-side pseudo-status that maps to "no `statuses`
 * filter" on the API call. */
export const PROPERTY_TABS = [
  { key: 'all', label: 'All' },
  { key: 'draft', label: 'Draft' },
  { key: 'published', label: 'Published' },
  { key: 'unpublished', label: 'Unpublished' },
  { key: 'archived', label: 'Archived' },
  { key: 'sold', label: 'Sold' },
] as const;

export type PropertyTabKey = (typeof PROPERTY_TABS)[number]['key'];

/** Human-readable option lists for the create/edit form dropdowns.
 * Keys match the backend enums; labels stay UI-only. */
export const PROPERTY_TYPE_OPTIONS: ReadonlyArray<{ key: PropertyTypeKey; label: string }> = [
  { key: 'apartment', label: 'Apartment' },
  { key: 'villa', label: 'Villa' },
  { key: 'plot', label: 'Plot' },
  { key: 'commercial_office', label: 'Commercial Office' },
  { key: 'commercial_shop', label: 'Commercial Shop' },
  { key: 'warehouse', label: 'Warehouse' },
  { key: 'farmhouse', label: 'Farmhouse' },
  { key: 'pg_hostel', label: 'PG / Hostel' },
  { key: 'other', label: 'Other' },
];

export const PROPERTY_CATEGORY_OPTIONS: ReadonlyArray<{ key: PropertyCategoryKey; label: string }> =
  [
    { key: 'residential_sale', label: 'Residential — Sale' },
    { key: 'residential_rent', label: 'Residential — Rent' },
    { key: 'commercial_sale', label: 'Commercial — Sale' },
    { key: 'commercial_rent', label: 'Commercial — Rent' },
    { key: 'land_sale', label: 'Land — Sale' },
  ];

export const AREA_UNIT_OPTIONS: ReadonlyArray<{ key: string; label: string }> = [
  { key: 'sqft', label: 'sqft' },
  { key: 'sqm', label: 'sqm' },
  { key: 'acres', label: 'acres' },
  { key: 'cents', label: 'cents' },
  { key: 'gaj', label: 'gaj' },
];

/** Client-side upload constraints — must match the backend validator
 * in `shared/files/image.py` (5 MB, JPEG/PNG/WebP). Kept here so the
 * gallery can pre-reject before hitting the multipart endpoint. */
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
export const ALLOWED_IMAGE_MIME: ReadonlySet<string> = new Set([
  'image/jpeg',
  'image/png',
  'image/webp',
]);
export const MAX_UPLOAD_BATCH = 20;
