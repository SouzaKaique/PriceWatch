import { DecimalPipe } from '@angular/common';
import { Component, computed, inject, input } from '@angular/core';
import { RouterLink } from '@angular/router';

import { BrlPipe } from '../core/money';
import { Product } from '../core/models';
import { StoreService } from '../core/store.service';
import { ProductImage } from './product-image';

/** Produto com preço bom: card grande no topo do dashboard. */
@Component({
  selector: 'app-deal-card',
  imports: [RouterLink, BrlPipe, DecimalPipe, ProductImage],
  template: `
    @let p = product();
    @let s = p.summary;
    <article class="deal h-100">
      <a [routerLink]="['/produtos', p.id]" class="img-link" [attr.aria-label]="p.name">
        <app-product-image [src]="p.display_image_url" [alt]="p.name" [category]="p.category" ratio="1 / 1" />
      </a>
      <div class="content min-w-0">
        <span class="label"><i class="bi" [class.bi-bullseye]="s.highlight?.reason === 'target'"
          [class.bi-stars]="s.highlight?.reason !== 'target'"></i>{{ s.highlight?.label }}</span>
        <a class="name" [routerLink]="['/produtos', p.id]" [title]="p.name">{{ p.name }}</a>
        <div class="price-row">
          <span class="price tabular">{{ s.best_price_cents | brl }}</span>
          <span class="store-chip" [attr.data-store]="s.best_store">{{ stores.name(s.best_store) }}</span>
        </div>
        <ul class="why">
          @if (s.target_reached && p.target_price_cents !== null) {
            <li><i class="bi bi-check2-circle"></i>
              @if (belowTarget()) { {{ belowTarget() | brl }} abaixo do seu alvo ({{ p.target_price_cents | brl }}) }
              @else { No seu preço-alvo ({{ p.target_price_cents | brl }}) }
            </li>
          }
          @if (s.analysis?.real_discount_pct; as pct) {
            @if (pct > 0) {
              <li><i class="bi bi-graph-down-arrow"></i>{{ pct | number: '1.0-0' }}% abaixo do preço habitual
                ({{ s.analysis!.baseline_cents | brl }})</li>
            }
          }
          @if (isLowest()) { <li><i class="bi bi-trophy"></i>Menor preço já registrado</li> }
        </ul>
        <div class="d-flex flex-wrap gap-2 mt-auto">
          @if (s.best_url) {
            <a class="btn btn-primary btn-sm" [href]="s.best_url" target="_blank" rel="noopener noreferrer">
              Ver na loja <i class="bi bi-box-arrow-up-right ms-1"></i>
            </a>
          }
          <a class="btn btn-outline-secondary btn-sm" [routerLink]="['/produtos', p.id]">Detalhes</a>
        </div>
      </div>
    </article>
  `,
  styles: `
    .deal {
      display: grid; grid-template-columns: 9.5rem 1fr; gap: 1rem; padding: 0.85rem;
      border-radius: var(--pw-radius); border: 1px solid rgba(180, 240, 90, 0.35);
      background:
        radial-gradient(120% 140% at 100% 0%, rgba(180, 240, 90, 0.09), transparent 55%),
        var(--pw-surface);
      box-shadow: 0 0 0 1px rgba(180, 240, 90, 0.06), var(--pw-shadow);
    }
    @media (max-width: 420px) { .deal { grid-template-columns: 6.5rem 1fr; gap: 0.8rem; } }
    .img-link { display: block; align-self: start; }
    .content { display: flex; flex-direction: column; padding: 0.15rem 0.2rem; }
    .label {
      align-self: flex-start; display: inline-flex; align-items: center; gap: 0.3rem; font-size: 0.72rem; font-weight: 700;
      color: #0b1120; background: var(--pw-green); padding: 0.22rem 0.6rem; border-radius: 999px;
    }
    .name {
      color: var(--pw-text); text-decoration: none; font-weight: 600; font-size: 1rem; line-height: 1.35; margin: 0.55rem 0 0.4rem;
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
    }
    .name:hover { color: #fff; text-decoration: underline; }
    .price-row { display: flex; align-items: center; flex-wrap: wrap; gap: 0.5rem; }
    .price { font-size: 1.7rem; font-weight: 800; letter-spacing: -0.025em; color: var(--pw-green); line-height: 1.1; }
    .why { list-style: none; padding: 0; margin: 0.55rem 0 0.85rem; font-size: 0.8rem; color: #c6cfdf; }
    .why li { display: flex; gap: 0.4rem; align-items: baseline; margin: 0.15rem 0; }
    .why .bi { color: var(--pw-green); }
  `,
})
export class DealCard {
  readonly product = input.required<Product>();
  protected readonly stores = inject(StoreService);

  protected readonly belowTarget = computed(() => {
    const p = this.product();
    const best = p.summary.best_price_cents;
    return best !== null && p.target_price_cents !== null ? Math.max(p.target_price_cents - best, 0) : 0;
  });

  protected readonly isLowest = computed(() => {
    const s = this.product().summary;
    const lo = s.analysis?.lowest_cents;
    return lo != null && s.best_price_cents !== null && s.best_price_cents <= lo && (this.product().trend.length ?? 0) >= 7;
  });
}
