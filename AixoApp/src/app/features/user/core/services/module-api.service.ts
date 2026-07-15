import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';

export interface ModuleDescriptorOut {
  id: string;
  name: string;
  icon: string;
  layer: 'core' | 'pack';
  route: string;
  frontend_route: string;
  permissions: string[];
  menu_position: number;
  parent: string | null;
}

@Injectable({ providedIn: 'root' })
export class ModuleApiService {
  private readonly http = inject(HttpClient);

  list(): Observable<ModuleDescriptorOut[]> {
    return this.http.get<ModuleDescriptorOut[]>(`${environment.apiBaseUrl}/modules`);
  }
}
