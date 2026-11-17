import { DatePipe } from '@angular/common';
import {
  Component,
  ElementRef,
  OnDestroy,
  afterNextRender,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';

import { BrlPipe, formatCents } from '../core/money';
import { HistorySeries, StoreKey } from '../core/models';
import { StoreService } from '../core/store.service';

/** Cor fixa por loja (segue a entidade, nunca a posição). Validada no tema escuro. */
export const STORE_COLORS: Record<string, string> = {
  kabum: 'var(--pw-series-1)',
  pichau: 'var(--pw-series-2)',
  mercadolivre: 'var(--pw-series-3)',
  amazon: 'var(--pw-series-4)',
};

interface Pt {
  t: number;
  price: number | null;
  manual: boolean;
}
interface Line {
  store: StoreKey;
  name: string;
  color: string;
  pts: Pt[];
  path: string;
  markers: { x: number; y: number; manual: boolean }[];
  end: { x: number; y: number } | null;
}

const PAD = { top: 16, right: 96, bottom: 28, left: 64 };
const HEIGHT = 260;

/** Gráfico de degraus: o preço vale até a consulta seguinte. Nulo = sem preço (lacuna). */
@Component({
  selector: 'app-price-chart',
  imports: [DatePipe, BrlPipe],
  template: `
    <div class="d-flex flex-wrap align-items-center gap-3 mb-2 small" aria-label="Legenda">
      @for (l of lines(); track l.store) {
        <span class="d-inline-flex align-items-center gap-1">
          <span class="legend-swatch" [style.background]="l.color"></span>{{ l.name }}
        </span>
      }
      @if (target() !== null) {
        <span class="d-inline-flex align-items-center gap-1 text-muted-pw">
          <span class="legend-dash"></span>Preço-alvo
        </span>
      }
      @if (hasManual()) {
        <span class="d-inline-flex align-items-center gap-1 text-muted-pw">
          <span class="legend-ring"></span>Informado por você
        </span>
      }
      <button type="button" class="btn btn-link btn-sm ms-auto p-0 text-decoration-none" (click)="showTable.set(!showTable())">
        {{ showTable() ? 'Ver gráfico' : 'Ver tabela' }}
      </button>
    </div>

    @if (showTable()) {
      <div class="table-responsive" style="max-height: 320px">
        <table class="table table-sm small">
          <thead><tr><th>Data</th><th>Loja</th><th class="text-end">Preço</th><th>Obs.</th></tr></thead>
          <tbody>
            @for (r of tableRows(); track $index) {
              <tr>
                <td>{{ r.t | date: 'dd/MM/yyyy HH:mm' }}</td>
                <td>{{ r.name }}</td>
                <td class="text-end tabular">{{ r.price | brl }}</td>
                <td class="text-muted-pw">{{ r.note }}</td>
              </tr>
            }
          </tbody>
        </table>
      </div>
    } @else {
      <div class="chart-wrap" (mousemove)="onMove($event)" (mouseleave)="hover.set(null)">
        <svg [attr.width]="width()" [attr.height]="height" role="img"
          [attr.aria-label]="'Histórico de preços por loja'">
          <!-- grade e eixo Y -->
          @for (tk of yTicks(); track tk.v) {
            <line class="grid" [attr.x1]="pad.left" [attr.x2]="width() - pad.right" [attr.y1]="tk.y" [attr.y2]="tk.y" />
            <text class="axis" [attr.x]="pad.left - 8" [attr.y]="tk.y" text-anchor="end" dominant-baseline="middle">{{ tk.label }}</text>
          }
          <!-- eixo X -->
          @for (tk of xTicks(); track tk.t) {
            <text class="axis" [attr.x]="tk.x" [attr.y]="height - 8" text-anchor="middle">{{ tk.label }}</text>
          }
          <!-- preço-alvo -->
          @if (targetY(); as ty) {
            <line class="target" [attr.x1]="pad.left" [attr.x2]="width() - pad.right" [attr.y1]="ty" [attr.y2]="ty" />
            <text class="axis" [attr.x]="width() - pad.right + 6" [attr.y]="ty" dominant-baseline="middle">alvo</text>
          }
          <!-- séries -->
          @for (l of lines(); track l.store) {
            <path [attr.d]="l.path" fill="none" [attr.stroke]="l.color" stroke-width="2" stroke-linejoin="round" />
            @for (m of l.markers; track $index) {
              <circle [attr.cx]="m.x" [attr.cy]="m.y" r="4"
                [attr.fill]="m.manual ? 'var(--pw-surface)' : l.color" [attr.stroke]="m.manual ? l.color : 'var(--pw-surface)'" stroke-width="2" />
            }
            @if (l.end; as e) {
              <text class="end-label" [attr.x]="e.x + 8" [attr.y]="e.y" dominant-baseline="middle">{{ l.name }}</text>
            }
          }
          <!-- crosshair -->
          @if (hover(); as h) {
            <line class="crosshair" [attr.x1]="h.x" [attr.x2]="h.x" [attr.y1]="pad.top" [attr.y2]="height - pad.bottom" />
          }
        </svg>
        @if (hover(); as h) {
          <div class="tip" [style.left.px]="h.x" [class.flip]="h.x > width() * 0.6">
            <div class="text-muted-pw mb-1">{{ h.t | date: 'dd/MM/yyyy HH:mm' }}</div>
            @for (r of h.rows; track r.name) {
              <div class="d-flex align-items-center gap-2">
                <span class="legend-swatch" [style.background]="r.color"></span>
                <span>{{ r.name }}</span>
                <span class="ms-auto tabular fw-semibold">{{ r.label }}</span>
              </div>
            }
          </div>
        }
      </div>
    }
  `,
  styles: `
    :host { display: block; }
    .chart-wrap { position: relative; }
    svg { display: block; overflow: visible; }
    .grid { stroke: var(--pw-border); stroke-width: 1; }
    .axis { fill: var(--pw-muted); font-size: 11px; font-variant-numeric: tabular-nums; }
    .end-label { fill: var(--pw-text); font-size: 11px; }
    .target { stroke: var(--pw-muted); stroke-width: 1.5; stroke-dasharray: 5 4; }
    .crosshair { stroke: var(--pw-muted); stroke-width: 1; }
    .legend-swatch { width: 10px; height: 10px; border-radius: 3px; display: inline-block; flex: none; }
    .legend-dash { width: 16px; border-top: 2px dashed var(--pw-muted); display: inline-block; }
    .legend-ring { width: 10px; height: 10px; border-radius: 50%; border: 2px solid var(--pw-muted); display: inline-block; }
    .tip {
      position: absolute; top: 8px; transform: translateX(12px); pointer-events: none; min-width: 11rem;
      background: var(--pw-surface-2); border: 1px solid var(--pw-border); border-radius: 0.5rem;
      padding: 0.5rem 0.65rem; font-size: 0.78rem; box-shadow: var(--pw-shadow); z-index: 2;
    }
    .tip.flip { transform: translateX(calc(-100% - 12px)); }
  `,
})
export class PriceChart implements OnDestroy {
  readonly series = input.required<HistorySeries[]>();
  readonly target = input<number | null>(null);

  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly stores = inject(StoreService);
  private observer?: ResizeObserver;

  protected readonly pad = PAD;
  protected readonly height = HEIGHT;
  protected readonly width = signal(640);
  protected readonly showTable = signal(false);
  protected readonly hover = signal<{
    x: number;
    t: number;
    rows: { name: string; color: string; label: string }[];
  } | null>(null);

  constructor() {
    afterNextRender(() => {
      const el = this.host.nativeElement as HTMLElement;
      this.width.set(Math.max(280, el.clientWidth));
      this.observer = new ResizeObserver(([e]) => this.width.set(Math.max(280, Math.floor(e.contentRect.width))));
      this.observer.observe(el);
    });
  }

  ngOnDestroy(): void {
    this.observer?.disconnect();
  }

  private readonly data = computed(() =>
    this.series()
      .filter((s) => s.points.length)
      .map((s) => ({
        store: s.store,
        pts: s.points.map((p) => ({ t: Date.parse(p.t), price: p.price_cents, manual: p.source === 'manual' })),
      })),
  );

  protected readonly hasManual = computed(() => this.data().some((d) => d.pts.some((p) => p.manual)));

  private readonly xDomain = computed<[number, number]>(() => {
    const ts = this.data().flatMap((d) => d.pts.map((p) => p.t));
    if (!ts.length) return [0, 1];
    let [a, b] = [Math.min(...ts), Math.max(...ts)];
    if (a === b) [a, b] = [a - 3_600_000, b + 3_600_000];
    return [a, b];
  });

  private readonly yDomain = computed<[number, number]>(() => {
    const vals = this.data().flatMap((d) => d.pts.map((p) => p.price).filter((v): v is number => v !== null));
    const t = this.target();
    if (t !== null) vals.push(t);
    if (!vals.length) return [0, 1];
    let [a, b] = [Math.min(...vals), Math.max(...vals)];
    const span = Math.max(b - a, b * 0.04);
    a -= span * 0.15;
    b += span * 0.15;
    return [Math.max(0, a), b];
  });

  private x = (t: number) => {
    const [a, b] = this.xDomain();
    return PAD.left + ((t - a) / (b - a)) * (this.width() - PAD.left - PAD.right);
  };
  private y = (v: number) => {
    const [a, b] = this.yDomain();
    return HEIGHT - PAD.bottom - ((v - a) / (b - a)) * (HEIGHT - PAD.top - PAD.bottom);
  };

  protected readonly lines = computed<Line[]>(() => {
    this.width(); // recalcula ao redimensionar
    return this.data().map((d) => {
      let path = '';
      let prev: Pt | null = null;
      const markers: Line['markers'] = [];
      for (const p of d.pts) {
        if (p.price === null) {
          prev = null; // indisponível/sem preço: interrompe a linha
          continue;
        }
        const px = this.x(p.t);
        const py = this.y(p.price);
        if (prev && prev.price !== null) path += ` H${px.toFixed(1)} V${py.toFixed(1)}`;
        else path += ` M${px.toFixed(1)} ${py.toFixed(1)}`;
        markers.push({ x: px, y: py, manual: p.manual });
        prev = p;
      }
      const lastPriced = [...d.pts].reverse().find((p) => p.price !== null);
      return {
        store: d.store,
        name: this.stores.name(d.store),
        color: STORE_COLORS[d.store] ?? 'var(--pw-muted)',
        pts: d.pts,
        path: path.trim(),
        // poucos pontos: mostra todos; muitos: só o último (rótulo direto seletivo)
        markers: markers.length <= 30 ? markers : markers.slice(-1),
        end: lastPriced ? { x: this.x(lastPriced.t), y: this.y(lastPriced.price!) } : null,
      };
    });
  });

  protected readonly targetY = computed(() => {
    this.width();
    const t = this.target();
    return t === null || !this.data().length ? null : this.y(t);
  });

  protected readonly yTicks = computed(() => {
    const [a, b] = this.yDomain();
    const raw = (b - a) / 4;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
    const out = [];
    for (let v = Math.ceil(a / step) * step; v <= b; v += step) {
      out.push({ v, y: this.y(v), label: formatCents(Math.round(v)).replace(',00', '') });
    }
    return out;
  });

  protected readonly xTicks = computed(() => {
    const [a, b] = this.xDomain();
    const n = Math.max(2, Math.min(6, Math.floor((this.width() - PAD.left - PAD.right) / 110)));
    const short = b - a < 2 * 86_400_000;
    const fmt = new Intl.DateTimeFormat('pt-BR', short ? { hour: '2-digit', minute: '2-digit' } : { day: '2-digit', month: '2-digit' });
    const ticks = Array.from({ length: n }, (_, i) => {
      const t = a + ((b - a) * i) / (n - 1);
      return { t, x: this.x(t), label: fmt.format(t) };
    });
    // Intervalos curtos geram rótulos iguais: mantém só a primeira ocorrência.
    return ticks.filter((tk, i) => i === 0 || tk.label !== ticks[i - 1].label);
  });

  protected readonly tableRows = computed(() =>
    this.data()
      .flatMap((d) =>
        d.pts.map((p) => ({
          t: p.t,
          name: this.stores.name(d.store),
          price: p.price,
          note: [p.manual ? 'informado por você' : '', p.price === null ? 'sem preço/indisponível' : '']
            .filter(Boolean)
            .join(' · '),
        })),
      )
      .sort((r1, r2) => r2.t - r1.t),
  );

  onMove(ev: MouseEvent): void {
    const rect = (ev.currentTarget as HTMLElement).getBoundingClientRect();
    const px = Math.min(Math.max(ev.clientX - rect.left, PAD.left), this.width() - PAD.right);
    const [a, b] = this.xDomain();
    const t = a + ((px - PAD.left) / (this.width() - PAD.left - PAD.right)) * (b - a);
    const rows = this.lines().map((l) => {
      const last = [...l.pts].reverse().find((p) => p.t <= t);
      return {
        name: l.name,
        color: l.color,
        label: !last ? 'sem dados' : last.price === null ? 'indisponível' : formatCents(last.price),
      };
    });
    this.hover.set({ x: px, t, rows });
  }
}
