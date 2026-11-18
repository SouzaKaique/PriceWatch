import { DatePipe } from '@angular/common';
import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';

import { ApiService, HealthResponse, StatsResponse, describeError } from '../../core/api.service';
import { centsToInput, parseBRL } from '../../core/money';
import { AccessInfo, AppSettings, DiagnosticItem, MonitorStatus } from '../../core/models';

/** Saúde do sistema + configurações e execuções do monitoramento. */
@Component({
  selector: 'app-status-page',
  imports: [DatePipe, RouterLink],
  templateUrl: './status.html',
  styles: `
    .metric { font-size: 1.75rem; font-weight: 600; }
    .label { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--pw-muted); }
  `,
})
export class StatusPage implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);

  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly health = signal<HealthResponse | null>(null);
  protected readonly stats = signal<StatsResponse | null>(null);
  protected readonly monitor = signal<MonitorStatus | null>(null);
  protected readonly settings = signal<AppSettings | null>(null);
  protected readonly checkedAt = signal<Date | null>(null);
  protected readonly diagnostics = signal<DiagnosticItem[]>([]);
  protected readonly access = signal<AccessInfo | null>(null);

  protected readonly saving = signal(false);
  protected readonly saveMsg = signal<{ ok: boolean; text: string } | null>(null);
  protected readonly minChangeReais = signal('');

  protected readonly intervals = [30, 60, 120, 180, 240, 360, 720, 1440];
  protected readonly reasonLabel: Partial<Record<string, string>> = {
    scheduled: 'Agendada',
    manual: 'Manual',
    startup: 'Retomada',
  };
  private poll?: ReturnType<typeof setInterval>;

  ngOnInit(): void {
    this.refresh();
  }

  ngOnDestroy(): void {
    if (this.poll) clearInterval(this.poll);
  }

  refresh(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.diagnostics().subscribe({ next: (d) => this.diagnostics.set(d.items), error: () => this.diagnostics.set([]) });
    this.api.access().subscribe({ next: (a) => this.access.set(a), error: () => this.access.set(null) });
    forkJoin({
      health: this.api.health(),
      stats: this.api.stats(),
      monitor: this.api.monitor(),
      settings: this.api.settings(),
    }).subscribe({
      next: ({ health, stats, monitor, settings }) => {
        this.health.set(health);
        this.stats.set(stats);
        this.monitor.set(monitor);
        this.settings.set(settings);
        this.minChangeReais.set(centsToInput(settings.min_change_cents));
        this.checkedAt.set(new Date());
        this.loading.set(false);
        this.watch(monitor.running);
      },
      error: () => {
        this.health.set(null);
        this.stats.set(null);
        this.error.set(
          'Não foi possível conectar à API. Verifique se o backend está rodando em http://127.0.0.1:5000.',
        );
        this.checkedAt.set(new Date());
        this.loading.set(false);
      },
    });
  }

  private watch(running: boolean): void {
    if (running && !this.poll) {
      this.poll = setInterval(() => {
        this.api.monitor().subscribe((m) => {
          this.monitor.set(m);
          if (!m.running) {
            clearInterval(this.poll);
            this.poll = undefined;
            this.refresh();
          }
        });
      }, 4000);
    }
  }

  runNow(): void {
    this.api.runMonitor().subscribe({
      next: () => this.api.monitor().subscribe((m) => {
        this.monitor.set({ ...m, running: true });
        this.watch(true);
      }),
      error: (e) => this.saveMsg.set({ ok: false, text: describeError(e).message }),
    });
  }

  save(patch: Partial<AppSettings>): void {
    this.saving.set(true);
    this.saveMsg.set(null);
    this.api.updateSettings(patch).subscribe({
      next: (s) => {
        this.settings.set(s);
        this.saving.set(false);
        this.saveMsg.set({ ok: true, text: 'Configurações salvas.' });
        this.api.monitor().subscribe((m) => this.monitor.set(m));
      },
      error: (e) => {
        const d = describeError(e);
        this.saving.set(false);
        this.saveMsg.set({ ok: false, text: Object.values(d.fields)[0] ?? d.message });
      },
    });
  }

  saveThresholds(percent: string): void {
    const pct = Number(percent.replace(',', '.'));
    const cents = parseBRL(this.minChangeReais()) ?? 0;
    if (!Number.isFinite(pct) || Number.isNaN(cents)) {
      this.saveMsg.set({ ok: false, text: 'Valores inválidos.' });
      return;
    }
    this.save({ min_change_percent: pct, min_change_cents: cents });
  }

  intervalLabel(min: number): string {
    return min < 60 ? `${min} min` : min % 60 === 0 ? `${min / 60} h` : `${(min / 60).toFixed(1)} h`;
  }

  protected value(e: Event): string {
    return (e.target as HTMLInputElement | HTMLSelectElement).value;
  }
}
