import { Pipe, PipeTransform } from '@angular/core';

const BRL = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });

export function formatCents(cents: number | null | undefined): string {
  return cents === null || cents === undefined ? '—' : BRL.format(cents / 100);
}

/**
 * Converte o texto digitado ("1.299,90", "1299.90", "R$ 750") em centavos.
 * Retorna null para vazio e NaN para valor inválido.
 */
export function parseBRL(input: string | null | undefined): number | null {
  let s = (input ?? '').replace(/R\$|\s/g, '');
  if (!s) return null;
  if (s.includes(',')) s = s.replace(/\./g, '').replace(',', '.');
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return NaN;
  return Math.round(Number(s) * 100);
}

/** Centavos → texto para preencher um campo de formulário ("1299,90"). */
export function centsToInput(cents: number | null | undefined): string {
  return cents === null || cents === undefined ? '' : (cents / 100).toFixed(2).replace('.', ',');
}

@Pipe({ name: 'brl' })
export class BrlPipe implements PipeTransform {
  transform(cents: number | null | undefined): string {
    return formatCents(cents);
  }
}
