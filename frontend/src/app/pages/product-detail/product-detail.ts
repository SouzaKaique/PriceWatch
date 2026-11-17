import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, OnInit, computed, inject, input, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import { ApiService, describeError } from '../../core/api.service';
import { BrlPipe, parseBRL } from '../../core/money';
import {
  Coupon,
  Offer,
  PriceEvent,
  Product,
  ProductAnalysis,
  ProductCouponItem,
  ProductHistory,
} from '../../core/models';
import { StoreService } from '../../core/store.service';
import { AnalysisBadge } from '../../shared/analysis-badge';
import { AnalysisPanel } from '../../shared/analysis-panel';
import { CouponCard } from '../../shared/coupon-card';
import { EventList } from '../../shared/event-list';
import { PriceChart } from '../../shared/price-chart';

@Component({
  selector: 'app-product-detail-page',
  imports: [RouterLink, DatePipe, DecimalPipe, BrlPipe, PriceChart, EventList, AnalysisPanel, AnalysisBadge, CouponCard],
  templateUrl: './product-detail.html',
})
export class ProductDetailPage implements OnInit {
  readonly id = input.required<string>();

  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  protected readonly storeSvc = inject(StoreService);

  protected readonly product = signal<Product | null>(null);
  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly newUrl = signal('');
  protected readonly offerError = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected imgFailed = false;

  /** Ofertas ordenadas: com preço (menor primeiro) e depois as ainda não consultadas. */
  protected readonly offers = computed(() => {
    const list = [...(this.product()?.offers ?? [])];
    const key = (o: Offer) => o.current_price_cents ?? Number.POSITIVE_INFINITY;
    return list.sort((a, b) => key(a) - key(b));
  });

  /** Diferença do menor preço para o preço-alvo (positivo = falta reduzir). */
  protected readonly gapToTarget = computed(() => {
    const p = this.product();
    if (!p || p.target_price_cents === null || p.summary.best_price_cents === null) return null;
    return p.summary.best_price_cents - p.target_price_cents;
  });

  // ---- Histórico e eventos ----
  protected readonly periods = [
    { days: 7, label: '7d' },
    { days: 30, label: '30d' },
    { days: 90, label: '90d' },
    { days: 180, label: '180d' },
    { days: 0, label: 'Tudo' },
  ];
  protected readonly days = signal(30);
  protected readonly history = signal<ProductHistory | null>(null);
  protected readonly events = signal<PriceEvent[]>([]);
  protected readonly analysis = signal<ProductAnalysis | null>(null);
  protected readonly coupons = signal<ProductCouponItem[]>([]);
  /** Cupons que a loja vincula ao produto ou que combinam com ele. */
  protected readonly mainCoupons = computed(() =>
    this.coupons().filter((i) => i.offers.some((o) => o.applicability.level !== 'unknown')),
  );
  /** Cupons genéricos: participação do produto não confirmada. */
  protected readonly otherCoupons = computed(() =>
    this.coupons().filter((i) => i.offers.every((o) => o.applicability.level === 'unknown')),
  );
  protected readonly applicabilityLabel: Record<string, string> = {
    applies: 'A loja indica este produto',
    possible: 'Provavelmente aplicável',
    unknown: 'Aplicabilidade não confirmada',
  };

  setCouponVerification(id: number, status: Coupon['verification_status']): void {
    this.api.updateCoupon(id, { verification_status: status }).subscribe({
      next: () => this.api.productCoupons(Number(this.id())).subscribe((c) => this.coupons.set(c)),
      error: (e) => this.error.set(describeError(e).message),
    });
  }

  protected readonly historyPoints = computed(
    () => this.history()?.series.reduce((n, s) => n + s.points.length, 0) ?? 0,
  );

  protected readonly periodStats = computed(() => {
    const prices =
      this.history()
        ?.series.flatMap((s) => s.points.map((p) => p.price_cents))
        .filter((v): v is number => v !== null) ?? [];
    return {
      min: prices.length ? Math.min(...prices) : null,
      max: prices.length ? Math.max(...prices) : null,
    };
  });

  setDays(d: number): void {
    this.days.set(d);
    this.loadHistory();
  }

