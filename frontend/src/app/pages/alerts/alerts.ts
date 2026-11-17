import { DatePipe } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { SwPush } from '@angular/service-worker';
import { firstValueFrom } from 'rxjs';

import { ApiService, describeError } from '../../core/api.service';
import { AppSettings, EventKind, NotificationLogEntry, NotificationStatus } from '../../core/models';

@Component({
  selector: 'app-alerts-page',
  imports: [DatePipe],
  templateUrl: './alerts.html',
})
export class AlertsPage implements OnInit {
  private readonly api = inject(ApiService);
  protected readonly swPush = inject(SwPush);
  /** Inscrição de push deste aparelho (null = não inscrito). */
  protected readonly pushSub = toSignal(this.swPush.subscription, { initialValue: null });
  protected readonly secure = typeof window !== 'undefined' && window.isSecureContext;

  protected readonly status = signal<NotificationStatus | null>(null);
  protected readonly log = signal<NotificationLogEntry[]>([]);
  protected readonly loading = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected readonly msg = signal<{ ok: boolean; text: string } | null>(null);
  protected readonly suggestedTopic = signal(this.randomTopic());
  protected readonly topicCopied = signal(false);

  protected readonly kinds: { key: EventKind; label: string; hint: string }[] = [
    { key: 'target_reached', label: 'Preço-alvo atingido', hint: 'o menor preço chegou ao valor que você definiu' },
    { key: 'price_drop', label: 'Queda relevante de preço', hint: 'acima dos limites definidos em Sistema' },
    { key: 'lowest_ever', label: 'Menor preço registrado', hint: 'com pelo menos 3 consultas anteriores' },
    { key: 'opportunity', label: 'Ótima oportunidade identificada', hint: 'pela análise de preços' },
    { key: 'coupon_available', label: 'Cupom disponível', hint: 'que se aplica a um produto monitorado' },
    { key: 'back_in_stock', label: 'Produto voltou ao estoque', hint: '' },
    { key: 'better_store', label: 'Oferta melhor em outra loja', hint: '' },
    { key: 'price_increase', label: 'Aumento de preço', hint: '' },
    { key: 'out_of_stock', label: 'Produto ficou indisponível', hint: '' },
    { key: 'misleading_promo', label: 'Possível promoção enganosa', hint: '' },
  ];

  protected readonly channelLabel: Partial<Record<string, string>> = { telegram: 'Telegram', ntfy: 'ntfy', webpush: 'Web Push' };

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.api.notificationStatus().subscribe({
      next: (s) => {
        this.status.set(s);
        this.loading.set(false);
      },
      error: (e) => {
        this.error.set(describeError(e).message);
        this.loading.set(false);
      },
    });
    this.api.notificationLog(30).subscribe({ next: (l) => this.log.set(l) });
  }

  connectTelegram(): void {
    this.run(this.api.telegramConnect(), (r) => {
      this.status.set(r);
      this.msg.set({ ok: true, text: `Conectado ao chat de ${r.chat_name} via @${r.bot_username}.` });
    });
  }

  disconnectTelegram(): void {
    this.run(this.api.telegramDisconnect(), (s) => {
      this.status.set(s);
      this.msg.set({ ok: true, text: 'Chat do Telegram desconectado.' });
    });
  }

  sendTest(): void {
    this.run(this.api.sendTestNotification(), (r) => {
      const parts = Object.entries(r.results).map(
        ([ch, res]) => `${this.channelLabel[ch] ?? ch}: ${res.ok ? 'enviado' : 'falhou — ' + res.error}`,
      );
      this.msg.set({ ok: Object.values(r.results).every((x) => x.ok), text: parts.join(' · ') + '. Confira o celular.' });
      this.api.notificationLog(30).subscribe((l) => this.log.set(l));
    });
  }

  async enablePush(): Promise<void> {
    this.busy.set(true);
    this.msg.set(null);
    try {
      const { public_key } = await firstValueFrom(this.api.pushKey());
      const sub = await this.swPush.requestSubscription({ serverPublicKey: public_key });
      const st = await firstValueFrom(this.api.pushSubscribe(sub.toJSON()));
      this.status.set(st);
      this.msg.set({ ok: true, text: 'Notificações ativadas neste aparelho. Use "Enviar teste" para conferir.' });
    } catch (e) {
      const denied = typeof Notification !== 'undefined' && Notification.permission === 'denied';
      this.msg.set({
        ok: false,
        text: denied
          ? 'Permissão de notificação negada. Libere nas configurações do navegador/aparelho e tente de novo.'
          : 'Não foi possível ativar: ' + (describeError(e).message ?? String(e)),
      });
    } finally {
      this.busy.set(false);
    }
  }

  async disablePush(): Promise<void> {
    const sub = this.pushSub();
    if (!sub) return;
    this.busy.set(true);
    try {
      const st = await firstValueFrom(this.api.pushUnsubscribe(sub.endpoint));
      await this.swPush.unsubscribe().catch(() => undefined);
      this.status.set(st);
      this.msg.set({ ok: true, text: 'Notificações desativadas neste aparelho.' });
    } finally {
      this.busy.set(false);
    }
  }

  dispatchNow(): void {
    this.run(this.api.dispatchNotifications(), (r) => {
      this.msg.set({
        ok: true,
        text: `${r.sent} enviado(s), ${r.held} aguardando (silêncio/limite), ${r.skipped} descartado(s).`,
      });
      this.load();
    });
  }

  save(patch: Partial<AppSettings>): void {
    this.run(this.api.updateSettings(patch), () => {
      this.msg.set({ ok: true, text: 'Preferências salvas.' });
      this.api.notificationStatus().subscribe((s) => this.status.set(s));
    });
  }

  toggleKind(key: EventKind, value: boolean): void {
    this.save({ notify_kinds: { [key]: value } });
  }

  async copyTopic(): Promise<void> {
    try {
      await navigator.clipboard.writeText(this.suggestedTopic());
      this.topicCopied.set(true);
      setTimeout(() => this.topicCopied.set(false), 2000);
    } catch {
      /* o usuário pode selecionar o texto manualmente */
    }
  }

  private randomTopic(): string {
    const bytes = new Uint8Array(12);
    crypto.getRandomValues(bytes);
    return 'pricewatch-' + Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  }

  private run<T>(obs: import('rxjs').Observable<T>, ok: (v: T) => void): void {
    this.busy.set(true);
    this.msg.set(null);
    obs.subscribe({
      next: (v) => {
        this.busy.set(false);
        ok(v);
      },
      error: (e) => {
        this.busy.set(false);
        const d = describeError(e);
        this.msg.set({ ok: false, text: Object.values(d.fields)[0] ?? d.message });
      },
    });
  }

  protected value(e: Event): string {
    return (e.target as HTMLInputElement).value;
  }
}
