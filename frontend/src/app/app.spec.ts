import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { provideServiceWorker } from '@angular/service-worker';

import { App } from './app';
import { AccessKeyService, accessKeyInterceptor } from './core/access-key';

describe('App', () => {
  beforeEach(async () => {
    localStorage.clear();
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [
        provideRouter([]),
        provideHttpClient(withInterceptors([accessKeyInterceptor])),
        provideHttpClientTesting(),
        provideServiceWorker('ngsw-worker.js', { enabled: false }),
      ],
    }).compileComponents();
  });

  it('should create the app', () => {
    const fixture = TestBed.createComponent(App);
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('should render the brand', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('.brand')?.textContent).toContain('PRICE WATCH');
  });

  it('asks for the access key on 401 and sends it afterwards', () => {
    const http = TestBed.inject(HttpClient);
    const ctrl = TestBed.inject(HttpTestingController);
    const keys = TestBed.inject(AccessKeyService);

    http.get('/api/products').subscribe({ error: () => undefined });
    ctrl.expectOne('/api/products').flush({ error: 'unauthorized' }, { status: 401, statusText: 'Unauthorized' });
    expect(keys.required()).toBe(true);

    keys.set('segredo');
    http.get('/api/products').subscribe();
    const req = ctrl.expectOne('/api/products');
    expect(req.request.headers.get('X-API-Key')).toBe('segredo');
    req.flush([]);
    ctrl.verify();
  });
});
