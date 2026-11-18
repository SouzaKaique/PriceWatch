import { Component, computed, input, signal } from '@angular/core';

/** Ícone por categoria para quando a loja não fornece foto. */
export function categoryIcon(category: string | null | undefined): string {
  const c = (category ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const map: [RegExp, string][] = [
    [/monitor|tela|display/, 'bi-display'],
    [/placa.*video|gpu|grafic/, 'bi-gpu-card'],
    [/processador|cpu/, 'bi-cpu'],
    [/ssd|hd|armazen|memoria|pendrive/, 'bi-device-ssd'],
    [/notebook|laptop/, 'bi-laptop'],
    [/headset|fone|audio|caixa de som/, 'bi-headphones'],
    [/mouse/, 'bi-mouse'],
    [/teclado/, 'bi-keyboard'],
    [/periferic/, 'bi-mouse2'],
    [/cadeira/, 'bi-person-workspace'],
    [/celular|smartphone/, 'bi-phone'],
    [/console|game|playstation|xbox|nintendo|jogo/, 'bi-controller'],
    [/tv|televis/, 'bi-tv'],
    [/camera|webcam/, 'bi-camera'],
    [/roteador|rede/, 'bi-router'],
  ];
  return map.find(([re]) => re.test(c))?.[1] ?? 'bi-box-seam';
}

/** Foto do produto (fundo branco, sem cortar) com reserva elegante quando não há imagem. */
@Component({
  selector: 'app-product-image',
  template: `
    <div class="thumb" [class.empty]="!showImage()" [style.aspect-ratio]="ratio()">
      @if (showImage()) {
        <img [src]="src()!" [alt]="alt()" loading="lazy" referrerpolicy="no-referrer" (error)="failed.set(true)" />
      } @else {
        <i class="bi {{ icon() }}" aria-hidden="true"></i>
      }
      <ng-content />
    </div>
  `,
})
export class ProductImage {
  readonly src = input<string | null | undefined>(null);
  readonly alt = input('');
  readonly category = input<string | null | undefined>(null);
  readonly ratio = input('4 / 3');

  protected readonly failed = signal(false);
  protected readonly showImage = computed(() => !!this.src() && !this.failed());
  protected readonly icon = computed(() => categoryIcon(this.category()));
}
