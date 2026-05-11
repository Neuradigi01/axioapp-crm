import { Injectable } from '@angular/core';
import { IDeviceInfo } from '@app/schemas/auth';

@Injectable({ providedIn: 'root' })
export class DeviceInfoService {

  collect(): IDeviceInfo {
    const ua = navigator.userAgent;
    return {
      browser: this.detectBrowser(ua),
      browser_version: this.detectBrowserVersion(ua),
      device: this.detectDevice(ua),
      device_type: this.detectDeviceType(ua),
      os: this.detectOS(ua),
      os_version: this.detectOSVersion(ua),
      user_agent: ua,
    };
  }

  private detectBrowser(ua: string): string {
    if (ua.includes('Edg/')) return 'Edge';
    if (ua.includes('OPR/') || ua.includes('Opera')) return 'Opera';
    if (ua.includes('Chrome') && !ua.includes('Edg')) return 'Chrome';
    if (ua.includes('Safari') && !ua.includes('Chrome')) return 'Safari';
    if (ua.includes('Firefox')) return 'Firefox';
    return 'Unknown';
  }

  private detectBrowserVersion(ua: string): string {
    const patterns: [string, RegExp][] = [
      ['Edge', /Edg\/(\d+[\d.]*)/],
      ['Opera', /OPR\/(\d+[\d.]*)/],
      ['Chrome', /Chrome\/(\d+[\d.]*)/],
      ['Safari', /Version\/(\d+[\d.]*)/],
      ['Firefox', /Firefox\/(\d+[\d.]*)/],
    ];
    for (const [, regex] of patterns) {
      const match = ua.match(regex);
      if (match) return match[1];
    }
    return '';
  }

  private detectDevice(ua: string): string {
    const match = ua.match(/\(([^)]+)\)/);
    if (!match) return 'Unknown';
    const info = match[1];
    if (/iPhone/.test(info)) return 'iPhone';
    if (/iPad/.test(info)) return 'iPad';
    if (/Android/.test(info)) {
      const model = info.match(/;\s*([^;)]+)\s*Build/);
      return model ? model[1].trim() : 'Android Device';
    }
    if (/Macintosh/.test(info)) return 'Mac';
    if (/Windows/.test(info)) return 'PC';
    if (/Linux/.test(info)) return 'Linux PC';
    return 'Unknown';
  }

  private detectDeviceType(ua: string): string {
    if (/Mobi|Android.*Mobile|iPhone/.test(ua)) return 'Mobile';
    if (/iPad|Android(?!.*Mobile)|Tablet/.test(ua)) return 'Tablet';
    return 'Desktop';
  }

  private detectOS(ua: string): string {
    if (ua.includes('Windows')) return 'Windows';
    if (ua.includes('Mac OS X') || ua.includes('Macintosh')) return 'macOS';
    if (ua.includes('iPhone') || ua.includes('iPad')) return 'iOS';
    if (ua.includes('Android')) return 'Android';
    if (ua.includes('Linux')) return 'Linux';
    if (ua.includes('CrOS')) return 'Chrome OS';
    return 'Unknown';
  }

  private detectOSVersion(ua: string): string {
    const patterns: RegExp[] = [
      /Windows NT (\d+[\d.]*)/,
      /Mac OS X (\d+[_.\d]*)/,
      /iPhone OS (\d+[_.\d]*)/,
      /Android (\d+[\d.]*)/,
    ];
    for (const regex of patterns) {
      const match = ua.match(regex);
      if (match) return match[1].replace(/_/g, '.');
    }
    return '';
  }
}
