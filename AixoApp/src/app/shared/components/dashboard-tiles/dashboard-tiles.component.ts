import { Component, ChangeDetectionStrategy, input } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { IDashboardTile } from '@app/schemas/shared';

@Component({
  selector: 'app-dashboard-tiles',
  templateUrl: './dashboard-tiles.component.html',
  styleUrl: './dashboard-tiles.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatIconModule],
})
export class DashboardTilesComponent {
  readonly tiles = input<IDashboardTile[]>([]);
}
