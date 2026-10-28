import {
  ComponentRef,
  Directive,
  EmbeddedViewRef,
  Input,
  OnDestroy,
  TemplateRef,
  ViewContainerRef,
  effect,
  inject,
} from '@angular/core';

import { FeatureAccessService } from '../../services/feature-access.service';
import { LockedFeatureComponent } from './locked-feature.component';

type DetachedView =
  | { kind: 'projected'; ref: EmbeddedViewRef<unknown> }
  | { kind: 'else'; ref: EmbeddedViewRef<unknown> }
  | { kind: 'locked'; ref: ComponentRef<LockedFeatureComponent> };

/**
 * `*crmRequiresFeature` — render the projected content only when the
 * org's current plan grants the given feature key.
 *
 * Two valid shapes:
 *
 * 1. Bare check (no else template, nothing fancy):
 *    ```html
 *    <div *crmRequiresFeature="'integrations.whatsapp'">…</div>
 *    ```
 *    Renders nothing when the user lacks the feature.
 *
 * 2. Explicit fallback template:
 *    ```html
 *    <div *crmRequiresFeature="'automation.workflows'; else lockedTile">
 *      …
 *    </div>
 *    <ng-template #lockedTile>
 *      <crm-locked-feature feature="automation.workflows" />
 *    </ng-template>
 *    ```
 *
 * 3. Shortcut to the default locked tile (no `else` template needed):
 *    ```html
 *    <div *crmRequiresFeature="'integrations.whatsapp'; lockedFallback: true">
 *      …
 *    </div>
 *    ```
 *
 * While the subscription is still loading (`current()` returns `null`),
 * the directive renders nothing — better than flashing the locked
 * tile and immediately replacing it with the real content.
 */
@Directive({
  selector: '[crmRequiresFeature]',
  standalone: true,
})
export class RequiresFeatureDirective implements OnDestroy {
  private readonly templateRef = inject<TemplateRef<unknown>>(TemplateRef);
  private readonly viewContainer = inject(ViewContainerRef);
  private readonly access = inject(FeatureAccessService);

  private featureKey: string | null = null;
  private elseTemplate: TemplateRef<unknown> | null = null;
  private useLockedFallback = false;
  private currentView: DetachedView | null = null;

  @Input({ required: true })
  set crmRequiresFeature(value: string) {
    this.featureKey = value;
    this.render();
  }

  @Input()
  set crmRequiresFeatureElse(value: TemplateRef<unknown> | null) {
    this.elseTemplate = value ?? null;
    this.render();
  }

  @Input()
  set crmRequiresFeatureLockedFallback(value: boolean) {
    this.useLockedFallback = value === true;
    this.render();
  }

  constructor() {
    // Re-render whenever the org's current plan changes (paid upgrade
    // takes effect mid-session, free trial downgrade, etc.).
    effect(() => {
      // Touching the signal subscribes us to changes.
      this.access.currentPlan();
      this.render();
    });
  }

  ngOnDestroy(): void {
    this.detach();
  }

  private render(): void {
    if (this.featureKey === null) return;
    const plan = this.access.currentPlan();

    if (plan === null) {
      // Subscription still loading — render nothing.
      this.detach();
      return;
    }

    if (this.access.hasFeature(this.featureKey)) {
      this.ensureView('projected');
      return;
    }

    if (this.elseTemplate !== null) {
      this.ensureView('else');
      return;
    }

    if (this.useLockedFallback) {
      this.ensureView('locked');
      return;
    }

    this.detach();
  }

  private ensureView(kind: DetachedView['kind']): void {
    if (this.currentView !== null && this.currentView.kind === kind) {
      return;
    }
    this.detach();
    switch (kind) {
      case 'projected': {
        const ref = this.viewContainer.createEmbeddedView(this.templateRef);
        this.currentView = { kind, ref };
        return;
      }
      case 'else': {
        if (this.elseTemplate === null) return;
        const ref = this.viewContainer.createEmbeddedView(this.elseTemplate);
        this.currentView = { kind, ref };
        return;
      }
      case 'locked': {
        const ref = this.viewContainer.createComponent(LockedFeatureComponent);
        if (this.featureKey !== null) {
          ref.setInput('feature', this.featureKey);
        }
        this.currentView = { kind, ref };
        return;
      }
    }
  }

  private detach(): void {
    if (this.currentView === null) return;
    this.viewContainer.clear();
    this.currentView = null;
  }
}
