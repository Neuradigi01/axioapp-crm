import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { ModuleApiService, ModuleDescriptorOut } from '../services/module-api.service';

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [RouterLink, RouterLinkActive, LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './sidebar.component.html',
})
export class SidebarComponent implements OnInit {
  private readonly moduleApi = inject(ModuleApiService);

  readonly open = input.required<boolean>();
  readonly toggle = output<void>();

  protected readonly modules = signal<ModuleDescriptorOut[]>([]);
  protected readonly error = signal<string | null>(null);

  ngOnInit(): void {
    this.moduleApi.list().subscribe({
      next: (mods) => this.modules.set(mods),
      error: () => this.error.set('Could not load modules.'),
    });
  }
}
