import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { AnalysisBrief, Coupon, HistorySeries } from '../core/models';
import { AnalysisBadge } from './analysis-badge';
import { CouponCard } from './coupon-card';
import { PriceChart } from './price-chart';

const providers = [provideHttpClient(), provideHttpClientTesting()];

describe('PriceChart', () => {
  beforeEach(() => TestBed.configureTestingModule({ imports: [PriceChart], providers }));

  function render(series: HistorySeries[], target: number | null = null) {
    const f = TestBed.createComponent(PriceChart);
    f.componentRef.setInput('series', series);
    f.componentRef.setInput('target', target);
    f.detectChanges();
    return f.nativeElement as HTMLElement;
  }

  it('breaks the line when the product was unavailable (no invented price)', () => {
    const el = render([
      {
        offer_id: 1,
        store: 'kabum',
        points: [
          { t: '2026-11-01T12:00:00Z', price_cents: 100000, available: true, source: 'auto' },
          { t: '2026-11-02T12:00:00Z', price_cents: null, available: false, source: 'auto' },
          { t: '2026-11-03T12:00:00Z', price_cents: 90000, available: true, source: 'auto' },
        ],
      },
    ]);
    const d = el.querySelector('path')!.getAttribute('d')!;
    expect((d.match(/M/g) ?? []).length).toBe(2); // dois trechos separados
    expect(el.querySelectorAll('circle').length).toBe(2);
  });

  it('marks manual prices with a hollow marker and shows the target line', () => {
    const el = render(
      [
        {
          offer_id: 2,
          store: 'pichau',
          points: [{ t: '2026-11-01T12:00:00Z', price_cents: 50000, available: true, source: 'manual' }],
        },
      ],
      45000,
    );
    expect(el.querySelector('circle')!.getAttribute('fill')).toBe('var(--pw-surface)');
    expect(el.querySelector('line.target')).toBeTruthy();
    expect(el.textContent).toContain('Informado por você');
  });
});

describe('CouponCard', () => {
  beforeEach(() => TestBed.configureTestingModule({ imports: [CouponCard], providers }));

  const base: Coupon = {
    id: 1, store: 'kabum', code: 'SSD10', description: 'em SSD selecionados', discount_percent: 10,
    discount_cents: null, max_discount_cents: null, min_purchase_cents: null, categories: null,
    conditions: null, valid_from: null, valid_until: null, link_url: null, source: 'Página oficial',
    origin: 'kabum_official', verification_status: 'unconfirmed', validity: 'active', last_seen_at: null,
    created_at: '2026-11-17T00:00:00Z',
  };

  it('shows discount and never claims an unverified coupon works', () => {
    const f = TestBed.createComponent(CouponCard);
    f.componentRef.setInput('coupon', base);
    f.detectChanges();
    const text = (f.nativeElement as HTMLElement).textContent!;
    expect(text).toContain('10% OFF');
    expect(text).toContain('Não confirmado');
    expect(text).not.toContain('Funcionou com você');
  });

  it('formats fixed-value coupons and hides delete for official ones', () => {
    const f = TestBed.createComponent(CouponCard);
    f.componentRef.setInput('coupon', { ...base, discount_percent: null, discount_cents: 5000 });
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;
    expect(el.textContent!.replace(/\s/g, ' ')).toContain('R$ 50 OFF');
    expect(el.querySelector('[aria-label="Excluir cupom"]')).toBeNull();
  });
});

describe('AnalysisBadge', () => {
  beforeEach(() => TestBed.configureTestingModule({ imports: [AnalysisBadge] }));

  it('hides "insufficient data" in lists when asked', () => {
    const a: AnalysisBrief = { classification: 'insufficient', label: 'Dados insuficientes', tone: 'muted', headline: null };
    const f = TestBed.createComponent(AnalysisBadge);
    f.componentRef.setInput('analysis', a);
    f.componentRef.setInput('hideInsufficient', true);
    f.detectChanges();
    expect((f.nativeElement as HTMLElement).textContent!.trim()).toBe('');
    f.componentRef.setInput('hideInsufficient', false);
    f.detectChanges();
    expect((f.nativeElement as HTMLElement).textContent).toContain('Dados insuficientes');
  });
});
