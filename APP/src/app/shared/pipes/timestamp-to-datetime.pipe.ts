import { Pipe, PipeTransform } from '@angular/core';

@Pipe({
  name: 'timestampToDatetime',
  pure: true,
})
export class TimestampToDatetimePipe implements PipeTransform {
  transform(value: number | null | undefined): string {
    if (value === null || value === undefined) {
      return '';
    }

    return new Date(value * 1000).toLocaleString();
  }
}
