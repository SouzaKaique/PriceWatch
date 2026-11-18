import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';

import { ApiService, describeError } from '../../core/api.service';
import { BrlPipe, parseBRL } from '../../core/money';
import { PriceEvent, Product, Stats } from '../../core/models';
import { StoreService } from '../../core/store.service';
import { DealCard } from '../../shared/deal-card';
import { EventList } from '../../shared/event-list';
import { ProductCard } from '../../shared/product-card';

type View = 'all' | 'deals' | 'target' | 'no-price' | 'paused';
type SortKey = 'smart' | 'recent' | 'price' | 'name' | 'variation';

const HIGHLIGHT_RANK: Record<string, number> = { target: 0, great: 1, good: 2 };

@Component({
  selector: 'app-dashboard-page',
  imports: [RouterLink, DatePipe, DecimalPipe, BrlPipe, ProductCard, DealCard, EventList],
  templateUrl: './dashboard.html',
})
export class DashboardPage implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  protected readonly storeSvc = inject(StoreService);

  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly products = signal<Product[]>([]);
  protected readonly stats = signal<Stats | null>(null);
  protected readonly events = signal<PriceEvent[]>([]);
  protected readonly running = signal(false);
  protected readonly showActivity = signal(false);
  private poll?: ReturnType<typeof setInterval>;

  // Filtros
  protected readonly view = signal<View>('all');
  protected readonly search = signal('');
  protected readonly showMore = signal(false);
  protected readonly store = signal('');
  protected readonly category = signal('');
  protected readonly maxPrice = signal('');
  protected readonly opportunity = signal('');
  protected readonly sort = signal<SortKey>('smart');

  /** Produtos com preço bom: preço-alvo atingido, ótima ou boa oportunidade. */
  protected readonly highlights = computed(() =>
    this.products()
      .filter((p) => p.active && p.summary.highlight)
      .sort(
        (a, b) =>
          HIGHLIGHT_RANK[a.summary.highlight!.reason] - HIGHLIGHT_RANK[b.summary.highlight!.reason] ||
          (b.summary.analysis?.real_discount_pct ?? 0) - (a.summary.analysis?.real_discount_pct ?? 0),
      ),
  );

  protected readonly counts = computed(() => {
    const ps = this.products();
    return {
      all: ps.length,
      deals: ps.filter((p) => p.summary.highlight).length,
      target: ps.filter((p) => p.summary.target_reached).length,
      'no-price': ps.filter((p) => p.summary.best_price_cents === null).length,
      paused: ps.filter((p) => !p.active).length,
    } as Record<View, number>;
  });

  protected readonly views: { key: View; label: string }[] = [
    { key: 'all', label: 'Todos' },
    { key: 'deals', label: 'Preço bom' },
    { key: 'target', label: 'Alvo atingido' },
    { key: 'no-price', label: 'Sem preço' },
    { key: 'paused', label: 'Pausados' },
  ];

  protected readonly categories = computed(() =>
    [...new Set(this.products().map((p) => p.category).filter((c): c is string => !!c))].sort(),
  );

  protected readonly moreFiltersActive = computed(
    () => !!this.store() || !!this.category() || !!this.opportunity() || !!this.maxPrice(),
  );
  protected readonly hasFilters = computed(() => !!this.search() || this.view() !== 'all' || this.moreFiltersActive());

  protected readonly filtered = computed(() => {
    const q = this.search().trim().toLowerCase();
    const view = this.view();
    const store = this.store();
    const cat = this.category();
    const max = parseBRL(this.maxPrice());
    const opp = this.opportunity();

    const list = this.products().filter((p) => {
      const s = p.summary;
      if (q && ![p.name, p.brand, p.model, p.manufacturer_code, p.category].some((v) => v?.toLowerCase().includes(q)))
        return false;
      if (view === 'deals' && !s.highlight) return false;
      if (view === 'target' && !s.target_reached) return false;
      if (view === 'no-price' && s.best_price_cents !== null) return false;
      if (view === 'paused' && p.active) return false;
      if (store && !s.stores.includes(store)) return false;
      if (cat && p.category !== cat) return false;
      if (opp && (s.analysis?.classification ?? 'insufficient') !== opp) return false;
      if (max !== null && !Number.isNaN(max) && (s.best_price_cents === null || s.best_price_cents > max)) return false;
      return true;
    });

    const nullsLast = (v: number | null | undefined) => (v == null ? Number.POSITIVE_INFINITY : v);
    switch (this.sort()) {
      case 'price':
        return list.sort((a, b) => nullsLast(a.summary.best_price_cents) - nullsLast(b.summary.best_price_cents));
      case 'name':
        return list.sort((a, b) => a.name.localeCompare(b.name, 'pt-BR'));
      case 'variation':
        return list.sort((a, b) => nullsLast(a.summary.variation_percent) - nullsLast(b.summary.variation_percent));
      case 'recent':
        return list; // a API já envia os mais recentes primeiro
      default:
        // preço bom primeiro, depois ativos com preço, depois o resto
        return list.sort((a, b) => this.rank(a) - this.rank(b));
    }
  });

  private rank(p: Product): number {
    const h = p.summary.highlight;
    if (h) return HIGHLIGHT_RANK[h.reason];
    if (!p.active) return 9;
    return p.summary.best_price_cents === null ? 6 : 4;
  }

  ngOnInit(): void {
    this.load();
  }

  ngOnDestroy(): void {
    this.stopPolling();
  }

  load(): void {
    this.loading.set(true);
    this.error.set(null);
    forkJoin({
      products: this.api.products(),
      stats: this.api.stats(),
      events: this.api.events({ limit: 8 }),
    }).subscribe({
      next: ({ products, stats, events }) => {
        this.products.set(products);
        this.stats.set(stats);
        this.events.set(events);
        this.loading.set(false);
        this.setRunning(stats.monitor_running);
      },
      error: (e) => {
        this.error.set(describeError(e).message);
        this.loading.set(false);
      },
    });
  }

  /** Dispara uma verificação completa e acompanha até terminar. */
  runNow(): void {
    this.api.runMonitor().subscribe({
      next: () => this.setRunning(true),
      error: (e) => {
        const d = describeError(e);
        if ((e as { status?: number }).status === 409) this.setRunning(true);
        else this.error.set(d.message);
      },
    });
  }

  private setRunning(running: boolean): void {
    const was = this.running();
    this.running.set(running);
    if (running && !this.poll) {
      this.poll = setInterval(() => {
        this.api.stats().subscribe((st) => {
          this.stats.set(st);
          if (!st.monitor_running) {
            this.stopPolling();
            this.running.set(false);
            this.load(); // terminou: recarrega produtos e eventos
          }
        });
      }, 4000);
    } else if (!running && was) {
      this.stopPolling();
    }
  }

  private stopPolling(): void {
    if (this.poll) clearInterval(this.poll);
    this.poll = undefined;
  }

  clearFilters(): void {
    this.view.set('all');
    this.search.set('');
    this.store.set('');
    this.category.set('');
    this.maxPrice.set('');
    this.opportunity.set('');
  }

  toggleActive(product: Product, active: boolean): void {
    this.api.updateProduct(product.id, { active }).subscribe({
      next: (updated) => {
        this.products.update((list) => list.map((p) => (p.id === updated.id ? updated : p)));
        this.api.stats().subscribe((s) => this.stats.set(s));
      },
      error: (e) => this.error.set(describeError(e).message),
    });
  }

  protected value(e: Event): string {
    return (e.target as HTMLInputElement | HTMLSelectElement).value;
  }
}
