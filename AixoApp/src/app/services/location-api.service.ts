import { Injectable, inject } from '@angular/core';
import { HttpHelperService } from '@core/services/http-helper.service';
import { IApiResponse, ICountry, IState } from '@app/schemas/common';

@Injectable({ providedIn: 'root' })
export class LocationApiService {
  private readonly http = inject(HttpHelperService);

  getCountries(): Promise<IApiResponse<ICountry[]>> {
    return this.http.Get<ICountry[]>('/location/countries');
  }

  getStates(countryId: number): Promise<IApiResponse<IState[]>> {
    return this.http.Get<IState[]>(`/location/countries/${countryId}/states`);
  }
}
