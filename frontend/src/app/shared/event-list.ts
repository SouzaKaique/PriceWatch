import { DatePipe } from '@angular/common';
import { Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';

import { EventKind, PriceEvent } from '../core/models';

const META: Record<EventKind, { icon: string; tone: string; label: string }> = {
  price_drop: { icon: 'bi-graph-down-arrow', tone: 'green', label: 'Queda de preço' },
  price_increase: { icon: 'bi-graph-up-arrow', tone: 'red', label: 'Aumento de preço' },
  back_in_stock: { icon: 'bi-box-seam', tone: 'blue', label: 'Voltou ao estoque' },
  out_of_stock: { icon: 'bi-slash-circle', tone: 'orange', label: 'Indisponível' },
  lowest_ever: { icon: 'bi-trophy', tone: 'green', label: 'Menor preço registrado' },
  target_reached: { icon: 'bi-bullseye', tone: 'green', label: 'Preço-alvo atingido' },
  better_store: { icon: 'bi-shop', tone: 'blue', label: 'Oferta melhor em outra loja' },
  opportunity: { icon: 'bi-stars', tone: 'green', label: 'Oportunidade identificada' },
  misleading_promo: { icon: 'bi-exclamation-triangle', tone: 'red', label: 'Possível promoção enganosa' },
  coupon_available: { icon: 'bi-ticket-perforated', tone: 'blue', label: 'Cupom disponível' },
};

@Component({
  selector: 'app-event-list',
  imports: [DatePipe, RouterLink],
  template: `
    <ul class="list-unstyled mb-0 d-grid gap-2">
      @for (e of events(); track e.id) {
        @let m = meta[e.kind];
        <li class="d-flex gap-2 align-items-start small">
          <span class="badge-soft {{ m.tone }} ev-icon" [title]="m.label"><i class="bi {{ m.icon }}"></i></span>
          <div class="min-w-0">
            @if (linkProducts() && e.product_id) {
              <a class="text-body text-decoration-none" [routerLink]="['/produtos', e.product_id]">{{ e.message }}</a>
            } @else {
              <span>{{ e.message }}</span>
            }
            <div class="text-muted-pw" style="font-size: 0.72rem">
              {{ m.label }} · {{ e.created_at | date: 'dd/MM/yyyy HH:mm' }}
            </div>
          </div>
        </li>
      } @empty {
        <li class="small text-muted-pw">{{ emptyText() }}</li>
      }
    </ul>
  `,
  styles: `
    .ev-icon { display: inline-flex; align-items: center; justify-content: center; width: 1.8rem; height: 1.8rem; flex: none; padding: 0; }
  `,
})
export class EventList {
  readonly events = input.required<PriceEvent[]>();
  readonly linkProducts = input(false);
  readonly emptyText = input('Nenhuma alteração relevante registrada ainda.');
  protected readonly meta = META;
}
