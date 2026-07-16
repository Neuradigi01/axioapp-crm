import { Injectable, inject } from '@angular/core';
import { HttpHelperService } from '@core/services/http-helper.service';
import { IApiResponse } from '@app/schemas/common';
import { IUserProfile, IUserDashboardData, IUpdateUserProfileRequest } from '@app/schemas/user';

@Injectable({ providedIn: 'root' })
export class UserApiService {
  private readonly http = inject(HttpHelperService);

  getProfile(): Promise<IApiResponse<IUserProfile>> {
    return this.http.Get<IUserProfile>('/user/profile');
  }

  updateProfile(payload: IUpdateUserProfileRequest): Promise<IApiResponse> {
    return this.http.Put('/user/profile', payload);
  }

  uploadProfileImage(file: File): Promise<IApiResponse<{ profile_image: string }>> {
    return this.http.Upload<{ profile_image: string }>('/user/profile/image', file);
  }

  removeProfileImage(): Promise<IApiResponse> {
    return this.http.Delete('/user/profile/image');
  }

  getDashboard(): Promise<IApiResponse<IUserDashboardData>> {
    return this.http.Get<IUserDashboardData>('/user/dashboard');
  }
}
