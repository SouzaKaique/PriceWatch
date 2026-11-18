import { Component, OnDestroy, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { ApiService, describeError } from '../../core/api.service';
import { BrlPipe, centsToInput, parseBRL } from '../../core/money';
import { ImportItem, ImportPreview, ImportResult, ProductInput } from '../../core/models';
import { StoreService } from '../../core/store.service';

type LinkStatus =
  | { state: 'pending' }
  | { state: 'loading' }
  | { state: 'ok'; price: number | null; available: boolean | null }
  | { state: 'fail'; message: string };

interface Row extends ImportItem {
  targetInput: string;
  newLink: string;
  linkError: string | null;
  brand: string | null;
  model: string | null;
  category: string | null;
  image_url: string | null;
  linkStatus: Record<string, LinkStatus>;
}

/** Importar lista de desejos (PDF ou texto): enviar → revisar/identificar → importar. */
@Component({
  selector: 'app-import-page',
  imports: [RouterLink, BrlPipe],
  templateUrl: './import.html',
  styles: `
    .drop {
      border: 2px dashed var(--pw-border); border-radius: 14px; padding: 2rem 1rem; text-align: center;
      cursor: pointer; transition: border-color 0.15s, background 0.15s;
    }
    .drop.over, .drop:hover { border-color: var(--pw-blue); background: rgba(59, 130, 246, 0.06); }
    .drop .bi { font-size: 2.2rem; color: var(--pw-blue); }
    .row-item { border-top: 1px solid var(--pw-border); }
    .row-item.off { opacity: 0.55; }
    .footer-bar {
      position: sticky; bottom: 0; z-index: 5; background: rgba(11, 17, 32, 0.92);
      backdrop-filter: blur(8px); border-top: 1px solid var(--pw-border);
    }
    @media (max-width: 767.98px) { .footer-bar { bottom: calc(4.2rem + env(safe-area-inset-bottom)); } }
  `,
})
export class ImportPage implements OnDestroy {
  private readonly api = inject(ApiService);
  protected readonly stores = inject(StoreService);

  protected readonly step = signal<'upload' | 'review' | 'done'>('upload');
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly dragOver = signal(false);
  protected readonly text = signal('');
  protected readonly preview = signal<ImportPreview | null>(null);
  protected readonly rows = signal<Row[]>([]);
  protected readonly result = signal<ImportResult | null>(null);

  // Identificação pelos links
  protected readonly identifying = signal(false);
  protected readonly progress = signal({ done: 0, total: 0 });
  private stopRequested = false;

  protected readonly selected = computed(() => this.rows().filter((r) => r.checked));
  protected readonly selectedWithoutLinks = computed(() => this.selected().filter((r) => !r.urls.length).length);
  protected readonly invalidSelected = computed(
    () => this.selected().filter((r) => !r.name.trim() || Number.isNaN(parseBRL(r.targetInput))).length,
  );

  ngOnDestroy(): void {
    this.stopRequested = true;
  }

  // ---- Etapa 1: enviar ---------------------------------------------------------

  onDrop(ev: DragEvent): void {
    ev.preventDefault();
    this.dragOver.set(false);
    const file = ev.dataTransfer?.files?.[0];
    if (file) this.readFile(file);
  }

  onFile(ev: Event): void {
    const input = ev.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) this.readFile(file);
    input.value = '';
  }

  readFile(file: File): void {
    if (!/\.pdf$/i.test(file.name) && file.type !== 'application/pdf') {
      this.error.set('Escolha um arquivo PDF.');
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      this.error.set('O PDF tem mais de 20 MB.');
      return;
    }
    this.run(this.api.parseImportFile(file));
  }

  readText(): void {
    if (this.text().trim()) this.run(this.api.parseImportText(this.text()));
  }

  private run(obs: ReturnType<ApiService['parseImportText']>): void {
    this.busy.set(true);
    this.error.set(null);
    obs.subscribe({
      next: (p) => {
        this.busy.set(false);
        this.preview.set(p);
        this.rows.set(
          p.items.map((i) => ({
            ...i,
            targetInput: centsToInput(i.target_price_cents),
            newLink: '',
            linkError: null,
            brand: null,
            model: null,
            category: null,
            image_url: null,
            linkStatus: Object.fromEntries(i.urls.map((u) => [u.url, { state: 'pending' } as LinkStatus])),
          })),
        );
        this.step.set('review');
        if (p.items.some((i) => i.checked && i.urls.length)) void this.identify();
      },
      error: (e) => {
        this.busy.set(false);
        this.error.set(describeError(e).message);
      },
    });
  }

  // ---- Etapa 2: revisar --------------------------------------------------------

  private patch(key: string, change: (r: Row) => Partial<Row>): void {
    this.rows.update((rows) => rows.map((r) => (r.key === key ? { ...r, ...change(r) } : r)));
  }

  toggle(r: Row): void {
    this.patch(r.key, (x) => ({ checked: !x.checked }));
  }

  setAll(checked: boolean): void {
    this.rows.update((rows) => rows.map((r) => ({ ...r, checked })));
  }

  setName(r: Row, value: string): void {
    this.patch(r.key, () => ({ name: value, name_source: 'line' }));
  }

  setTarget(r: Row, value: string): void {
    this.patch(r.key, () => ({ targetInput: value }));
  }

  useSeenAsTarget(r: Row): void {
    this.patch(r.key, (x) => ({ targetInput: centsToInput(x.price_seen_cents) }));
  }

  removeLink(r: Row, url: string): void {
    this.patch(r.key, (x) => ({ urls: x.urls.filter((u) => u.url !== url) }));
  }

  setNewLink(r: Row, value: string): void {
    this.patch(r.key, () => ({ newLink: value, linkError: null }));
  }

  addLink(r: Row): void {
    const url = r.newLink.trim();
    if (!url) return;
    let host = '';
    try {
      host = new URL(url).hostname.toLowerCase();
    } catch {
      this.patch(r.key, () => ({ linkError: 'Link inválido.' }));
      return;
    }
    const store = this.stores.stores().find((s) => s.domains.some((d) => host === d || host.endsWith('.' + d)));
    if (!store) {
      this.patch(r.key, () => ({ linkError: 'Loja não suportada.' }));
      return;
    }
    if (r.urls.some((u) => u.url === url)) return;
    this.patch(r.key, (x) => ({
      urls: [...x.urls, { url, store: store.key, store_name: store.name, existing: null }],
      linkStatus: { ...x.linkStatus, [url]: { state: 'pending' } },
      newLink: '',
      checked: true,
    }));
    void this.identifyOne(r.key, url);
  }

  /** Consulta cada link na loja (respeitando os limites do backend) e completa os dados. */
  async identify(): Promise<void> {
    if (this.identifying()) return;
    this.stopRequested = false;
    const queue = this.rows()
      .filter((r) => r.checked)
      .flatMap((r) => r.urls.filter((u) => !u.existing && r.linkStatus[u.url]?.state === 'pending').map((u) => [r.key, u.url]));
    this.progress.set({ done: 0, total: queue.length });
    this.identifying.set(true);
    for (const [key, url] of queue) {
      if (this.stopRequested) break;
      await this.identifyOne(key, url);
      this.progress.update((p) => ({ ...p, done: p.done + 1 }));
    }
    this.identifying.set(false);
  }

  stopIdentify(): void {
    this.stopRequested = true;
  }

  private async identifyOne(key: string, url: string): Promise<void> {
    this.patch(key, (x) => ({ linkStatus: { ...x.linkStatus, [url]: { state: 'loading' } } }));
    try {
      const res = await firstValueFrom(this.api.lookup(url));
      if (res.status === 'ok' && res.data) {
        const d = res.data;
        this.patch(key, (x) => ({
          name: x.name_source === 'url' || !x.name.trim() ? (d.name ?? x.name) : x.name,
          name_source: x.name_source === 'url' && d.name ? 'link_text' : x.name_source,
          brand: x.brand ?? d.brand,
          model: x.model ?? d.model,
          category: x.category ?? d.category,
          image_url: x.image_url ?? d.image_url,
          warnings: x.warnings.filter((w) => !w.startsWith('Nome provisório')),
          linkStatus: { ...x.linkStatus, [url]: { state: 'ok', price: d.price_cents, available: d.available } },
        }));
      } else {
        this.patch(key, (x) => ({
          linkStatus: { ...x.linkStatus, [url]: { state: 'fail', message: res.message ?? 'Não consultado.' } },
        }));
      }
    } catch (e) {
      this.patch(key, (x) => ({
        linkStatus: { ...x.linkStatus, [url]: { state: 'fail', message: describeError(e).message } },
      }));
    }
  }

  // ---- Etapa 3: importar -------------------------------------------------------

  doImport(): void {
    const chosen = this.selected();
    if (!chosen.length || this.invalidSelected()) return;
    const payload: ProductInput[] = chosen.map((r) => ({
      name: r.name.trim(),
      brand: r.brand,
      model: r.model,
      category: r.category,
      image_url: r.image_url,
      target_price_cents: parseBRL(r.targetInput),
      offers: r.urls.filter((u) => !u.existing).map((u) => ({ url: u.url })),
    }));
    this.busy.set(true);
    this.error.set(null);
    this.api.importProducts(payload).subscribe({
      next: (res) => this.finish(res),
      error: (e) => {
        this.busy.set(false);
        const body = (e as { error?: ImportResult }).error;
        if (body && Array.isArray(body.created)) this.finish(body);
        else this.error.set(describeError(e).message);
      },
    });
  }

  private finish(res: ImportResult): void {
    this.busy.set(false);
    this.result.set(res);
    this.step.set('done');
  }

  restart(): void {
    this.step.set('upload');
    this.preview.set(null);
    this.rows.set([]);
    this.result.set(null);
    this.text.set('');
    this.error.set(null);
  }

  targetInvalid(r: Row): boolean {
    return Number.isNaN(parseBRL(r.targetInput));
  }

  statusOf(r: Row, url: string): LinkStatus {
    return r.linkStatus[url] ?? { state: 'pending' };
  }

  errorText(fields: Record<string, string>): string {
    return Object.values(fields).join(' ');
  }

  protected value(e: Event): string {
    return (e.target as HTMLInputElement | HTMLTextAreaElement).value;
  }
}
