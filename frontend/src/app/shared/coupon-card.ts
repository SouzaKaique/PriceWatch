import { DatePipe } from '@angular/common';
import { Component, computed, inject, input, output, signal } from '@angular/core';

import { BrlPipe } from '../core/money';
import { Coupon } from '../core/models';
import { StoreService } from '../core/store.service';

/** Cartão de cupom: código copiável, desconto, vigência, condições, fonte e verificação. */
@Component({
  selector: 'app-coupon-card',
  imports: [DatePipe, BrlPipe],
  template: `
    @let c = coupon();
    <article class="card coupon h-100 p-3" [class.dim]="c.validity !== 'active' || c.verification_status === 'user_failed'">
      <div class="d-flex justify-content-between align-items-start gap-2 mb-2">
        <div class="min-w-0">
          <div class="d-flex flex-wrap gap-1 mb-1">
            <span class="store-chip">{{ stores.name(c.store) }}</span>
            @switch (c.verification_status) {
              @case ('user_confirmed') { <span class="badge-soft green"><i class="bi bi-check2-circle me-1"></i>Funcionou com você</span> }
              @case ('user_failed') { <span class="badge-soft red"><i class="bi bi-x-circle me-1"></i>Não funcionou</span> }
              @default { <span class="badge-soft muted" title="O PRICE WATCH não testa cupons no carrinho"><i class="bi bi-question-circle me-1"></i>Não confirmado</span> }
            }
            @if (c.validity === 'upcoming') { <span class="badge-soft blue">Em breve</span> }
            @if (c.validity === 'expired') { <span class="badge-soft muted">Expirado</span> }
          </div>
          <div class="fs-5 fw-semibold price-down">{{ discountText() }}</div>
          @if (c.description) { <div class="small text-muted-pw">{{ c.description }}</div> }
        </div>
      </div>

      <button type="button" class="code-btn" (click)="copy()" [attr.aria-label]="'Copiar cupom ' + c.code">
        <span class="font-monospace">{{ c.code }}</span>
        <span class="small">
          @if (copied()) { <i class="bi bi-check2 me-1"></i>Copiado } @else { <i class="bi bi-clipboard me-1"></i>Copiar }
        </span>
      </button>

      <ng-content />

      <dl class="small mt-2 mb-0 meta">
        @if (c.valid_until) {
          <dt>Validade</dt>
          <dd>
            @if (c.valid_from && c.validity === 'upcoming') { de {{ c.valid_from | date: 'dd/MM HH:mm' }} }
            até {{ c.valid_until | date: 'dd/MM/yyyy HH:mm' }}
            @if (hoursLeft(); as h) { <span class="text-warning"> · acaba em {{ h }} h</span> }
          </dd>
        } @else {
          <dt>Validade</dt><dd>não informada</dd>
        }
        @if (c.min_purchase_cents) { <dt>Compra mínima</dt><dd>{{ c.min_purchase_cents | brl }}</dd> }
        @if (c.max_discount_cents) { <dt>Desconto máximo</dt><dd>{{ c.max_discount_cents | brl }}</dd> }
        @if (c.categories) { <dt>Categorias</dt><dd>{{ c.categories }}</dd> }
        <dt>Fonte</dt><dd class="text-truncate" [title]="c.source ?? ''">{{ c.source }}</dd>
      </dl>

      @if (c.conditions) {
        <details class="small mt-2">
          <summary class="text-muted-pw">Condições completas</summary>
          <p class="mt-1 mb-0">{{ c.conditions }}</p>
        </details>
      }

      <div class="d-flex flex-wrap gap-2 mt-auto pt-3">
        @if (c.link_url) {
          <a class="btn btn-outline-primary btn-sm" [href]="c.link_url" target="_blank" rel="noopener noreferrer">
            <i class="bi bi-box-arrow-up-right me-1"></i>Ver ofertas
          </a>
        }
        @if (actions()) {
          @if (c.verification_status !== 'user_confirmed') {
            <button type="button" class="btn btn-outline-secondary btn-sm" (click)="verify.emit('user_confirmed')" title="Você testou no carrinho e o desconto foi aplicado">Funcionou</button>
          }
          @if (c.verification_status !== 'user_failed') {
            <button type="button" class="btn btn-outline-secondary btn-sm" (click)="verify.emit('user_failed')" title="Você testou e o desconto não foi aplicado">Não funcionou</button>
          }
          @if (c.verification_status !== 'unconfirmed') {
            <button type="button" class="btn btn-link btn-sm text-muted-pw" (click)="verify.emit('unconfirmed')">Desfazer</button>
          }
          @if (c.origin === 'manual') {
            <button type="button" class="btn btn-outline-danger btn-sm ms-auto" (click)="remove.emit()" aria-label="Excluir cupom"><i class="bi bi-trash"></i></button>
          }
        }
      </div>
    </article>
  `,
  styles: `
    .coupon { display: flex; flex-direction: column; }
    .coupon.dim { opacity: 0.6; }
    .code-btn {
      display: flex; justify-content: space-between; align-items: center; width: 100%;
      border: 1px dashed var(--pw-blue); border-radius: 0.5rem; background: rgba(59, 130, 246, 0.08);
      color: var(--pw-text); padding: 0.5rem 0.75rem; font-size: 1rem; letter-spacing: 0.06em;
    }
    .code-btn:hover { background: rgba(59, 130, 246, 0.16); }
    .meta { display: grid; grid-template-columns: auto 1fr; column-gap: 0.75rem; row-gap: 0.15rem; }
    .meta dt { color: var(--pw-muted); font-weight: 400; }
    .meta dd { margin: 0; min-width: 0; }
  `,
})
export class CouponCard {
  readonly coupon = input.required<Coupon>();
  readonly actions = input(true);
  readonly verify = output<Coupon['verification_status']>();
  readonly remove = output<void>();

  protected readonly stores = inject(StoreService);
  protected readonly copied = signal(false);

  protected readonly discountText = computed(() => {
    const c = this.coupon();
    if (c.discount_percent) return `${String(c.discount_percent).replace('.', ',')}% OFF`;
    if (c.discount_cents)
      return `${new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 }).format(c.discount_cents / 100)} OFF`;
    return 'Desconto';
  });

  protected readonly hoursLeft = computed(() => {
    const c = this.coupon();
    if (c.validity !== 'active' || !c.valid_until) return null;
    const h = Math.ceil((Date.parse(c.valid_until) - Date.now()) / 3_600_000);
    return h > 0 && h <= 48 ? h : null;
  });

  async copy(): Promise<void> {
    const code = this.coupon().code;
    try {
      await navigator.clipboard.writeText(code);
    } catch {
      // Fallback (ex.: HTTP no celular, sem permissão de clipboard)
      const ta = document.createElement('textarea');
      ta.value = code;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
    }
    this.copied.set(true);
    setTimeout(() => this.copied.set(false), 2000);
  }
}