  loadHistory(): void {
    const id = Number(this.id());
    this.api.history(id, this.days()).subscribe({ next: (h) => this.history.set(h) });
    this.api.events({ productId: id, limit: 50 }).subscribe({ next: (e) => this.events.set(e) });
    this.api.analysis(id).subscribe({ next: (a) => this.analysis.set(a) });
    this.api.productCoupons(id).subscribe({ next: (c) => this.coupons.set(c) });
  }

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loadHistory();
    this.loading.set(true);
    this.api.product(Number(this.id())).subscribe({
      next: (p) => {
        this.product.set(p);
        this.loading.set(false);
      },
      error: (e) => {
        this.error.set(describeError(e).message);
        this.loading.set(false);
      },
    });
  }

  toggleActive(): void {
    const p = this.product();
    if (!p) return;
    this.api.updateProduct(p.id, { active: !p.active }).subscribe({
      next: (u) => this.product.set(u),
      error: (e) => this.error.set(describeError(e).message),
    });
  }

  deleteProduct(): void {
    const p = this.product();
    if (!p) return;
    if (!confirm(`Excluir "${p.name}"? O histórico de preços também será apagado.`)) return;
    this.api.deleteProduct(p.id).subscribe({
      next: () => this.router.navigate(['/']),
      error: (e) => this.error.set(describeError(e).message),
    });
  }

  addOffer(): void {
    const p = this.product();
    const url = this.newUrl().trim();
    if (!p || !url) return;
    this.busy.set(true);
    this.offerError.set(null);
    this.api.addOffer(p.id, url).subscribe({
      next: () => {
        this.newUrl.set('');
        this.busy.set(false);
        this.load();
      },
      error: (e) => {
        const d = describeError(e);
        this.offerError.set(Object.values(d.fields)[0] ?? d.message);
        this.busy.set(false);
      },
    });
  }

  protected readonly matchLabel: Record<string, string> = {
    strong: 'Provável mesmo produto',
    possible: 'Possível — confira',
    mismatch: 'Parece diferente',
    unknown: 'Não comparado',
  };

  protected readonly checking = signal<Set<number>>(new Set());

  checkOffer(o: Offer): void {
    this.checking.update((s) => new Set(s).add(o.id));
    const done = () =>
      this.checking.update((s) => {
        const n = new Set(s);
        n.delete(o.id);
        return n;
      });
    this.api.checkOffer(o.id).subscribe({
      next: () => {
        done();
        this.load();
      },
      error: (e) => {
        done();
        this.error.set(describeError(e).message);
      },
    });
  }

  // ---- Preço manual (lojas sem integração automática) ----
  protected readonly manualFor = signal<number | null>(null);
  protected readonly manualPrice = signal('');
  protected readonly manualAvailable = signal(true);
  protected readonly manualError = signal<string | null>(null);

  openManual(o: Offer): void {
    this.manualFor.set(o.id);
    this.manualPrice.set('');
    this.manualAvailable.set(true);
    this.manualError.set(null);
  }

  saveManual(o: Offer): void {
    const cents = parseBRL(this.manualPrice());
    if (cents === null || Number.isNaN(cents) || cents <= 0) {
      this.manualError.set('Informe o preço no formato 1.299,90.');
      return;
    }
    this.api.manualPrice(o.id, cents, this.manualAvailable()).subscribe({
      next: () => {
        this.manualFor.set(null);
        this.load();
      },
      error: (e) => this.manualError.set(describeError(e).message),
    });
  }

  toggleMatch(o: Offer): void {
    this.api.updateOffer(o.id, { match_confirmed: !o.match_confirmed }).subscribe({
      next: () => this.load(),
      error: (e) => this.error.set(describeError(e).message),
    });
  }

  removeOffer(o: Offer): void {
    if (!confirm(`Remover a oferta da ${this.storeSvc.name(o.store)}? O histórico dela será apagado.`)) return;
    this.api.deleteOffer(o.id).subscribe({
      next: () => this.load(),
      error: (e) => this.error.set(describeError(e).message),
    });
  }

  protected value(e: Event): string {
    return (e.target as HTMLInputElement).value;
  }
}
