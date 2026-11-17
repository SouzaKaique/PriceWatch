import { Injectable, inject, signal } from '@angular/core';
import { SwUpdate } from '@angular/service-worker';

interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

const IOS_TIP_KEY = 'pricewatch.iosTipDismissed';

/** Instalação do PWA, atualização de versão e estado de conexão. */
@Injectable({ providedIn: 'root' })
export class PwaService {
  private readonly swUpdate = inject(SwUpdate);
  private deferredPrompt: BeforeInstallPromptEvent | null = null;

  readonly canInstall = signal(false);
  readonly updateReady = signal(false);
  readonly online = signal(typeof navigator === 'undefined' ? true : navigator.onLine);
  readonly standalone = signal(false);
  readonly showIosTip = signal(false);

  init(): void {
    const mq = window.matchMedia?.('(display-mode: standalone)');
    const isStandalone = !!mq?.matches || (navigator as unknown as { standalone?: boolean }).standalone === true;
    this.standalone.set(isStandalone);

    window.addEventListener('beforeinstallprompt', (e) => {
      e.preventDefault();
      this.deferredPrompt = e as BeforeInstallPromptEvent;
      this.canInstall.set(true);
    });
    window.addEventListener('appinstalled', () => {
      this.canInstall.set(false);
      this.deferredPrompt = null;
    });
    window.addEventListener('online', () => this.online.set(true));
    window.addEventListener('offline', () => this.online.set(false));

    // iPhone/iPad no Safari: não há prompt automático — mostra a dica uma vez.
    const ua = navigator.userAgent;
    const isIos = /iPad|iPhone|iPod/.test(ua) || (ua.includes('Macintosh') && navigator.maxTouchPoints > 1);
    let dismissed = false;
    try {
      dismissed = localStorage.getItem(IOS_TIP_KEY) === '1';
    } catch {
      /* ignore */
    }
    this.showIosTip.set(isIos && !isStandalone && !dismissed);

    if (this.swUpdate.isEnabled) {
      this.swUpdate.versionUpdates.subscribe((evt) => {
        if (evt.type === 'VERSION_READY') this.updateReady.set(true);
      });
      // verifica novas versões a cada 30 min enquanto aberto
      setInterval(() => this.swUpdate.checkForUpdate().catch(() => undefined), 30 * 60 * 1000);
    }
  }

  async install(): Promise<void> {
    if (!this.deferredPrompt) return;
    await this.deferredPrompt.prompt();
    await this.deferredPrompt.userChoice;
    this.deferredPrompt = null;
    this.canInstall.set(false);
  }

  dismissIosTip(): void {
    this.showIosTip.set(false);
    try {
      localStorage.setItem(IOS_TIP_KEY, '1');
    } catch {
      /* ignore */
    }
  }

  async applyUpdate(): Promise<void> {
    await this.swUpdate.activateUpdate().catch(() => undefined);
    document.location.reload();
  }
}
