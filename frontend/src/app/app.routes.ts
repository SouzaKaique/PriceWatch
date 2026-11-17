import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    title: 'PRICE WATCH',
    loadComponent: () => import('./pages/dashboard/dashboard').then((m) => m.DashboardPage),
  },
  {
    path: 'produtos/novo',
    title: 'Novo produto · PRICE WATCH',
    loadComponent: () => import('./pages/product-form/product-form').then((m) => m.ProductFormPage),
  },
  {
    path: 'produtos/:id/editar',
    title: 'Editar produto · PRICE WATCH',
    loadComponent: () => import('./pages/product-form/product-form').then((m) => m.ProductFormPage),
  },
  {
    path: 'produtos/:id',
    title: 'Produto · PRICE WATCH',
    loadComponent: () =>
      import('./pages/product-detail/product-detail').then((m) => m.ProductDetailPage),
  },
  {
    path: 'cupons',
    title: 'Cupons · PRICE WATCH',
    loadComponent: () => import('./pages/coupons/coupons').then((m) => m.CouponsPage),
  },
  {
    path: 'alertas',
    title: 'Alertas · PRICE WATCH',
    loadComponent: () => import('./pages/alerts/alerts').then((m) => m.AlertsPage),
  },
  {
    path: 'integracoes',
    title: 'Integrações · PRICE WATCH',
    loadComponent: () => import('./pages/integrations/integrations').then((m) => m.IntegrationsPage),
  },
  {
    path: 'status',
    title: 'Sistema · PRICE WATCH',
    loadComponent: () => import('./pages/status/status').then((m) => m.StatusPage),
  },
  { path: '**', redirectTo: '' },
];
