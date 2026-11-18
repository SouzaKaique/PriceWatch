export type StoreKey = 'kabum' | 'pichau' | 'mercadolivre' | 'amazon' | string;

export interface Store {
  key: StoreKey;
  name: string;
  domains: string[];
}

export interface Offer {
  id: number;
  product_id: number;
  store: StoreKey;
  url: string;
  store_product_id: string | null;
  title: string | null;
  brand: string | null;
  model: string | null;
  mpn: string | null;
  gtin: string | null;
  image_url: string | null;
  current_price_cents: number | null;
  previous_price_cents: number | null;
  list_price_cents: number | null;
  installment_price_cents: number | null;
  shipping_cents: number | null;
  price_source: 'auto' | 'manual' | null;
  available: boolean | null;
  match_confirmed: boolean;
  last_checked_at: string | null;
  last_status: OfferStatus | null;
  last_error: string | null;
  /** Sugestão de correspondência (só presente no detalhe do produto). */
  match?: MatchHint;
  analysis?: AnalysisBrief | null;
}

export type OfferStatus = 'ok' | 'error' | 'blocked' | 'not_found' | 'rate_limited' | 'unsupported';

export interface MatchHint {
  level: 'strong' | 'possible' | 'mismatch' | 'unknown';
  reasons: string[];
}

export interface LookupData {
  store: StoreKey;
  url: string;
  store_product_id: string | null;
  name: string | null;
  brand: string | null;
  model: string | null;
  mpn: string | null;
  gtin: string | null;
  category: string | null;
  image_url: string | null;
  price_cents: number | null;
  list_price_cents: number | null;
  installment_price_cents: number | null;
  available: boolean | null;
  variations: string[];
  source: string;
}

export interface LookupResult {
  url: string;
  store: StoreKey | null;
  store_name: string | null;
  status: 'ok' | Exclude<OfferStatus, 'ok'>;
  message: string | null;
  data: LookupData | null;
}

export interface ProductSummary {
  best_price_cents: number | null;
  best_store: StoreKey | null;
  best_offer_id: number | null;
  best_url: string | null;
  highest_price_cents: number | null;
  variation_percent: number | null;
  target_reached: boolean;
  offer_count: number;
  priced_offer_count: number;
  stores: StoreKey[];
  last_checked_at: string | null;
  analysis: AnalysisBrief | null;
}

export interface Product {
  id: number;
  name: string;
  brand: string | null;
  model: string | null;
  manufacturer_code: string | null;
  category: string | null;
  image_url: string | null;
  target_price_cents: number | null;
  notes: string | null;
  active: boolean;
  created_at: string;
  updated_at: string;
  offers: Offer[];
  summary: ProductSummary;
}

export interface ProductInput {
  name?: string;
  brand?: string | null;
  model?: string | null;
  manufacturer_code?: string | null;
  category?: string | null;
  image_url?: string | null;
  target_price_cents?: number | null;
  notes?: string | null;
  active?: boolean;
  offers?: { url: string; store?: StoreKey }[];
}

export interface Stats {
  products: number;
  products_total: number;
  stores: number;
  offers: number;
  priced_offers: number;
  target_reached: number;
  opportunities: number;
  biggest_drop: {
    amount_cents: number;
    percent: number;
    product_id: number;
    product_name: string;
    store: StoreKey;
  } | null;
  potential_savings_cents: number;
  last_check_at: string | null;
  scheduler_active: boolean;
  next_check_at: string | null;
  monitor_running: boolean;
}

export interface HealthResponse {
  status: 'ok' | 'degraded';
  app: string;
  version: string;
  database: string;
  check_interval_minutes: number;
}

/** Erro de validação retornado pela API (HTTP 422). */
export interface ValidationError {
  error: 'validation';
  fields: Record<string, string>;
}

