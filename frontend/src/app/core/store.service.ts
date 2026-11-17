import { Injectable, inject, signal } from '@angular/core';

import { ApiService } from './api.service';
import { Store } from './models';

/** Lista de lojas suportadas (vinda da API), carregada uma única vez. */
@Injectable({ providedIn: 'root' })
export class StoreService {
  private readonly api = inject(ApiService);
  readonly stores = signal<Store[]>([]);
  private loaded = false;

  load(): void {
    if (this.loaded) return;
    this.loaded = true;
    this.api.stores().subscribe({
      next: (s) => this.stores.set(s),
      error: () => (this.loaded = false),
    });
  }

  name(key: string | null | undefined): string {
    if (!key) return '—';
    return this.stores().find((s) => s.key === key)?.name ?? key;
  }
}
