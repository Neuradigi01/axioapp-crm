/**
 * Public surface of the in-app billing module.
 *
 * Feature modules that need to gate UI on plan tier import from this
 * barrel rather than the per-component file paths — keeps the
 * cross-feature import edges shallow and lets the billing internals
 * reorganise without rippling.
 *
 * Usage:
 *   ```ts
 *   import { LockedFeatureComponent, RequiresFeatureDirective } from
 *     '@app/features/user/core/billing';
 *   ```
 */
export { LockedFeatureComponent } from './components/locked-feature/locked-feature.component';
export type { LockedFeatureVariant } from './components/locked-feature/locked-feature.component';
export { RequiresFeatureDirective } from './components/locked-feature/requires-feature.directive';
export { FeatureAccessService } from './services/feature-access.service';
export type { PlanCode } from './services/feature-access.service';
export { UpgradeModalService } from './services/upgrade-modal.service';
