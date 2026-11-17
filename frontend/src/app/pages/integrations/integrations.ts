import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';

import { ApiService, describeError } from '../../core/api.service';
import { Integration } from '../../core/models';

@Component({
  selector: 'app-integrations-page',
  imports: [DatePipe, DecimalPipe],
  templateUrl: './integrations.html',
})
export class IntegrationsPage implements OnInit {
  private readonly api = inject(ApiService);

  protected readonly items = signal<Integration[]>([]);
  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);

  // Mercado Livre
  protected readonly mlBusy = signal(false);
  protected readonly mlMessage = signal<{ ok: boolean; text: string } | null>(null);
  protected readonly authUrl = signal<string | null>(null);
  protected readonly code = signal('');

  protected readonly stateLabel: Record<Integration['state'], string> = {
    available: 'Automática',
    connected: 'Conta conectada',
    app_token: 'Credenciais configuradas',
    not_configured: 'Não configurada',
    limited: 'Limitada · preço manual',
  };

  protected readonly statusLabel: Partial<Record<string, string>> = {
    ok: 'consultadas',
    blocked: 'bloqueadas',
    rate_limited: 'em pausa',
    not_found: 'não encontradas',
    error: 'com erro',
    unsupported: 'sem integração',
    pending: 'aguardando',
  };

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.api.integrations().subscribe({
      next: (items) => {
        this.items.set(items);
        this.loading.set(false);
      },
      error: (e) => {
        this.error.set(describeError(e).message);
        this.loading.set(false);
      },
    });
  }

  statusEntries(i: Integration): { key: string; count: number }[] {
    return Object.entries(i.stats.by_status).map(([key, count]) => ({ key, count }));
  }

  mlTest(): void {
    this.mlBusy.set(true);
    this.mlMessage.set(null);
    this.api.mlTest().subscribe({
      next: (r) => {
        this.mlMessage.set({ ok: r.ok, text: r.message });
        this.mlBusy.set(false);
        this.load();
      },
      error: (e) => this.fail(e),
    });
  }

  mlAuthorize(): void {
    this.mlBusy.set(true);
    this.mlMessage.set(null);
    this.api.mlAuthorizeUrl().subscribe({
      next: (r) => {
        this.authUrl.set(r.url);
        this.mlBusy.set(false);
        window.open(r.url, '_blank', 'noopener');
      },
      error: (e) => this.fail(e),
    });
  }

  mlConnect(): void {
    if (!this.code().trim()) return;
    this.mlBusy.set(true);
    this.api.mlConnect(this.code().trim()).subscribe({
      next: () => {
        this.mlMessage.set({ ok: true, text: 'Conta do Mercado Livre conectada.' });
        this.authUrl.set(null);
        this.code.set('');
        this.mlBusy.set(false);
        this.load();
      },
      error: (e) => this.fail(e),
    });
  }

  mlDisconnect(): void {
    if (!confirm('Desconectar a conta do Mercado Livre? Os tokens salvos serão apagados.')) return;
    this.api.mlDisconnect().subscribe({ next: () => this.load(), error: (e) => this.fail(e) });
  }

  private fail(e: unknown): void {
    const d = describeError(e);
    this.mlMessage.set({ ok: false, text: Object.values(d.fields)[0] ?? d.message });
    this.mlBusy.set(false);
  }

  protected value(e: Event): string {
    return (e.target as HTMLInputElement).value;
  }
}
