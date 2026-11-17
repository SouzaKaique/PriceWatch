import { Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { AccessKeyService } from './core/access-key';
import { PwaService } from './core/pwa.service';
import { StoreService } from './core/store.service';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './app.html',
})
export class App implements OnInit {
  private readonly stores = inject(StoreService);
  protected readonly pwa = inject(PwaService);
  protected readonly accessKey = inject(AccessKeyService);
  protected readonly keyInput = signal('');

  protected readonly nav = [
    { path: '/', label: 'Dashboard', short: 'Início', icon: 'bi-grid-1x2', exact: true },
    { path: '/produtos/novo', label: 'Novo produto', short: 'Adicionar', icon: 'bi-plus-circle', exact: true },
    { path: '/cupons', label: 'Cupons', short: 'Cupons', icon: 'bi-ticket-perforated', exact: true },
    { path: '/alertas', label: 'Alertas', short: 'Alertas', icon: 'bi-bell', exact: true },
    { path: '/integracoes', label: 'Integrações', short: 'Lojas', icon: 'bi-plug', exact: true },
    { path: '/status', label: 'Sistema', short: 'Sistema', icon: 'bi-hdd-stack', exact: true },
  ];

  ngOnInit(): void {
    this.stores.load();
    this.pwa.init();
  }

  saveKey(): void {
    if (!this.keyInput().trim()) return;
    this.accessKey.set(this.keyInput());
    location.reload();
  }

  protected value(e: Event): string {
    return (e.target as HTMLInputElement).value;
  }
}
