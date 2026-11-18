import { DecimalPipe } from '@angular/common';
import { Component, computed, inject, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';

import { BrlPipe } from '../core/money';
import { Product } from '../core/models';
import { StoreService } from '../core/store.service';
import { CLASS_ICON } from './analysis-badge';
import { ProductImage } from './product-image';
import { Sparkline } from './sparkline';

@Component({
  selector: 'app-product-card',
  imports: [RouterLink, BrlPipe, DecimalPipe, ProductImage, Sparkline],
  template: `
    @let p = product();
    @let s = p.summary;
    <article class="pc h-100" [class.paused]="!p.active" [class.hot]="!!s.highlight">
      <a [routerLink]="['/produtos', p.id]" class="stretched-link" [attr.aria-label]="p.name"></a>

      <app-product-image [src]="p.display_image_url" [alt]="p.name" [category]="p.category">
        @if (s.highlight; as h) {
          <span class="ribbon"><i class="bi bi-stars"></i>{{ h.label }}</span>
        } @else if (s.analysis && s.analysis.classification !== 'insufficient') {
          <span class="ribbon tone-{{ s.analysis.tone }}"><i class="bi {{ icon() }}"></i>{{ s.analysis.label }}</span>
        }
        @if (!p.active) { <span class="paused-chip"><i class="bi bi-pause-fill"></i>Pausado</span> }
      </app-product-image>

      <div class="pc-body">
        <div class="meta text-truncate">{{ subtitle() }}</div>
        <h3 class="name" [title]="p.name">{{ p.name }}</h3>

        <div class="d-flex align-items-end justify-content-between gap-2 mt-auto">
          <div class="min-w-0">
            @if (s.best_price_cents !== null) {
              <div class="price tabular" [class.price-down]="!!s.highlight">{{ s.best_price_cents | brl }}</div>
              <div class="where text-truncate">na {{ stores.name(s.best_store) }}</div>
            } @else {
              <div class="price muted">—</div>
              <div class="where">aguardando a primeira consulta</div>
            }
          </div>
          @if (s.variation_percent !== null && s.variation_percent !== 0) {
            <span class="delta" [class.down]="s.variation_percent < 0" [class.up]="s.variation_percent > 0">
              <i class="bi" [class.bi-arrow-down-right]="s.variation_percent < 0" [class.bi-arrow-up-right]="s.variation_percent > 0"></i>
              {{ s.variation_percent | number: '1.0-1' }}%
            </span>
          }
        </div>

        <app-sparkline class="my-2" [values]="p.trend" />

        @if (p.target_price_cents !== null) {
          <div class="d-flex justify-content-between small mb-1">
            <span class="text-muted-pw">Alvo <span class="text-body tabular">{{ p.target_price_cents | brl }}</span></span>
            @if (s.target_reached) {
              <span class="price-down fw-semibold"><i class="bi bi-check2-circle me-1"></i>atingido</span>
            } @else if (gap() !== null) {
              <span class="text-muted-pw">faltam <span class="text-body tabular">{{ gap() | brl }}</span></span>
            }
          </div>
          <div class="target-bar" [class.hit]="s.target_reached"><span [style.width.%]="progress()"></span></div>
        } @else {
          <div class="small text-muted-pw">Sem preço-alvo definido</div>
        }

        <div class="d-flex align-items-center justify-content-between gap-2 mt-3">
          <div class="d-flex flex-wrap gap-1 min-w-0">
            @for (st of s.stores; track st) {
              <span class="store-chip" [attr.data-store]="st">{{ stores.name(st) }}</span>
            } @empty {
              <span class="small text-muted-pw">sem loja vinculada</span>
            }
          </div>
          <div class="form-check form-switch m-0 toggle" (click)="$event.stopPropagation()">
            <input class="form-check-input" type="checkbox" role="switch" [id]="'active-' + p.id" [checked]="p.active"
              (change)="toggleActive.emit(!p.active)" [attr.aria-label]="p.active ? 'Pausar monitoramento' : 'Ativar monitoramento'"
              [title]="p.active ? 'Monitorando — clique para pausar' : 'Pausado — clique para monitorar'" />
          </div>
        </div>
      </div>
    </article>
  `,
  styles: `
    .pc {
      position: relative; display: flex; flex-direction: column; border-radius: var(--pw-radius);
      background: var(--pw-surface); border: 1px solid var(--pw-border-soft); box-shadow: var(--pw-shadow);
      padding: 0.6rem; transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s;
    }
    .pc:hover { transform: translateY(-2px); box-shadow: var(--pw-shadow-hover); border-color: rgba(79, 140, 255, 0.45); }
    .pc.hot { border-color: rgba(180, 240, 90, 0.45); box-shadow: 0 0 0 1px rgba(180, 240, 90, 0.12), var(--pw-shadow); }
    .pc.paused { opacity: 0.6; }
    .pc-body { display: flex; flex-direction: column; flex: 1; padding: 0.85rem 0.55rem 0.35rem; }
    .meta { font-size: 0.72rem; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--pw-muted); }
    .name {
      font-size: 0.98rem; font-weight: 600; line-height: 1.35; margin: 0.25rem 0 0.9rem;
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; min-height: 2.65em;
    }
    .price { font-size: 1.45rem; font-weight: 750; letter-spacing: -0.02em; line-height: 1.1; }
    .price.muted { color: var(--pw-muted); }
    .where { font-size: 0.78rem; color: var(--pw-muted); margin-top: 0.15rem; }
    .delta { font-size: 0.75rem; font-weight: 650; padding: 0.18rem 0.5rem; border-radius: 999px; white-space: nowrap;
      background: var(--pw-surface-2); color: var(--pw-muted); }
    .delta.down { color: var(--pw-green); background: var(--pw-green-soft); }
    .delta.up { color: var(--pw-red); background: rgba(248, 113, 113, 0.12); }
    .ribbon {
      position: absolute; top: 0.6rem; left: 0.6rem; display: inline-flex; align-items: center; gap: 0.3rem;
      font-size: 0.7rem; font-weight: 700; padding: 0.28rem 0.6rem; border-radius: 999px;
      background: #0b1120; color: var(--pw-green); box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
    }
    .ribbon.tone-orange { color: var(--pw-orange); }
    .ribbon.tone-red { color: var(--pw-red); }
    .ribbon.tone-muted { color: #c6cfdf; }
    .paused-chip {
      position: absolute; top: 0.6rem; right: 0.6rem; font-size: 0.7rem; font-weight: 600; padding: 0.25rem 0.55rem;
      border-radius: 999px; background: rgba(11, 17, 32, 0.85); color: #c6cfdf;
    }
    .toggle { position: relative; z-index: 2; }
  `,
})
export class ProductCard {
  readonly product = input.required<Product>();
  readonly toggleActive = output<boolean>();
  protected readonly stores = inject(StoreService);

  protected readonly subtitle = computed(() => {
    const p = this.product();
    return [p.brand, p.category].filter(Boolean).join(' · ') || 'Produto monitorado';
  });

  protected readonly icon = computed(() => CLASS_ICON[this.product().summary.analysis?.classification ?? 'insufficient']);

  protected readonly gap = computed(() => {
    const p = this.product();
    const best = p.summary.best_price_cents;
    return best !== null && p.target_price_cents !== null ? Math.max(best - p.target_price_cents, 0) : null;
  });

  /** Quão perto o preço está do alvo (100% = atingido). */
  protected readonly progress = computed(() => {
    const p = this.product();
    const best = p.summary.best_price_cents;
    if (p.summary.target_reached) return 100;
    if (best === null || p.target_price_cents === null || best <= 0) return 0;
    return Math.max(4, Math.min(100, (p.target_price_cents / best) * 100));
  });
}
