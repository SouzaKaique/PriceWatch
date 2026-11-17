import { Component, computed, input } from '@angular/core';

import { AnalysisBrief, Classification } from '../core/models';

export const CLASS_ICON: Record<Classification, string> = {
  great: 'bi-stars',
  good: 'bi-hand-thumbs-up',
  average: 'bi-dash-circle',
  above: 'bi-arrow-up-circle',
  weak_discount: 'bi-tag',
  misleading: 'bi-exclamation-triangle',
  insufficient: 'bi-hourglass-split',
};

/** Selo da classificação de preço (ícone + texto; nunca só cor). */
@Component({
  selector: 'app-analysis-badge',
  template: `
    @if (show()) {
      @let a = analysis()!;
      <span class="badge-soft {{ a.tone }} d-inline-flex align-items-center gap-1" [title]="a.headline ?? ''">
        <i class="bi {{ icon() }}"></i>{{ a.label }}
      </span>
    }
  `,
})
export class AnalysisBadge {
  readonly analysis = input<AnalysisBrief | null | undefined>(null);
  /** Esconde "Dados insuficientes" (útil em listas). */
  readonly hideInsufficient = input(false);

  protected readonly show = computed(() => {
    const a = this.analysis();
    return !!a && !(this.hideInsufficient() && a.classification === 'insufficient');
  });
  protected readonly icon = computed(() => CLASS_ICON[this.analysis()?.classification ?? 'insufficient']);
}
