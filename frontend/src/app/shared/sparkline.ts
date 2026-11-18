import { Component, computed, input } from '@angular/core';

/** Mini-gráfico do menor preço por dia (sem eixos; só a tendência). */
@Component({
  selector: 'app-sparkline',
  template: `
    @if (path(); as d) {
      <svg [attr.viewBox]="'0 0 ' + w + ' ' + h" preserveAspectRatio="none" [attr.height]="h" width="100%"
        role="img" [attr.aria-label]="label()">
        <defs>
          <linearGradient [attr.id]="gid" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" [attr.stop-color]="color()" stop-opacity="0.28" />
            <stop offset="1" [attr.stop-color]="color()" stop-opacity="0" />
          </linearGradient>
        </defs>
        <path [attr.d]="d + ' L ' + w + ' ' + h + ' L 0 ' + h + ' Z'" [attr.fill]="'url(#' + gid + ')'" stroke="none" />
        <path [attr.d]="d" fill="none" [attr.stroke]="color()" stroke-width="1.6" stroke-linejoin="round"
          stroke-linecap="round" vector-effect="non-scaling-stroke" />
      </svg>
    } @else {
      <div class="spark-empty" [style.height.px]="h">histórico começa nas próximas consultas</div>
    }
  `,
  styles: `
    :host { display: block; }
    svg { display: block; overflow: visible; }
    .spark-empty { display: flex; align-items: center; font-size: 0.7rem; color: var(--pw-muted); opacity: 0.8; }
  `,
})
export class Sparkline {
  readonly values = input<number[]>([]);
  protected readonly w = 120;
  protected readonly h = 34;
  protected readonly gid = 'sg' + Math.random().toString(36).slice(2, 8);

  /** Verde se o último preço for o menor do período; azul caso contrário. */
  protected readonly color = computed(() => {
    const v = this.values();
    return v.length > 1 && v[v.length - 1] <= Math.min(...v) ? 'var(--pw-green)' : 'var(--pw-blue)';
  });

  protected readonly label = computed(() => `Tendência de ${this.values().length} dia(s)`);

  protected readonly path = computed(() => {
    const v = this.values();
    if (v.length < 2) return null;
    const min = Math.min(...v);
    const max = Math.max(...v);
    const span = max - min || 1;
    const pad = 3;
    return v
      .map((p, i) => {
        const x = (i / (v.length - 1)) * this.w;
        const y = pad + (1 - (p - min) / span) * (this.h - pad * 2);
        return `${i ? 'L' : 'M'} ${x.toFixed(1)} ${y.toFixed(1)}`;
      })
      .join(' ');
  });
}
