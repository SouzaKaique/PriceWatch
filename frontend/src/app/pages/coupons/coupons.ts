import { DatePipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import { ApiService, describeError } from '../../core/api.service';
import { parseBRL } from '../../core/money';
import { Coupon, CouponSources } from '../../core/models';
import { StoreService } from '../../core/store.service';
import { CouponCard } from '../../shared/coupon-card';

@Component({
  selector: 'app-coupons-page',
  imports: [CouponCard, DatePipe, ReactiveFormsModule],
  templateUrl: './coupons.html',
})
export class CouponsPage implements OnInit {
  private readonly api = inject(ApiService);
  private readonly fb = inject(FormBuilder);
  protected readonly storeSvc = inject(StoreService);

  protected readonly coupons = signal<Coupon[]>([]);
  protected readonly sources = signal<CouponSources | null>(null);
  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly refreshing = signal(false);
  protected readonly refreshMsg = signal<{ ok: boolean; text: string } | null>(null);

  protected readonly store = signal('');
  protected readonly validity = signal('active');
  protected readonly verification = signal('');
  protected readonly search = signal('');

  protected readonly showForm = signal(false);
  protected readonly saving = signal(false);
  protected readonly formErrors = signal<Record<string, string>>({});

  protected readonly form = this.fb.nonNullable.group({
    store: ['', Validators.required],
    code: ['', Validators.required],
    discount_type: ['percent'],
    discount: ['', Validators.required],
    min_purchase: [''],
    description: [''],
    valid_until: [''],
    link_url: [''],
    source: ['', Validators.required],
    conditions: [''],
  });

  protected readonly filtered = computed(() => {
    const q = this.search().trim().toLowerCase();
    const v = this.verification();
    return this.coupons().filter(
      (c) =>
        (!v || c.verification_status === v) &&
        (!q || [c.code, c.description, c.conditions].some((x) => x?.toLowerCase().includes(q))),
    );
  });

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.api.coupons({ store: this.store(), validity: this.validity() }).subscribe({
      next: (r) => {
        this.coupons.set(r.coupons);
        this.sources.set(r.sources);
        this.loading.set(false);
      },
      error: (e) => {
        this.error.set(describeError(e).message);
        this.loading.set(false);
      },
    });
  }

  refresh(): void {
    this.refreshing.set(true);
    this.refreshMsg.set(null);
    this.api.refreshCoupons().subscribe({
      next: (r) => {
        this.refreshing.set(false);
        this.refreshMsg.set(
          r.fetched
            ? { ok: true, text: `${r.total} cupons lidos da página oficial, ${r.new} novo(s).` }
            : { ok: false, text: r.message ?? 'Não foi possível atualizar agora.' },
        );
        this.load();
      },
      error: (e) => {
        this.refreshing.set(false);
        this.refreshMsg.set({ ok: false, text: describeError(e).message });
      },
    });
  }

  setVerification(c: Coupon, status: Coupon['verification_status']): void {
    this.api.updateCoupon(c.id, { verification_status: status }).subscribe({
      next: (u) => this.coupons.update((l) => l.map((x) => (x.id === u.id ? u : x))),
      error: (e) => this.error.set(describeError(e).message),
    });
  }

  remove(c: Coupon): void {
    if (!confirm(`Excluir o cupom ${c.code}?`)) return;
    this.api.deleteCoupon(c.id).subscribe({
      next: () => this.coupons.update((l) => l.filter((x) => x.id !== c.id)),
      error: (e) => this.error.set(describeError(e).message),
    });
  }

  save(): void {
    this.form.markAllAsTouched();
    this.formErrors.set({});
    const v = this.form.getRawValue();
    const errs: Record<string, string> = {};
    let pct: number | null = null;
    let cents: number | null = null;
    if (v.discount_type === 'percent') {
      pct = Number(v.discount.replace(',', '.').replace('%', ''));
      if (!Number.isFinite(pct) || pct <= 0 || pct >= 100) errs['discount_percent'] = 'Percentual inválido.';
    } else {
      cents = parseBRL(v.discount);
      if (cents === null || Number.isNaN(cents) || cents <= 0) errs['discount_cents'] = 'Valor inválido.';
    }
    const min = parseBRL(v.min_purchase);
    if (Number.isNaN(min)) errs['min_purchase_cents'] = 'Valor inválido.';
    if (Object.keys(errs).length || this.form.invalid) {
      this.formErrors.set(errs);
      return;
    }
    this.saving.set(true);
    this.api
      .createCoupon({
        store: v.store,
        code: v.code,
        discount_percent: pct,
        discount_cents: cents,
        min_purchase_cents: min,
        description: v.description || null,
        valid_until: v.valid_until || null,
        link_url: v.link_url || null,
        source: v.source,
        conditions: v.conditions || null,
      })
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.showForm.set(false);
          this.form.reset({ discount_type: 'percent' });
          this.load();
        },
        error: (e) => {
          const d = describeError(e);
          this.saving.set(false);
          this.formErrors.set({ ...d.fields, _: d.message });
        },
      });
  }

  fieldError(name: string): string | null {
    const server = this.formErrors()[name];
    if (server) return server;
    const c = this.form.get(name);
    return c && c.invalid && c.touched ? 'Campo obrigatório.' : null;
  }

  protected value(e: Event): string {
    return (e.target as HTMLInputElement | HTMLSelectElement).value;
  }
}
