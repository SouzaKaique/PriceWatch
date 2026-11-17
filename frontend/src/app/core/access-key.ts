import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { catchError, throwError } from 'rxjs';

const STORAGE_KEY = 'pricewatch.apiKey';

/**
 * Chave de acesso opcional (API_ACCESS_KEY no backend). Quando a API responde 401,
 * o app pede a chave uma vez e a guarda neste aparelho.
 */
@Injectable({ providedIn: 'root' })
export class AccessKeyService {
  readonly required = signal(false);

  get(): string | null {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch {
      return null;
    }
  }

  set(key: string): void {
    try {
      localStorage.setItem(STORAGE_KEY, key.trim());
    } catch {
      /* armazenamento indisponível (modo privado): a chave vale só nesta sessão */
    }
    this.required.set(false);
  }

  clear(): void {
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }
}

export const accessKeyInterceptor: HttpInterceptorFn = (req, next) => {
  const svc = inject(AccessKeyService);
  const key = svc.get();
  const request = key && req.url.startsWith('/api') ? req.clone({ setHeaders: { 'X-API-Key': key } }) : req;
  return next(request).pipe(
    catchError((err: unknown) => {
      if (err instanceof HttpErrorResponse && err.status === 401 && req.url.startsWith('/api')) {
        if (key) svc.clear(); // chave salva deixou de valer
        svc.required.set(true);
      }
      return throwError(() => err);
    }),
  );
};
