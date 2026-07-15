import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { PropertyListPageComponent } from './property-list.page';
import { PropertyApiService } from './property-api.service';
import type { Property, PropertyListResponse } from './property.types';

function makeProperty(overrides: Partial<Property> = {}): Property {
  return {
    id: 'prop-1',
    org_id: 'org-1',
    owner_id: 'user-1',
    title: 'Sea-facing 3 BHK',
    slug: 'sea-facing-3-bhk',
    description: null,
    property_type: 'apartment',
    category: 'residential_sale',
    price: '25000000',
    currency: 'INR',
    address_line: null,
    city: 'Mumbai',
    state: 'Maharashtra',
    country: 'India',
    pincode: '400001',
    bedrooms: 3,
    bathrooms: 2,
    area_value: '1450',
    area_unit: 'sqft',
    amenities: [],
    contact_person: null,
    contact_phone: null,
    contact_email: null,
    status: 'published',
    published_at: '2026-07-01T00:00:00Z',
    archived_at: null,
    sold_at: null,
    custom_data: {},
    created_at: '2026-07-01T00:00:00Z',
    updated_at: '2026-07-01T00:00:00Z',
    images: [],
    featured_image_url: null,
    ...overrides,
  };
}

describe('PropertyListPageComponent', () => {
  let apiSpy: jasmine.SpyObj<PropertyApiService>;

  function makeFixture(items: Property[] = []): ComponentFixture<PropertyListPageComponent> {
    apiSpy = jasmine.createSpyObj<PropertyApiService>('PropertyApiService', ['list']);
    const response: PropertyListResponse = {
      items,
      total: items.length,
      page: 1,
      page_size: 20,
      status_counts: items.reduce<Record<string, number>>((acc, p) => {
        acc[p.status] = (acc[p.status] ?? 0) + 1;
        return acc;
      }, {}),
    };
    apiSpy.list.and.returnValue(of(response));

    TestBed.configureTestingModule({
      imports: [PropertyListPageComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: PropertyApiService, useValue: apiSpy },
      ],
    });
    const fixture = TestBed.createComponent(PropertyListPageComponent);
    fixture.detectChanges();
    return fixture;
  }

  it('renders empty state when the list is empty', () => {
    const fixture = makeFixture([]);
    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('No properties yet.');
    expect(apiSpy.list).toHaveBeenCalled();
  });

  it('renders rows from the API response', () => {
    const fixture = makeFixture([makeProperty()]);
    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('Sea-facing 3 BHK');
    expect(el.textContent).toContain('Mumbai');
  });

  it('shows counts on tabs from status_counts', () => {
    const fixture = makeFixture([
      makeProperty({ id: 'a', status: 'draft' }),
      makeProperty({ id: 'b', status: 'draft' }),
      makeProperty({ id: 'c', status: 'published' }),
    ]);
    const el = fixture.nativeElement as HTMLElement;
    const tabs = Array.from(el.querySelectorAll('nav button')).map((b) =>
      (b.textContent ?? '').replace(/\s+/g, ' ').trim(),
    );
    // "All 3", "Draft 2", "Published 1", others "0"
    expect(tabs.some((t) => t.startsWith('All') && t.endsWith('3'))).toBeTrue();
    expect(tabs.some((t) => t.startsWith('Draft') && t.endsWith('2'))).toBeTrue();
    expect(tabs.some((t) => t.startsWith('Published') && t.endsWith('1'))).toBeTrue();
  });
});
