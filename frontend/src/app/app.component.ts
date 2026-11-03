import { Component, OnInit, OnDestroy, ViewChild, ElementRef, ViewEncapsulation } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { NgxChartsModule } from '@swimlane/ngx-charts';
import { Observable, throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';

/** Change this one line if your backend URL changes. */
const API = location.hostname === 'localhost'
  ? 'http://localhost:8000/api'
  : 'https://upi-analyzer.onrender.com/api';

const PALETTE = ['#60a5fa', '#f97316', '#4ade80', '#a78bfa', '#fbbf24', '#f87171',
                 '#22d3ee', '#f472b6', '#34d399', '#fb923c', '#c084fc', '#2dd4bf'];
const FIXED_COLORS: Record<string, string> = {
  'Travel': PALETTE[0], 'Food & Grocery': PALETTE[1], 'Healthcare': PALETTE[2], 'Shopping': PALETTE[3],
  'Transport': PALETTE[4], 'Credit Card': PALETTE[5], 'Utilities': PALETTE[6], 'Entertainment': PALETTE[7],
  'Education': PALETTE[8], 'Transfer': '#94a3b8', 'Other': '#64748b',
};
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const TAB_NAMES: Record<string, string> = {
  overview: 'Overview', analytics: 'Analytics', transactions: 'Transactions',
  ai: 'AI Chat', about: 'About', admin: 'Admin',
};

interface Msg { role: 'user' | 'assistant'; text: string; loading?: boolean; meta?: string; error?: boolean; }
interface User { id: number; email: string; name: string; is_admin: boolean; }
interface AboutBlock { title?: string; items?: string[]; ordered?: boolean; text?: string; }

@Component({
  selector: 'app-root',
  standalone: true,
  encapsulation: ViewEncapsulation.None,
  imports: [CommonModule, FormsModule, NgxChartsModule],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css',
})
export class AppComponent implements OnInit, OnDestroy {
  @ViewChild('chatWin') chatWin?: ElementRef<HTMLElement>;

  // ── auth ──
  user: User | null = null;
  authMode: 'login' | 'register' = 'login';
  authName = ''; authEmail = ''; authPassword = '';
  authError = ''; authLoading = false;

  // ── shell ──
  tab = 'overview';
  sidebarOpen = false;
  toast = { msg: '', ok: true };
  private toastTimer: any;
  showPw = false; pwCurrent = ''; pwNew = ''; pwConfirm = ''; pwMsg = ''; pwOk = false; pwBusy = false;

  // ── data ──
  analytics: any = null;
  transactions: any[] = [];
  filteredTxns: any[] = [];
  totalStored = 0;
  dateMin = ''; dateMax = '';
  filterFrom = ''; filterTo = '';
  uploading = false;
  loadingData = false;
  allCategories: string[] = [];

  // ── transactions table ──
  fType = ''; fCat = ''; fStatus = ''; fSearch = '';
  showN = 100;
  editingId: number | null = null;
  editVal = ''; editNew = '';

  // ── chart data ──
  pieData: any[] = []; pieScheme: any = { domain: PALETTE };
  monthlyData: any[] = []; merchantData: any[] = []; weekdayData: any[] = [];
  weeklyData: any[] = []; compareData: any[] = []; incomeData: any[] = []; recurringTop: any[] = [];
  schemeMain: any = { domain: PALETTE };
  schemeCompare: any = { domain: ['#f87171', '#4ade80'] };
  schemeGreen: any = { domain: ['#4ade80', '#34d399', '#6ee7b7', '#86efac', '#bbf7d0'] };
  schemeLine: any = { domain: ['#60a5fa'] };

  // ── AI ──
  messages: Msg[] = [];
  question = '';
  chatLoading = false;
  ai: any = null;           // {running, provider, model, error}
  index: any = null;        // {status, count, error}
  suggestions = ['How much did I spend in total?', 'Which category costs me the most?',
                 'Who sends me money the most?', 'Show my biggest payments', 'How did my spending change month to month?'];

  // ── about + suggestions ──
  about: any = {};
  aboutBlocks: AboutBlock[] = [];
  editingAbout = false; aboutEdit: any = {}; aboutSaving = false;
  sgCategory = 'feature'; sgTitle = ''; sgMsg = ''; sgSending = false; sgSent = false; sgError = '';
  readonly sgCategories = [
    { id: 'feature', icon: '💡', label: 'Feature' }, { id: 'bug', icon: '🐞', label: 'Bug' },
    { id: 'design', icon: '🎨', label: 'Design' },   { id: 'other', icon: '💬', label: 'Other' },
  ];

  // ── admin ──
  adminTab: 'users' | 'suggestions' = 'users';
  adminStats: any = null;
  adminUsers: any[] = [];
  adminSugg: any[] = [];
  adminLoading = false;
  userSearch = ''; suggFilter = 'all';

  private hbTimer: any; private adminTimer: any;

  constructor(private http: HttpClient) {}

  // ═════════════ lifecycle ═════════════
  ngOnInit() {
    this.loadAbout();
    const token = localStorage.getItem('upi_token');
    if (!token) return;
    try { this.user = JSON.parse(localStorage.getItem('upi_user') || 'null'); } catch { this.user = null; }
    // refresh from the server so role changes (e.g. admin) apply without signing in again
    this.call<User>('GET', '/auth/me').subscribe({
      next: u => { this.setUser(u); this.startSession(); },
      error: () => { /* 401 handled by call() */ },
    });
  }
  ngOnDestroy() { this.stopTimers(); }

  private setUser(u: User) {
    this.user = u;
    localStorage.setItem('upi_user', JSON.stringify(u));
  }
  get isAdmin(): boolean { return !!this.user?.is_admin; }

  private startSession() {
    this.resetData();
    this.loadRange();
    this.loadCategories();
    this.checkAi();
    this.stopTimers();
    this.sendHeartbeat();
    this.hbTimer = setInterval(() => this.sendHeartbeat(), 30000);
    this.adminTimer = setInterval(() => { if (this.tab === 'admin' && this.isAdmin) this.loadAdmin(false); }, 15000);
  }
  private stopTimers() { clearInterval(this.hbTimer); clearInterval(this.adminTimer); }
  private sendHeartbeat() {
    if (!this.user) return;
    this.call('POST', '/heartbeat', { tab: TAB_NAMES[this.tab] || this.tab }).subscribe({ error: () => {} });
  }

  // ═════════════ http ═════════════
  private headers(): HttpHeaders {
    const t = localStorage.getItem('upi_token');
    return new HttpHeaders(t ? { Authorization: `Bearer ${t}` } : {});
  }
  private call<T = any>(method: string, path: string, body?: any, params?: Record<string, string>): Observable<T> {
    return this.http.request<T>(method, API + path, { body, params, headers: this.headers() }).pipe(
      catchError(e => {
        if (e.status === 401 && this.user && !path.startsWith('/auth/login')) this.logout(true);
        return throwError(() => e);
      }));
  }
  errText(e: any, fallback = 'Something went wrong'): string {
    if (e?.status === 0) return 'Cannot reach the server. If it was idle, wait ~30 seconds and retry.';
    const d = e?.error?.detail;
    return typeof d === 'string' ? d : fallback;
  }
  flash(msg: string, ok = true) {
    this.toast = { msg, ok };
    clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => this.toast = { msg: '', ok: true }, 4500);
  }

  // ═════════════ auth ═════════════
  submitAuth() {
    this.authError = '';
    if (!this.authEmail.trim() || !this.authPassword || (this.authMode === 'register' && !this.authName.trim())) {
      this.authError = 'Please fill in all fields.'; return;
    }
    this.authLoading = true;
    const body = this.authMode === 'login'
      ? { email: this.authEmail, password: this.authPassword }
      : { email: this.authEmail, name: this.authName, password: this.authPassword };
    this.call<any>('POST', this.authMode === 'login' ? '/auth/login' : '/auth/register', body).subscribe({
      next: r => {
        localStorage.setItem('upi_token', r.token);
        this.authLoading = false; this.authPassword = '';
        this.tab = 'overview';
        this.setUser(r.user);
        this.startSession();
      },
      error: e => { this.authLoading = false; this.authError = this.errText(e, 'Sign in failed'); },
    });
  }
  logout(expired = false) {
    if (!expired && localStorage.getItem('upi_token')) {
      this.http.post(API + '/auth/logout', {}, { headers: this.headers() }).subscribe({ error: () => {} });
    }
    this.stopTimers();
    localStorage.removeItem('upi_token'); localStorage.removeItem('upi_user');
    this.user = null; this.tab = 'overview'; this.sidebarOpen = false;
    this.resetData(); this.messages = []; this.question = '';
    this.adminStats = null; this.adminUsers = []; this.adminSugg = [];
    this.ai = null; this.index = null; this.showPw = false;
    if (expired) this.authError = 'Your session ended. Please sign in again.';
  }
  private resetData() {
    this.analytics = null; this.transactions = []; this.filteredTxns = []; this.totalStored = 0;
    this.filterFrom = ''; this.filterTo = ''; this.dateMin = ''; this.dateMax = '';
    this.pieData = []; this.monthlyData = []; this.merchantData = []; this.weekdayData = [];
    this.weeklyData = []; this.compareData = []; this.incomeData = []; this.recurringTop = [];
  }
  changePassword() {
    this.pwMsg = '';
    if (this.pwNew.length < 6) { this.pwMsg = 'New password must be at least 6 characters'; this.pwOk = false; return; }
    if (this.pwNew !== this.pwConfirm) { this.pwMsg = 'Passwords do not match'; this.pwOk = false; return; }
    this.pwBusy = true;
    this.call('POST', '/auth/change-password', { current_password: this.pwCurrent, new_password: this.pwNew }).subscribe({
      next: () => {
        this.pwBusy = false; this.pwOk = true; this.pwMsg = 'Password changed.';
        this.pwCurrent = this.pwNew = this.pwConfirm = '';
        setTimeout(() => { this.showPw = false; this.pwMsg = ''; }, 1400);
      },
      error: e => { this.pwBusy = false; this.pwOk = false; this.pwMsg = this.errText(e); },
    });
  }

  // ═════════════ navigation ═════════════
  go(t: string) {
    this.tab = t; this.sidebarOpen = false;
    this.sendHeartbeat();
    if (t === 'admin') this.loadAdmin();
    if (t === 'ai') { this.checkAi(); this.scrollChat(); }
    if (t === 'about') this.loadAbout();
  }
  get title(): string { return TAB_NAMES[this.tab] || ''; }

  // ═════════════ data ═════════════
  private rangeParams(): Record<string, string> {
    const p: Record<string, string> = {};
    if (this.filterFrom) p['date_from'] = this.filterFrom;
    if (this.filterTo) p['date_to'] = this.filterTo;
    return p;
  }
  loadRange() {
    this.call<any>('GET', '/date-range').subscribe({
      next: r => {
        this.totalStored = r.count || 0; this.dateMin = r.min || ''; this.dateMax = r.max || '';
        if (this.totalStored) this.refresh(); else { this.analytics = null; this.transactions = []; this.filteredTxns = []; }
      },
      error: () => {},
    });
  }
  refresh() {
    this.loadingData = true;
    this.call<any>('GET', '/analytics', undefined, this.rangeParams()).subscribe({
      next: a => { this.analytics = a; this.buildCharts(); this.loadingData = false; },
      error: e => { if (e.status === 404) { this.analytics = null; this.buildCharts(); } this.loadingData = false; },
    });
    this.call<any>('GET', '/transactions', undefined, this.rangeParams()).subscribe({
      next: r => { this.transactions = r.transactions || []; this.applyFilters(); },
      error: () => {},
    });
  }
  private refreshAnalyticsOnly() {
    this.call<any>('GET', '/analytics', undefined, this.rangeParams()).subscribe({
      next: a => { this.analytics = a; this.buildCharts(); },
      error: e => { if (e.status === 404) { this.analytics = null; this.buildCharts(); } },
    });
  }
  loadCategories() {
    this.call<any>('GET', '/categories').subscribe({ next: r => this.allCategories = r.categories || [], error: () => {} });
  }

  // date filter
  onDates() { this.refresh(); }
  allTime() { this.filterFrom = ''; this.filterTo = ''; this.refresh(); }
  thisMonth() {
    const n = new Date();
    this.setRange(new Date(n.getFullYear(), n.getMonth(), 1), new Date(n.getFullYear(), n.getMonth() + 1, 0));
  }
  lastDays(d: number) {
    const to = this.dateMax ? new Date(this.dateMax + 'T00:00:00') : new Date();
    const from = new Date(to); from.setDate(from.getDate() - d + 1);
    this.setRange(from, to);
  }
  private setRange(a: Date, b: Date) {
    const f = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    this.filterFrom = f(a); this.filterTo = f(b); this.refresh();
  }
  get rangeLabel(): string {
    if (!this.filterFrom && !this.filterTo) return 'All time';
    return `${this.filterFrom || '…'} → ${this.filterTo || '…'}`;
  }

  // upload
  onFile(ev: Event) {
    const input = ev.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    const name = file.name.toLowerCase();
    if (!name.endsWith('.csv') && !name.endsWith('.pdf')) { this.flash('Please choose a .csv or .pdf statement', false); return; }
    this.uploading = true;
    const fd = new FormData(); fd.append('file', file);
    this.http.post<any>(API + (name.endsWith('.pdf') ? '/upload' : '/upload-csv'), fd, { headers: this.headers() }).subscribe({
      next: r => {
        this.uploading = false;
        this.flash(`${r.format}: ${r.inserted} new, ${r.skipped} already saved. ${r.total_stored} total.`);
        this.loadRange(); this.loadCategories();
        this.call('POST', '/rag/index').subscribe({ error: () => {} });
      },
      error: e => {
        this.uploading = false;
        if (e.status === 401) this.logout(true); else this.flash(this.errText(e, 'Import failed'), false);
      },
    });
  }
  clearAll() {
    if (!confirm('Delete ALL your saved transactions? This cannot be undone.')) return;
    this.call('DELETE', '/transactions').subscribe({
      next: () => { this.resetData(); this.flash('All transactions deleted'); },
      error: e => this.flash(this.errText(e), false),
    });
  }
  downloadSample() {
    const csv = 'Date\tTime\tTransaction Details\tTransaction ID\tUTR\tTransaction Type\tCredit/debit instrument\tAmount\n' +
      'Jun 15, 2026\t7:20 PM\tReceived from Alex\tT1\t1\tCREDIT\tCredited to XXXXXX0000\t8000\n' +
      'Jun 16, 2026\t1:05 PM\tPaid to Zomato\tT2\t2\tDEBIT\tDebited from XXXXXX0000\t340\n';
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    a.download = 'sample-phonepe.csv'; a.click();
  }

  // ═════════════ formatting ═════════════
  /** compact form for chart axes and labels: ₹850, ₹4.3k, ₹1.2L, ₹2Cr */
  compact = (v: any): string => {
    const n = Number(v) || 0, a = Math.abs(n);
    const f = (x: number) => String(Math.round(x * 10) / 10).replace(/\.0$/, '');
    if (a >= 1e7) return '₹' + f(n / 1e7) + 'Cr';
    if (a >= 1e5) return '₹' + f(n / 1e5) + 'L';
    if (a >= 1e3) return '₹' + f(n / 1e3) + 'k';
    return '₹' + Math.round(n);
  };
  inr = (v: any): string => '₹' + Math.round(Number(v) || 0).toLocaleString('en-IN');
  pct(v: number, total: number): number { return total > 0 ? (v / total) * 100 : 0; }
  monthLabel(k: string): string {
    const [y, m] = (k || '').split('-');
    return MONTHS[+m - 1] ? `${MONTHS[+m - 1]} ${String(y).slice(2)}` : k;
  }
  private utc(iso: string): Date { return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + 'Z'); }
  ago(iso: string | null): string {
    if (!iso) return 'never';
    const s = Math.max(0, (Date.now() - this.utc(iso).getTime()) / 1000);
    if (s < 60) return 'just now';
    if (s < 3600) return `${Math.floor(s / 60)} min ago`;
    if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
    return `${Math.floor(s / 86400)} d ago`;
  }
  when(iso: string | null): string {
    return iso ? this.utc(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }) : '—';
  }
  colorOf(name: string): string {
    if (FIXED_COLORS[name]) return FIXED_COLORS[name];
    let h = 0; for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return PALETTE[h % PALETTE.length];
  }

  // ═════════════ charts ═════════════
  private buildCharts() {
    const a = this.analytics;
    if (!a) {
      this.pieData = []; this.monthlyData = []; this.merchantData = []; this.weekdayData = [];
      this.weeklyData = []; this.compareData = []; this.incomeData = []; this.recurringTop = []; return;
    }
    this.pieData = Object.entries<number>(a.category_breakdown || {})
      .filter(([, v]) => v > 0).sort((x, y) => y[1] - x[1])
      .map(([name, value]) => ({ name, value, color: this.colorOf(name) }));
    this.pieScheme = { domain: this.pieData.map(d => d.color) };
    this.monthlyData = Object.entries<number>(a.monthly_trend || {}).map(([k, v]) => ({ name: this.monthLabel(k), value: v }));
    this.merchantData = (a.top_merchants || []).slice(0, 8).map((m: any) => ({ name: this.short(m.name), value: m.spent }));
    this.recurringTop = (a.recurring_merchants || []).slice(0, 6);
    this.incomeData = (a.top_received_sources || []).map((m: any) => ({ name: this.short(m.name), value: m.received }));
    this.weekdayData = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
      .map(d => ({ name: d.slice(0, 3), value: (a.dow_spending || {})[d] || 0 })).filter(d => d.value > 0);
    const weeks = Object.entries<number>(a.weekly_trend || {});
    this.weeklyData = weeks.length > 1
      ? [{ name: 'Spending', series: weeks.map(([k, v]) => ({ name: k.split('-')[1] || k, value: v })) }] : [];
    this.compareData = (a.monthly_combined || []).map((m: any) => ({
      name: this.monthLabel(m.month),
      series: [{ name: 'Spent', value: m.spent }, { name: 'Received', value: m.received }],
    }));
  }
  private short(s: string): string { return s && s.length > 20 ? s.slice(0, 19) + '…' : s; }

  // ═════════════ transactions table ═════════════
  applyFilters() {
    const q = this.fSearch.trim().toLowerCase();
    this.filteredTxns = this.transactions.filter(t =>
      (!this.fType || t.transaction_type === this.fType) &&
      (!this.fCat || t.category === this.fCat) &&
      (!this.fStatus || (this.fStatus === 'included' ? t.included : !t.included)) &&
      (!q || (t.merchant || '').toLowerCase().includes(q)));
    this.showN = 100;
  }
  get excludedCount(): number { return this.transactions.filter(t => !t.included).length; }
  get txnCategories(): string[] { return [...new Set(this.transactions.map(t => t.category))].sort(); }
  trackId = (_: number, t: any) => t.id;

  toggleIncluded(t: any) {
    const next = !t.included;
    t.included = next;
    this.call<any>('PATCH', `/transactions/${t.id}`, { included: next }).subscribe({
      next: () => this.refreshAnalyticsOnly(),
      error: e => { t.included = !next; this.flash(this.errText(e, 'Could not update'), false); },
    });
  }
  startEdit(t: any) { this.editingId = t.id; this.editVal = t.category; this.editNew = ''; }
  cancelEdit() { this.editingId = null; }
  saveEdit(t: any) {
    const cat = (this.editVal === '__new__' ? this.editNew : this.editVal).trim();
    if (!cat) { this.flash('Enter a category name', false); return; }
    this.call<any>('PATCH', `/transactions/${t.id}`, { category: cat }).subscribe({
      next: r => {
        t.category = r.category; t.custom_category = r.custom_category;
        this.allCategories = r.all_categories || this.allCategories;
        this.editingId = null;
        this.refreshAnalyticsOnly();
        this.flash(`Category set to “${r.category}”`);
      },
      error: e => this.flash(this.errText(e, 'Could not update'), false),
    });
  }

  // ═════════════ AI chat ═════════════
  checkAi() {
    this.call<any>('GET', '/rag/status').subscribe({
      next: r => { this.ai = r.ai; this.index = r.index; },
      error: () => { this.ai = { running: false, error: 'Cannot reach the server' }; },
    });
  }
  reindex() {
    this.call<any>('POST', '/rag/index').subscribe({
      next: () => { this.flash('Re-indexing in the background'); setTimeout(() => this.checkAi(), 2500); },
      error: e => this.flash(this.errText(e), false),
    });
  }
  ask(q: string) { this.question = q; this.send(); }
  send() {
    const q = this.question.trim();
    if (!q || this.chatLoading) return;
    this.messages.push({ role: 'user', text: q });
    const pending: Msg = { role: 'assistant', text: '', loading: true };
    this.messages.push(pending);
    this.question = ''; this.chatLoading = true; this.scrollChat();
    this.call<any>('POST', '/rag/query', { question: q }).subscribe({
      next: r => {
        pending.loading = false; pending.text = r.answer || 'No answer.'; pending.error = !!r.error;
        pending.meta = r.model ? `${r.model} · ${r.retrieval || 'keyword'} search` : '';
        this.chatLoading = false; this.scrollChat(); this.checkAi();
      },
      error: e => {
        pending.loading = false; pending.error = true; this.chatLoading = false;
        pending.text = this.errText(e, 'The server returned an error. Please try again.'); this.scrollChat();
      },
    });
  }
  clearChat() { this.messages = []; }
  private scrollChat() {
    setTimeout(() => { const el = this.chatWin?.nativeElement; if (el) el.scrollTop = el.scrollHeight; }, 30);
  }
  /** escape first, then allow **bold**, bullets and line breaks */
  md(text: string): string {
    return (text || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/^\s*[-*]\s+/gm, '• ').replace(/\n/g, '<br>');
  }

  // ═════════════ about + suggestions ═════════════
  loadAbout() {
    this.http.get<any>(API + '/about').subscribe({
      next: r => { this.about = r; this.aboutBlocks = this.parseAbout(r.about_body || ''); },
      error: () => {},
    });
  }
  private parseAbout(body: string): AboutBlock[] {
    return body.split(/\n\s*\n/).map(b => b.trim()).filter(Boolean).map(block => {
      const lines = block.split('\n').map(l => l.trim()).filter(Boolean);
      const isItem = (l: string) => /^(•|-|\*|\d+[.)])\s/.test(l);
      const head = lines[0];
      if (lines.length > 1 && !isItem(head) && head.length <= 48) {
        const rest = lines.slice(1);
        const items = rest.filter(isItem);
        if (items.length === rest.length) {
          return { title: head, items: items.map(l => l.replace(/^(•|-|\*|\d+[.)])\s/, '')), ordered: /^\d/.test(rest[0]) };
        }
        return { title: head, text: rest.join(' ') };
      }
      return { text: lines.join(' ') };
    });
  }
  startEditAbout() { this.aboutEdit = { ...this.about }; this.editingAbout = true; }
  saveAbout() {
    this.aboutSaving = true;
    this.call<any>('PUT', '/about', this.aboutEdit).subscribe({
      next: r => {
        this.about = r; this.aboutBlocks = this.parseAbout(r.about_body || '');
        this.editingAbout = false; this.aboutSaving = false; this.flash('About page saved');
      },
      error: e => { this.aboutSaving = false; this.flash(this.errText(e, 'Save failed'), false); },
    });
  }
  sendSuggestion() {
    this.sgError = '';
    if (this.sgTitle.trim().length < 3) { this.sgError = 'Give your idea a short title.'; return; }
    if (this.sgMsg.trim().length < 10) { this.sgError = 'Add a little more detail (10+ characters).'; return; }
    this.sgSending = true;
    this.call('POST', '/suggestions', { title: this.sgTitle, message: this.sgMsg, category: this.sgCategory }).subscribe({
      next: () => { this.sgSending = false; this.sgSent = true; this.sgTitle = ''; this.sgMsg = ''; },
      error: e => { this.sgSending = false; this.sgError = this.errText(e, 'Could not send. Please try again.'); },
    });
  }
  newSuggestion() { this.sgSent = false; this.sgError = ''; }

  // ═════════════ admin ═════════════
  loadAdmin(spinner = true) {
    if (!this.isAdmin) return;
    if (spinner) this.adminLoading = true;
    this.call<any>('GET', '/admin/stats').subscribe({ next: s => this.adminStats = s, error: () => {} });
    this.call<any>('GET', '/admin/users').subscribe({
      next: r => { this.adminUsers = r.users || []; this.adminLoading = false; },
      error: e => { this.adminLoading = false; if (spinner) this.flash(this.errText(e, 'Could not load users'), false); },
    });
    this.call<any>('GET', '/admin/suggestions').subscribe({ next: r => this.adminSugg = r.suggestions || [], error: () => {} });
  }
  get shownUsers(): any[] {
    const q = this.userSearch.trim().toLowerCase();
    return this.adminUsers.filter(u => !q || u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q));
  }
  get shownSugg(): any[] {
    return this.adminSugg.filter(s => this.suggFilter === 'all' || s.status === this.suggFilter);
  }
  get newSuggCount(): number { return this.adminSugg.filter(s => s.status === 'new').length; }
  toggleRole(u: any) {
    const to = !u.is_admin;
    if (!confirm(`${to ? 'Make' : 'Remove'} ${u.name} ${to ? 'an admin' : 'as admin'}?`)) return;
    this.call('PATCH', `/admin/users/${u.id}`, { is_admin: to }).subscribe({
      next: () => { this.flash('Role updated'); this.loadAdmin(false); },
      error: e => this.flash(this.errText(e), false),
    });
  }
  deleteUser(u: any) {
    if (!confirm(`Delete ${u.name} (${u.email}) and all their transactions? This cannot be undone.`)) return;
    this.call('DELETE', `/admin/users/${u.id}`).subscribe({
      next: () => { this.flash(`${u.name} deleted`); this.loadAdmin(false); },
      error: e => this.flash(this.errText(e), false),
    });
  }
  setSuggStatus(s: any) {
    this.call('PATCH', `/admin/suggestions/${s.id}`, { status: s.status }).subscribe({
      next: () => this.loadAdmin(false), error: e => this.flash(this.errText(e), false),
    });
  }
  deleteSugg(s: any) {
    if (!confirm('Delete this suggestion?')) return;
    this.call('DELETE', `/admin/suggestions/${s.id}`).subscribe({ next: () => this.loadAdmin(false), error: () => {} });
  }
  catIcon(id: string): string { return this.sgCategories.find(c => c.id === id)?.icon || '💬'; }
}
