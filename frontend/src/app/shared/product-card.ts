import { DecimalPipe } from '@angular/common';
import { Component, computed, inject, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';

import { BrlPipe } from '../core/money';
import { Product } from '../core/models';
import { StoreService } from '../core/store.service';
import { AnalysisBadge } from './analysis-badge';

@Component({
  selector: 'app-product-card',
  imports: [RouterLink, BrlPipe, DecimalPipe, AnalysisBadge],
  template: `
    @let p = product();
    @let s = p.summary;
    <article class="card h-100 product-card" [class.paused]="!p.active">
      <a [routerLink]="['/produtos', p.id]" class="stretched-link" [attr.aria-label]="p.name"></a>
      <div class="p-3 d-flex flex-column h-100 gap-3">
        <div class="thumb" [class.empty]="!p.image_url || imgFailed">
          @if (p.image_url && !imgFailed) {
            <img [src]="p.image_url" [alt]="p.name" loading="lazy" (error)="imgFailed = true" />
          } @else {
            <i class="bi bi-box-seam"></i>
          }
        </div>

        <div>
          <h2 class="h6 mb-1 name">{{ p.name }}</h2>
          <div class="small text-muted-pw text-truncate">
            {{ subtitle() }}
          </div>
        </div>

        <div class="mt-auto">
          @if (s.analysis && s.analysis.classification !== 'insufficient') {
            <div class="mb-2"><app-analysis-badge [analysis]="s.analysis" /></div>
          }
          <div class="d-flex align-items-end justify-content-between gap-2">
            <div>
              <div class="eyebrow">Menor preço</div>
              @if (s.best_price_cents !== null) {
                <div class="fs-5 fw-semibold tabular" [class.price-down]="s.target_reached">
                  {{ s.best_price_cents | brl }}
                </div>
                <div class="small text-muted-pw">{{ stores.name(s.best_store) }}</div>
              } @else {
                <div class="small text-muted-pw mt-1">Aguardando consulta</div>
              }
            </div>
            @if (s.variation_percent !== null) {
              <span
                class="badge-soft"
                [class.green]="s.variation_percent < 0"
                [class.red]="s.variation_percent > 0"
                [class.muted]="s.variation_percent === 0"
              >
                <i
                  class="bi"
                  [class.bi-arrow-down-right]="s.variation_percent < 0"
                  [class.bi-arrow-up-right]="s.variation_percent > 0"
                ></i>
                {{ s.variation_percent | number: '1.0-1' }}%
              </span>
            }
          </div>

          <hr class="my-2" />

          <div class="d-flex align-items-center justify-content-between small gap-2">
            <span class="text-muted-pw">
              Alvo:
              <span class="text-body tabular">{{ p.target_price_cents | brl }}</span>
              @if (s.target_reached) {
                <i class="bi bi-bullseye price-down ms-1" title="Preço-alvo atingido"></i>
              }
            </span>
            <div class="form-check form-switch m-0 toggle" (click)="$event.stopPropagation()">
              <input
                class="form-check-input"
                type="checkbox"
                role="switch"
                [id]="'active-' + p.id"
                [checked]="p.active"
                (change)="toggleActive.emit(!p.active)"
                [attr.aria-label]="p.active ? 'Pausar monitoramento' : 'Ativar monitoramento'"
              />
              <label class="form-check-label text-muted-pw" [for]="'active-' + p.id">
                {{ p.active ? 'Ativo' : 'Pausado' }}
              </label>
            </div>
          </div>
          <div class="d-flex flex-wrap gap-1 mt-2">
            @for (st of s.stores; track st) {
              <span class="store-chip">{{ stores.name(st) }}</span>
            } @empty {
              <span class="small text-muted-pw">Nenhuma loja vinculada</span>
            }
          </div>
        </div>
      </div>
    </article>
  `,
  styles: `
    .product-card {
      transition: border-color 0.15s, transform 0.15s;
    }
    .product-card:hover {
      border-color: var(--pw-blue);
    }
    .product-card.paused {
      opacity: 0.6;
    }
    .name {
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
      line-height: 1.35;
    }
    .toggle {
      position: relative;
      z-index: 2;
    }
  `,
})
export class ProductCard {
  readonly product = input.required<Product>();
  readonly toggleActive = output<boolean>();
  protected readonly stores = inject(StoreService);
  protected imgFailed = false;

  protected readonly subtitle = computed(() => {
    const p = this.product();
    return [p.brand, p.model].filter(Boolean).join(' · ') || 'Marca/modelo não informados';
  });
}