export interface Integration {
  key: StoreKey;
  name: string;
  method: string;
  limitation: string | null;
  state: 'available' | 'limited' | 'connected' | 'app_token' | 'not_configured';
  paused_seconds: number;
  stats: {
    offers: number;
    by_status: Record<string, number>;
    last_success_at: string | null;
    last_error: string | null;
  };
  mercadolivre?: {
    configured: boolean;
    redirect_uri_configured: boolean;
    user_connected: boolean;
    mode: 'app' | 'user' | null;
    last_error: string | null;
  };
}

export type EventKind =
  | 'price_drop'
  | 'price_increase'
  | 'back_in_stock'
  | 'out_of_stock'
  | 'lowest_ever'
  | 'target_reached'
  | 'better_store'
  | 'opportunity'
  | 'misleading_promo'
  | 'coupon_available';

export interface PriceEvent {
  id: number;
  kind: EventKind;
  product_id: number | null;
  offer_id: number | null;
  store: StoreKey | null;
  old_price_cents: number | null;
  new_price_cents: number | null;
  message: string;
  source: 'auto' | 'manual';
  notified: boolean;
  created_at: string;
}

export interface HistoryPoint {
  t: string;
  price_cents: number | null;
  available: boolean | null;
  source: 'auto' | 'manual';
}

export interface HistorySeries {
  offer_id: number;
  store: StoreKey;
  points: HistoryPoint[];
}

export interface ProductHistory {
  product_id: number;
  target_price_cents: number | null;
  days: number;
  monitoring_since: string | null;
  series: HistorySeries[];
}

export interface MonitorRun {
  id: number;
  reason: 'scheduled' | 'manual' | 'startup';
  status: 'running' | 'done' | 'failed';
  started_at: string;
  finished_at: string | null;
  offers_checked: number;
  offers_ok: number;
  offers_failed: number;
  offers_skipped: number;
  events: number;
  error: string | null;
}

export interface MonitorStatus {
  scheduler_active: boolean;
  paused: boolean;
  next_run_at: string | null;
  running: boolean;
  enabled: boolean;
  interval_minutes: number;
  runs: MonitorRun[];
}

export interface AppSettings {
  monitor_enabled: boolean;
  check_interval_minutes: number;
  min_change_percent: number;
  min_change_cents: number;
  notify_enabled: boolean;
  notify_kinds: Partial<Record<EventKind, boolean>>;
  notify_quiet_enabled: boolean;
  notify_quiet_start: string;
  notify_quiet_end: string;
  notify_max_per_hour: number;
}

export type Classification =
  | 'great'
  | 'good'
  | 'average'
  | 'above'
  | 'weak_discount'
  | 'misleading'
  | 'insufficient';

export interface AnalysisBrief {
  classification: Classification;
  label: string;
  tone: 'green' | 'muted' | 'orange' | 'red';
  headline: string | null;
}

export interface WindowStats {
  days_with_data: number;
  sufficient: boolean;
  avg_cents: number | null;
  min_cents: number | null;
  max_cents: number | null;
}

export interface PromoContext {
  name: string;
  start: string;
  end: string;
  days_until: number;
  ongoing: boolean;
}

export interface OfferAnalysis {
  classification: Classification;
  label: string;
  tone: AnalysisBrief['tone'];
  reasons: string[];
  promo_context: PromoContext | null;
  metrics: {
    current_cents: number | null;
    baseline_cents: number | null;
    baseline_method: string | null;
    lowest: { price_cents: number; at: string; source: 'auto' | 'manual' } | null;
    highest_cents: number | null;
    windows: Record<'7' | '30' | '90' | '180', WindowStats>;
    announced_list_price_cents: number | null;
    announced_discount_pct: number | null;
    real_discount_pct: number | null;
    monitored_days: number;
    days_with_data: number;
  };
}

export interface ProductAnalysis {
  best_offer_id: number | null;
  overall: OfferAnalysis | null;
  lowest_overall: { price_cents: number; at: string; source: 'auto' | 'manual'; store: StoreKey } | null;
  offers: Record<string, OfferAnalysis>;
  promo_context: PromoContext | null;
}

