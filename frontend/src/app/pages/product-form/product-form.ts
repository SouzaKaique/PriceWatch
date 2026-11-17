import { NgTemplateOutlet } from '@angular/common';
import { Component, OnInit, computed, inject, input, signal } from '@angular/core';
import { FormArray, FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { ApiService, describeError } from '../../core/api.service';
import { BrlPipe, centsToInput, parseBRL } from '../../core/money';
import { LookupData, LookupResult, ProductInput } from '../../core/models';
import { StoreService } from '../../core/store.service';

type LookupState = { loading: true } | { loading: false; result: LookupResult } | { loading: false; error: string };

/** Cadastro (sem :id) e edição (com :id) de produto. */
@Component({
  selector: 'app-product-form-page',
  imports: [ReactiveFormsModule, RouterLink, BrlPipe, NgTemplateOutlet],
  templateUrl: './product-form.html',
})
export class ProductFormPage implements OnInit {
  /** Parâmetro de rota (withComponentInputBinding). */
  readonly id = input<string>();

  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly fb = inject(FormBuilder);
  protected readonly storeSvc = inject(StoreService);

  protected readonly isEdit = computed(() => !!this.id());
  protected readonly loading = signal(false);
  protected readonly saving = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly fieldErrors = signal<Record<string, string>>({});
  protected imgFailed = false;

  /** Link colado no card "Identificar pelo link". */
  protected readonly quickUrl = signal('');
  /** Resultado das consultas por link (chave = link digitado). */
  protected readonly lookups = signal<Record<string, LookupState>>({});
  /** Campos preenchidos automaticamente na última identificação. */
  protected readonly filled = signal<string[]>([]);

  protected readonly form = this.fb.nonNullable.group({
    name: ['', [Validators.required, Validators.maxLength(300)]],
    brand: ['', Validators.maxLength(120)],
    model: ['', Validators.maxLength(160)],
    manufacturer_code: ['', Validators.maxLength(120)],
    category: ['', Validators.maxLength(120)],
    image_url: [''],
    target_price: [''],
    notes: [''],
    offers: this.fb.array<string>([]),
  });

  get offers(): FormArray {
    return this.form.controls.offers;
  }

  ngOnInit(): void {
    const id = this.id();
    if (!id) {
      this.addOfferRow();
      return;
    }
    this.loading.set(true);
    this.api.product(Number(id)).subscribe({
      next: (p) => {
        this.form.patchValue({
          name: p.name,
          brand: p.brand ?? '',
          model: p.model ?? '',
          manufacturer_code: p.manufacturer_code ?? '',
          category: p.category ?? '',
          image_url: p.image_url ?? '',
          target_price: centsToInput(p.target_price_cents),
          notes: p.notes ?? '',
        });
        this.loading.set(false);
      },
      error: (e) => {
        this.error.set(describeError(e).message);
        this.loading.set(false);
      },
    });
  }

  // ---- Identificação pelo link -------------------------------------------

  lookupState(url: string | null | undefined): LookupState | null {
    return url ? (this.lookups()[url.trim()] ?? null) : null;
  }

  /** Card do topo: consulta, preenche o formulário e adiciona o link às ofertas. */
  identify(): void {
    const url = this.quickUrl().trim();
    if (!url) return;
    if (!this.detectedStore(url)) {
      this.lookups.update((m) => ({
        ...m,
        [url]: { loading: false, error: 'Loja não suportada. Use KaBuM!, Pichau, Mercado Livre ou Amazon.' },
      }));
      return;
    }
    const values = this.offers.getRawValue() as string[];
    if (!values.some((v) => v.trim() === url)) {
      const empty = values.findIndex((v) => !v.trim());
      if (empty >= 0) this.offers.at(empty).setValue(url);
      else this.offers.push(this.fb.nonNullable.control(url));
    }
    this.runLookup(url, true);
  }

  /** Linha de oferta: consulta ao sair do campo (se ainda não consultada). */
  lookupRow(i: number): void {
    const url = (this.offers.at(i).value as string).trim();
    if (!url || !this.detectedStore(url) || this.lookupState(url)) return;
    this.runLookup(url, false);
  }

  private runLookup(url: string, fillForm: boolean): void {
    this.lookups.update((m) => ({ ...m, [url]: { loading: true } }));
    this.api.lookup(url).subscribe({
      next: (result) => {
        this.lookups.update((m) => ({ ...m, [url]: { loading: false, result } }));
        if (result.status === 'ok' && result.data) this.fillEmpty(result.data, fillForm);
      },
      error: (e) => {
        const d = describeError(e);
        this.lookups.update((m) => ({
          ...m,
          [url]: { loading: false, error: Object.values(d.fields)[0] ?? d.message },
        }));
      },
    });
  }

  /** Preenche somente campos vazios — nunca sobrescreve o que o usuário digitou. */
  private fillEmpty(d: LookupData, announce: boolean): void {
    const map: [keyof typeof this.form.controls, string | null][] = [
      ['name', d.name],
      ['brand', d.brand],
      ['model', d.model],
      ['manufacturer_code', d.mpn],
      ['category', d.category],
      ['image_url', d.image_url],
    ];
    const done: string[] = [];
    for (const [field, value] of map) {
      const ctrl = this.form.controls[field];
      if (value && !String(ctrl.value ?? '').trim()) {
        ctrl.setValue(value as never);
        done.push(field);
      }
    }
    if (done.includes('image_url')) this.imgFailed = false;
    if (announce) this.filled.set(done);
  }

  protected readonly fieldLabels: Record<string, string> = {
    name: 'nome',
    brand: 'marca',
    model: 'modelo',
    manufacturer_code: 'código',
    category: 'categoria',
    image_url: 'imagem',
  };

  filledLabels(): string {
    return this.filled()
      .map((f) => this.fieldLabels[f])
      .join(', ');
  }

  // ---- Linhas de oferta --------------------------------------------------

  addOfferRow(): void {
    this.offers.push(this.fb.nonNullable.control(''));
  }

  removeOfferRow(i: number): void {
    this.offers.removeAt(i);
    this.fieldErrors.set({}); // índices mudaram; erros do servidor deixam de valer
  }

  /** Loja reconhecida pelo domínio do link (mesma regra do backend). */
  detectedStore(url: string): string | null {
    let host: string;
    try {
      host = new URL(url.trim()).hostname.toLowerCase();
    } catch {
      return null;
    }
    const s = this.storeSvc
      .stores()
      .find((st) => st.domains.some((d) => host === d || host.endsWith('.' + d)));
    return s?.name ?? null;
  }

  err(field: string): string | null {
    const server = this.fieldErrors()[field];
    if (server) return server;
    const c = this.form.get(field);
    if (c && c.invalid && (c.dirty || c.touched)) {
      if (c.hasError('required')) return 'Campo obrigatório.';
      if (c.hasError('maxlength')) return 'Texto muito longo.';
    }
    return null;
  }

  protected value(e: Event): string {
    return (e.target as HTMLInputElement).value;
  }

  save(): void {
    this.form.markAllAsTouched();
    this.fieldErrors.set({});
    this.error.set(null);

    const v = this.form.getRawValue();
    const target = parseBRL(v.target_price);
    if (Number.isNaN(target)) {
      this.fieldErrors.set({ target_price_cents: 'Use o formato 1.299,90.' });
      return;
    }
    if (this.form.invalid) return;

    const body: ProductInput = {
      name: v.name,
      brand: v.brand,
      model: v.model,
      manufacturer_code: v.manufacturer_code,
      category: v.category,
      image_url: v.image_url,
      target_price_cents: target,
      notes: v.notes,
    };

    this.saving.set(true);
    const id = this.id();
    const req = id
      ? this.api.updateProduct(Number(id), body)
      : this.api.createProduct({
          ...body,
          offers: (v.offers as string[]).map((u) => u.trim()).filter(Boolean).map((url) => ({ url })),
        });

    req.subscribe({
      next: (p) => this.router.navigate(['/produtos', p.id]),
      error: (e) => {
        const d = describeError(e);
        this.error.set(d.message);
        this.fieldErrors.set(d.fields);
        this.saving.set(false);
      },
    });
  }
}
