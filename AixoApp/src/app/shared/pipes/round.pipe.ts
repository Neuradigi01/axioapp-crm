import { Pipe, PipeTransform } from '@angular/core';

@Pipe({
  name: 'round',
  pure: true,
})
export class RoundPipe implements PipeTransform {
  transform(value: number | null | undefined, decimals: number = 2): string {
    if (value === null || value === undefined) {
      return '';
    }

    const factor = Math.pow(10, decimals);
    return (Math.round(value * factor) / factor).toFixed(decimals);
  }
}
