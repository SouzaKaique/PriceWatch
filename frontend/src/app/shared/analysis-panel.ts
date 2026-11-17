import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, computed, inject, input } from '@angular/core';

import { BrlPipe } from '../core/money';
import { ProductAnalysis } from '../core/models';
import { StoreService } from '../core/store.service';
import { CLASS_ICON } from './analysis-badge';

/** Painel "Inteligência de preço" da página do produto. */
@Component({
  selector: 'app-analysis-panel',
  imports: [BrlPipe, DatePipe, DecimalPipe],
  template: `
    @let a = data().overall;
    @if (!a) {
      <p class="small text-muted-pw mb-0">A análise aparece depois da primeira consulta de preço.</p>
    } @else {
      <div class="verdict tone-{{ a.tone }} mb-3">
        <div class="d-flex align-items-center gap-2 mb-1">
          <i class="bi {{ icon() }} fs-5"></i>
          <strong>{{ a.label }}</strong>
          @if (bestStore()) { <span class="text-muted-pw small">· melhor oferta: {{ bestStore() }}</span> }
        </div>
        <ul class="mb-0 ps-3 small">
          @for (r of a.reasons; track $index) { <li>{{ r }}</li> }
        </ul>
      </div>

      @for (o of alerts(); track o.id) {
        <div class="verdict tone-{{ o.a.tone }} mb-3">
          <div class="d-flex align-items-center gap-2 mb-1 small">
            <i class="bi {{ o.icon }}"></i><strong>{{ o.store }}: {{ o.a.label }}</strong>
          </div>
          <ul class="mb-0 ps-3 small">
            @for (r of o.a.reasons; track $index) { <li>{{ r }}</li> }
          </ul>
        </div>
      }

      <div class="row g-3 small">
        <div class="col-6 col-md-3">
          <div class="text-muted-pw">Preço atual</div>
          <div class="fs-6 fw-semibold tabular">{{ a.metrics.current_cents | brl }}</div>
        </div>
        <div class="col-6 col-md-3">
          <div class="text-muted-pw">Preço habitual</div>
          <div class="fs-6 fw-semibold tabular">{{ a.metrics.baseline_cents | brl }}</div>
          <div class="text-muted-pw" style="font-size: 0.72rem">{{ a.metrics.baseline_method ?? 'histórico insuficiente' }}</div>
        </div>
        <div class="col-6 col-md-3">
          <div class="text-muted-pw">Menor registrado</div>
          @if (data().lowest_overall; as lo) {
            <div class="fs-6 fw-semibold tabular">{{ lo.price_cents | brl }}</div>
            <div class="text-muted-pw" style="font-size: 0.72rem">
              {{ storeName(lo.store) }} · {{ lo.at | date: 'dd/MM/yyyy' }}{{ lo.source === 'manual' ? ' · informado por você' : '' }}
            </div>
          } @else { <div class="fs-6">—</div> }
        </div>
        <div class="col-6 col-md-3">
          <div class="text-muted-pw">Desconto anunciado × real</div>
          @if (a.metrics.announced_discount_pct !== null) {
            <div class="fs-6 fw-semibold tabular">
              {{ a.metrics.announced_discount_pct | number: '1.0-0' }}%
              <span class="text-muted-pw fw-normal">×</span>
              @if (a.metrics.real_discount_pct !== null) {
                <span [class.price-down]="a.metrics.real_discount_pct > 0" [class.price-up]="a.metrics.real_discount_pct < 0">
                  {{ a.metrics.real_discount_pct | number: '1.0-0' }}%
                </span>
              } @else { <span class="text-muted-pw">?</span> }
            </div>
            <div class="text-muted-pw" style="font-size: 0.72rem">"de" {{ a.metrics.announced_list_price_cents | brl }} × habitual</div>
          } @else {
            <div class="fs-6">—</div>
            <div class="text-muted-pw" style="font-size: 0.72rem">a loja não anuncia preço "de"</div>
          }
        </div>
      </div>

      <div class="table-responsive mt-3">
        <table class="table table-sm small mb-0">
          <thead>
            <tr><th>Período</th><th class="text-end">Média</th><th class="text-end">Mínimo</th><th class="text-end">Máximo</th><th class="text-end">Dias com dados</th></tr>
          </thead>
          <tbody>
            @for (w of windowKeys; track w) {
              @let s = a.metrics.windows[w];
              <tr [class.text-muted-pw]="!s.sufficient">
                <td>{{ w }} dias</td>
                @if (s.days_with_data) {
                  <td class="text-end tabular">{{ s.avg_cents | brl }}</td>
                  <td class="text-end tabular">{{ s.min_cents | brl }}</td>
                  <td class="text-end tabular">{{ s.max_cents | brl }}</td>
                } @else {
                  <td class="text-end" colspan="3">sem dados</td>
                }
                <td class="text-end tabular">
                  {{ s.days_with_data }}
                  @if (!s.sufficient) { <i class="bi bi-info-circle ms-1" title="Dados insuficientes para conclusões neste período"></i> }
                </td>
              </tr>
            }
          </tbody>
        </table>
      </div>

      @if (data().promo_context; as p) {
        <div class="small mt-3 d-flex gap-2 text-warning">
          <i class="bi bi-calendar-event"></i>
          <span>
            @if (p.ongoing) { {{ p.name }} em andamento. }
            @else { Período da {{ p.name }} começa em {{ p.days_until }} dia(s) ({{ p.start | date: 'dd/MM' }} a {{ p.end | date: 'dd/MM' }}). }
            É comum o preço subir antes dessas datas para depois "cair" — compare sempre com o preço habitual.
          </span>
        </div>
      }
      <p class="small text-muted-pw mt-2 mb-0">
        Análise baseada só no histórico coletado pelo PRICE WATCH ({{ a.metrics.days_with_data }} dia(s) com preço).
        Preços por dia = mediana das consultas do dia. Classificações são indícios, não acusações.
      </p>
    }
  `,
  styles: `
    .verdict { border-radius: 0.6rem; padding: 0.75rem 0.9rem; border: 1px solid var(--pw-border); background: var(--pw-surface-2); }
    .verdict.tone-green { border-color: rgba(163, 230, 53, 0.45); }
    .verdict.tone-green .bi { color: var(--pw-green); }
    .verdict.tone-orange { border-color: rgba(251, 146, 60, 0.45); }
    .verdict.tone-orange .bi { color: var(--pw-orange); }
    .verdict.tone-red { border-color: rgba(248, 113, 113, 0.5); }
    .verdict.tone-red .bi { color: var(--pw-red); }
  `,
})
export class AnalysisPanel {
  readonly data = input.required<ProductAnalysis>();
  /** Loja da melhor oferta (chave). */
  readonly bestStoreKey = input<string | null>(null);
  /** Ofertas do produto (para nomear lojas nos alertas). */
  readonly offers = input<{ id: number; store: string }[]>([]);

  /** Alertas de outras lojas (promoção enganosa / desconto fraco) além da melhor oferta. */
  protected readonly alerts = computed(() =>
    this.offers()
      .filter((o) => o.id !== this.data().best_offer_id)
      .map((o) => ({ id: o.id, store: this.stores.name(o.store), a: this.data().offers[String(o.id)] }))
      .filter((x) => x.a && (x.a.classification === 'misleading' || x.a.classification === 'weak_discount'))
      .map((x) => ({ ...x, icon: CLASS_ICON[x.a.classification] })),
  );
  private readonly stores = inject(StoreService);
  protected readonly windowKeys = ['7', '30', '90', '180'] as const;

  protected readonly icon = computed(() => CLASS_ICON[this.data().overall?.classification ?? 'insufficient']);
  protected readonly bestStore = computed(() => {
    const key = this.bestStoreKey();
    return key ? this.stores.name(key) : null;
  });

  storeName(key: string): string {
    return this.stores.name(key);
  }
}
