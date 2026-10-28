import { Injectable, inject } from '@angular/core';
import { HttpHelperService } from '@core/services/http-helper.service';
import { IApiResponse, IPaginatedApiResponse } from '@app/schemas/common';
import {
  IAdminDashboardData,
  IAdminProfile,
  IAssignableRoute,
  IChangeUserPasswordRequest,
  ICreateSubAdminRequest,
  IMember,
  IMemberDetail,
  IMemberListRequest,
  ISubAdmin,
  ISubAdminDetail,
  ISubAdminListRequest,
  IToggleStatusRequest,
  IToggleUserStatusRequest,
  IUpdateRoutesRequest,
  IUpdateSubAdminRequest,
} from '@app/schemas/admin';
import { IUpdateUserProfileRequest } from '@app/schemas/user';
import { ILoginData } from '@app/schemas/auth';

@Injectable({ providedIn: 'root' })
export class AdminApiService {
  private readonly http = inject(HttpHelperService);

  // ── Dashboard & Profile ──────────────────────────────────────────

  getDashboard(): Promise<IApiResponse<IAdminDashboardData>> {
    return this.http.Get<IAdminDashboardData>('/admin/dashboard');
  }

  getProfile(): Promise<IApiResponse<IAdminProfile>> {
    return this.http.Get<IAdminProfile>('/admin/profile');
  }

  updateProfile(payload: { email: string; mobile_no: string | null }): Promise<IApiResponse> {
    return this.http.Put('/admin/profile', payload);
  }

  uploadProfileImage(file: File): Promise<IApiResponse<{ profile_image: string }>> {
    return this.http.Upload<{ profile_image: string }>('/admin/profile/image', file);
  }

  removeProfileImage(): Promise<IApiResponse> {
    return this.http.Delete('/admin/profile/image');
  }

  // ── Sub-Admin Management ─────────────────────────────────────────

  getSubAdminList(payload: ISubAdminListRequest): Promise<IPaginatedApiResponse<ISubAdmin>> {
    return this.http.Post('/admin/sub-admins/list', payload) as Promise<
      IPaginatedApiResponse<ISubAdmin>
    >;
  }

  createSubAdmin(payload: ICreateSubAdminRequest): Promise<IApiResponse> {
    return this.http.Post('/admin/sub-admins/create', payload);
  }

  getSubAdminDetail(adminId: string): Promise<IApiResponse<ISubAdminDetail>> {
    return this.http.Get<ISubAdminDetail>(`/admin/sub-admins/${adminId}`);
  }

  updateSubAdmin(adminId: string, payload: IUpdateSubAdminRequest): Promise<IApiResponse> {
    return this.http.Put(`/admin/sub-admins/${adminId}`, payload);
  }

  getAssignableRoutes(): Promise<IApiResponse<IAssignableRoute[]>> {
    return this.http.Get<IAssignableRoute[]>('/admin/sub-admins/assignable-routes');
  }

  updateSubAdminRoutes(payload: IUpdateRoutesRequest): Promise<IApiResponse> {
    return this.http.Put('/admin/sub-admins/routes', payload);
  }

  toggleSubAdminStatus(payload: IToggleStatusRequest): Promise<IApiResponse> {
    return this.http.Put('/admin/sub-admins/toggle-status', payload);
  }

  // ── Member (User) Management ───────────────────────────────────────

  getMemberList(payload: IMemberListRequest): Promise<IPaginatedApiResponse<IMember>> {
    return this.http.Post('/admin/users/list', payload) as Promise<IPaginatedApiResponse<IMember>>;
  }

  getMemberDetail(userId: string): Promise<IApiResponse<IMemberDetail>> {
    return this.http.Get<IMemberDetail>(`/admin/users/${userId}`);
  }

  toggleUserStatus(payload: IToggleUserStatusRequest): Promise<IApiResponse> {
    return this.http.Put('/admin/users/toggle-status', payload);
  }

  changeUserPassword(payload: IChangeUserPasswordRequest): Promise<IApiResponse> {
    return this.http.Post('/admin/users/change-password', payload);
  }

  updateUserProfile(userId: string, payload: IUpdateUserProfileRequest): Promise<IApiResponse> {
    return this.http.Put(`/admin/users/${userId}`, payload);
  }

  impersonateUser(userId: string): Promise<IApiResponse<ILoginData>> {
    return this.http.Post<ILoginData>(`/admin/users/${userId}/impersonate`, {});
  }
}