export interface Coupon {
  id: number;
  store: StoreKey;
  code: string;
  description: string | null;
  discount_percent: number | null;
  discount_cents: number | null;
  max_discount_cents: number | null;
  min_purchase_cents: number | null;
  categories: string | null;
  conditions: string | null;
  valid_from: string | null;
  valid_until: string | null;
  link_url: string | null;
  source: string | null;
  origin: 'manual' | 'kabum_official';
  verification_status: 'unconfirmed' | 'user_confirmed' | 'user_failed';
  validity: 'active' | 'upcoming' | 'expired';
  last_seen_at: string | null;
  created_at: string;
}

export interface CouponInput {
  store?: StoreKey;
  code?: string;
  description?: string | null;
  discount_percent?: number | null;
  discount_cents?: number | null;
  min_purchase_cents?: number | null;
  categories?: string | null;
  conditions?: string | null;
  valid_until?: string | null;
  link_url?: string | null;
  source?: string;
  verification_status?: Coupon['verification_status'];
}

export interface CouponSources {
  kabum: {
    source: string;
    last_fetch_at: string | null;
    last_error: string | null;
    next_allowed_at: string | null;
  };
}

export interface ProductCouponItem {
  coupon: Coupon;
  offers: {
    offer_id: number;
    store: StoreKey;
    applicability: { level: 'applies' | 'possible' | 'unknown'; reasons: string[] };
    price_cents: number | null;
    estimated_cents: number | null;
  }[];
}

export interface NotificationStatus {
  channels: {
    telegram: { token_configured: boolean; chat_connected: boolean; bot_username: string | null; ready: boolean };
    ntfy: { configured: boolean; server: string; topic: string | null; ready: boolean };
    webpush: { ready: boolean; devices: number };
  };
  pending: number;
  quiet_now: boolean;
  settings: Pick<
    AppSettings,
    | 'notify_enabled'
    | 'notify_kinds'
    | 'notify_quiet_enabled'
    | 'notify_quiet_start'
    | 'notify_quiet_end'
    | 'notify_max_per_hour'
  >;
}

export interface NotificationLogEntry {
  id: number;
  kind: string;
  product_id: number | null;
  offer_id: number | null;
  event_id: number | null;
  title: string;
  body: string | null;
  url: string | null;
  channel: 'telegram' | 'ntfy' | 'webpush' | null;
  delivered: boolean;
  error: string | null;
  created_at: string;
}

export interface DiagnosticItem {
  key: string;
  label: string;
  status: 'ok' | 'warn' | 'error';
  detail: string;
  hint: string | null;
}

export interface AccessInfo {
  mode: 'local' | 'wifi' | 'rede_sem_https';
  https: boolean;
  host: string;
  port: number;
  lan_ips: string[];
  app_urls: string[];
  cert_page_urls: string[];
  certificate: { ips: string[]; names: string[]; expires_at: string; days_left: number } | null;
  certificate_covers_ips: boolean;
  access_key_required: boolean;
}

export interface ImportUrl {
  url: string;
  store: StoreKey;
  store_name: string;
  existing: { product_id: number; name: string } | null;
}

export interface ImportItem {
  key: string;
  name: string;
  name_source: 'link_text' | 'line' | 'url';
  urls: ImportUrl[];
  price_seen_cents: number | null;
  target_price_cents: number | null;
  line: string;
  checked: boolean;
  warnings: string[];
}

export interface ImportPreview {
  source: { type: 'pdf' | 'text'; name: string };
  stats: {
    pages: number | null;
    links: number | null;
    product_links: number | null;
    items: number;
    with_links: number;
    already_monitored: number;
  };
  items: ImportItem[];
  warnings: string[];
}

export interface ImportResult {
  created: { index: number; id: number; name: string; offers: number; ignored_links: string[] }[];
  skipped: { index: number; name: string | null; reason: string }[];
  errors: { index: number; name: string | null; fields: Record<string, string> }[];
}
