import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  AppSettings,
  Coupon,
  CouponInput,
  CouponSources,
  DiagnosticItem,
  HealthResponse,
  MonitorStatus,
  NotificationLogEntry,
  NotificationStatus,
  PriceEvent,
  ProductAnalysis,
  ProductCouponItem,
  ProductHistory,
  Integration,
  LookupResult,
  Offer,
  Product,
  ProductInput,
  Stats,
  Store,
} from './models';

export type { HealthResponse, Stats as StatsResponse } from './models';

/**
 * Acesso à API Flask. Em desenvolvimento, "/api" é encaminhado para
 * http://127.0.0.1:5000 pelo proxy do Angular (proxy.conf.json).
 */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly base = '/api';

  health(): Observable<HealthResponse> {
    return this.http.get<HealthResponse>(`${this.base}/health`);
  }

  stats(): Observable<Stats> {
    return this.http.get<Stats>(`${this.base}/stats`);
  }

  diagnostics(): Observable<{ status: DiagnosticItem['status']; items: DiagnosticItem[] }> {
    return this.http.get<{ status: DiagnosticItem['status']; items: DiagnosticItem[] }>(`${this.base}/diagnostics`);
  }

  stores(): Observable<Store[]> {
    return this.http.get<Store[]>(`${this.base}/stores`);
  }

  products(): Observable<Product[]> {
    return this.http.get<Product[]>(`${this.base}/products`);
  }

  product(id: number): Observable<Product> {
    return this.http.get<Product>(`${this.base}/products/${id}`);
  }

  createProduct(body: ProductInput): Observable<Product> {
    return this.http.post<Product>(`${this.base}/products`, body);
  }

  updateProduct(id: number, body: ProductInput): Observable<Product> {
    return this.http.patch<Product>(`${this.base}/products/${id}`, body);
  }

  deleteProduct(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/products/${id}`);
  }

  addOffer(productId: number, url: string): Observable<Offer> {
    return this.http.post<Offer>(`${this.base}/products/${productId}/offers`, { url });
  }

  updateOffer(id: number, body: { match_confirmed: boolean }): Observable<Offer> {
    return this.http.patch<Offer>(`${this.base}/offers/${id}`, body);
  }

  /** Identifica um produto pelo link (consulta real à loja). */
  lookup(url: string): Observable<LookupResult> {
    return this.http.post<LookupResult>(`${this.base}/lookup`, { url });
  }

  /** Consulta a oferta na loja agora. */
  checkOffer(id: number): Observable<Offer> {
    return this.http.post<Offer>(`${this.base}/offers/${id}/check`, {});
  }

  /** Registra um preço visto pelo usuário (lojas sem integração automática). */
  manualPrice(id: number, price_cents: number, available: boolean | null): Observable<Offer> {
    return this.http.post<Offer>(`${this.base}/offers/${id}/manual-price`, { price_cents, available });
  }

  integrations(): Observable<Integration[]> {
    return this.http.get<Integration[]>(`${this.base}/integrations`);
  }

  mlAuthorizeUrl(): Observable<{ url: string }> {
    return this.http.post<{ url: string }>(`${this.base}/integrations/mercadolivre/authorize`, {});
  }

  mlConnect(code: string): Observable<unknown> {
    return this.http.post(`${this.base}/integrations/mercadolivre/connect`, { code });
  }

  mlTest(): Observable<{ ok: boolean; message: string }> {
    return this.http.post<{ ok: boolean; message: string }>(`${this.base}/integrations/mercadolivre/test`, {});
  }

  mlDisconnect(): Observable<unknown> {
    return this.http.post(`${this.base}/integrations/mercadolivre/disconnect`, {});
  }

  monitor(): Observable<MonitorStatus> {
    return this.http.get<MonitorStatus>(`${this.base}/monitor`);
  }

  runMonitor(): Observable<{ started: boolean }> {
    return this.http.post<{ started: boolean }>(`${this.base}/monitor/run`, {});
  }

  settings(): Observable<AppSettings> {
    return this.http.get<AppSettings>(`${this.base}/settings`);
  }

  updateSettings(patch: Partial<AppSettings>): Observable<AppSettings> {
    return this.http.patch<AppSettings>(`${this.base}/settings`, patch);
  }

  events(opts: { productId?: number; limit?: number } = {}): Observable<PriceEvent[]> {
    const params: Record<string, number> = { limit: opts.limit ?? 30 };
    if (opts.productId) params['product_id'] = opts.productId;
    return this.http.get<PriceEvent[]>(`${this.base}/events`, { params });
  }

  history(productId: number, days: number): Observable<ProductHistory> {
    return this.http.get<ProductHistory>(`${this.base}/products/${productId}/history`, {
      params: { days },
    });
  }

  analysis(productId: number): Observable<ProductAnalysis> {
    return this.http.get<ProductAnalysis>(`${this.base}/products/${productId}/analysis`);
  }

  coupons(params: { store?: string; validity?: string } = {}): Observable<{ coupons: Coupon[]; sources: CouponSources }> {
    const p: Record<string, string> = {};
    if (params.store) p['store'] = params.store;
    if (params.validity) p['validity'] = params.validity;
    return this.http.get<{ coupons: Coupon[]; sources: CouponSources }>(`${this.base}/coupons`, { params: p });
  }

  createCoupon(body: CouponInput): Observable<Coupon> {
    return this.http.post<Coupon>(`${this.base}/coupons`, body);
  }

  updateCoupon(id: number, body: CouponInput): Observable<Coupon> {
    return this.http.patch<Coupon>(`${this.base}/coupons/${id}`, body);
  }

  deleteCoupon(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/coupons/${id}`);
  }

  refreshCoupons(): Observable<{ fetched: boolean; new?: number; total?: number; message?: string; reason?: string }> {
    return this.http.post<{ fetched: boolean; new?: number; total?: number; message?: string; reason?: string }>(
      `${this.base}/coupons/refresh`,
      {},
    );
  }

  productCoupons(productId: number): Observable<ProductCouponItem[]> {
    return this.http.get<ProductCouponItem[]>(`${this.base}/products/${productId}/coupons`);
  }

  notificationStatus(): Observable<NotificationStatus> {
    return this.http.get<NotificationStatus>(`${this.base}/notifications/status`);
  }

  telegramConnect(): Observable<NotificationStatus & { chat_name: string; bot_username: string }> {
    return this.http.post<NotificationStatus & { chat_name: string; bot_username: string }>(
      `${this.base}/notifications/telegram/connect`,
      {},
    );
  }

  telegramDisconnect(): Observable<NotificationStatus> {
    return this.http.post<NotificationStatus>(`${this.base}/notifications/telegram/disconnect`, {});
  }

  sendTestNotification(): Observable<{ results: Record<string, { ok: boolean; error?: string }> }> {
    return this.http.post<{ results: Record<string, { ok: boolean; error?: string }> }>(
      `${this.base}/notifications/test`,
      {},
    );
  }

  dispatchNotifications(): Observable<{ sent: number; skipped: number; failed: number; held: number }> {
    return this.http.post<{ sent: number; skipped: number; failed: number; held: number }>(
      `${this.base}/notifications/dispatch`,
      {},
    );
  }

  pushKey(): Observable<{ public_key: string }> {
    return this.http.get<{ public_key: string }>(`${this.base}/push/key`);
  }

  pushSubscribe(sub: PushSubscriptionJSON): Observable<NotificationStatus> {
    return this.http.post<NotificationStatus>(`${this.base}/push/subscribe`, sub);
  }

  pushUnsubscribe(endpoint: string): Observable<NotificationStatus> {
    return this.http.post<NotificationStatus>(`${this.base}/push/unsubscribe`, { endpoint });
  }

  notificationLog(limit = 30): Observable<NotificationLogEntry[]> {
    return this.http.get<NotificationLogEntry[]>(`${this.base}/notifications/log`, { params: { limit } });
  }

  deleteOffer(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/offers/${id}`);
  }
}

/** Extrai uma mensagem legível e os erros por campo de uma resposta HTTP. */
export function describeError(err: unknown): { message: string; fields: Record<string, string> } {
  if (err instanceof HttpErrorResponse) {
    if (err.status === 0) {
      return { message: 'Sem conexão com a API local. O backend está rodando?', fields: {} };
    }
    if (err.status === 504) {
      // service worker sem rede e sem cópia salva desta tela
      return {
        message:
          'Sem conexão com o PRICE WATCH (computador desligado ou backend fechado) e nenhum dado salvo desta tela neste aparelho.',
        fields: {},
      };
    }
    if (err.status === 422 && err.error?.fields) {
      return { message: 'Verifique os campos destacados.', fields: err.error.fields };
    }
    return { message: err.error?.message ?? `Erro ${err.status}`, fields: {} };
  }
  return { message: 'Erro inesperado.', fields: {} };
}
