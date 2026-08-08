import { Component, OnInit, ViewChild, ElementRef, HostListener, ViewEncapsulation } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { NgxChartsModule, LegendPosition } from '@swimlane/ngx-charts';

interface Message { role:'user'|'assistant'; text:string; sources?:string[]; loading?:boolean; }
interface User { id:number; email:string; name:string; }

@Component({
  selector: 'app-root',
  standalone: true,
  encapsulation: ViewEncapsulation.None,
  imports: [CommonModule, FormsModule, NgxChartsModule],
  template: `

<!-- AUTH SCREEN -->
<div class="auth-screen" *ngIf="!currentUser">
  <div class="auth-box">
    <div class="auth-logo">₹</div>
    <div class="auth-title">UPI Analyzer</div>
    <div class="auth-sub">Track your spending across months</div>

    <div class="auth-tabs">
      <button [class.on]="authMode==='login'"    (click)="authMode='login'">Sign in</button>
      <button [class.on]="authMode==='register'" (click)="authMode='register'">Create account</button>
    </div>

    <div class="auth-form">
      <input *ngIf="authMode==='register'" class="auth-in" [(ngModel)]="authName" placeholder="Full name">
      <input class="auth-in" [(ngModel)]="authEmail" placeholder="Email" type="email">
      <input class="auth-in" [(ngModel)]="authPassword" placeholder="Password" type="password" (keydown.enter)="submitAuth()">
      <div class="auth-err" *ngIf="authError">{{ authError }}</div>
      <button class="auth-btn" (click)="submitAuth()" [disabled]="authLoading">
        {{ authLoading ? 'Please wait…' : (authMode==='login' ? 'Sign in' : 'Create account') }}
      </button>
    </div>
  </div>
</div>

<!-- APP -->
<div class="shell" *ngIf="currentUser">

  <aside class="sidebar" [class.open]="sidebarOpen">
    <div class="sb-brand">
      <div class="sb-logo">₹</div>
      <div>
        <div class="sb-name">UPI Analyzer</div>
        <div class="sb-user">{{ currentUser.name }}</div>
      </div>
    </div>

    <nav class="sb-nav">
      <button class="sb-lnk" [class.on]="tab==='overview'"     (click)="go('overview')">
        <svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
        Overview
      </button>
      <button class="sb-lnk" [class.on]="tab==='analytics'"    (click)="go('analytics')" [disabled]="!analytics">
        <svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
        Analytics
      </button>
      <button class="sb-lnk" [class.on]="tab==='transactions'" (click)="go('transactions')" [disabled]="!totalStored">
        <svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
        Transactions
        <span class="sb-pill" *ngIf="totalStored">{{ totalStored }}</span>
      </button>
      <button class="sb-lnk" [class.on]="tab==='ai'"           (click)="go('ai')">
        <svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="2"/><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
        AI Chat
        <span class="sb-online" *ngIf="ollamaOk"></span>
      </button>
    </nav>

    <div class="sb-gap"></div>

    <div class="sb-filter" *ngIf="totalStored">
      <div class="sb-filter-lbl">Date range</div>
      <div class="sb-dates">
        <input type="date" class="din" [(ngModel)]="filterFrom" (change)="onDateFilter()">
        <span class="din-sep">→</span>
        <input type="date" class="din" [(ngModel)]="filterTo"   (change)="onDateFilter()">
      </div>
      <div class="date-actions">
        <button class="sb-reset" (click)="clearAllDates()">All time</button>
        <button class="sb-reset" (click)="setThisMonth()">This month</button>
      </div>
      <div class="sb-range-info" *ngIf="filterFrom||filterTo">{{ analytics?.transaction_count||0 }} of {{ totalStored }} transactions</div>
    </div>

    <div class="sb-foot">
      <label class="sb-import-btn">
        <input type="file" accept=".csv,.xlsx,.pdf" (change)="onFile($event, autoType($event))">
        <svg width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
        {{ uploading ? 'Importing…' : 'Import CSV / PDF' }}
      </label>
      <button class="sb-clear-btn" *ngIf="totalStored" (click)="confirmClear()">Clear all data</button>
      <button class="sb-logout" (click)="logout()">Sign out</button>
    </div>
  </aside>

  <div class="overlay" *ngIf="sidebarOpen" (click)="sidebarOpen=false"></div>

  <div class="main">
    <header class="bar">
      <button class="burger" (click)="sidebarOpen=!sidebarOpen">
        <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
      </button>
      <div class="bar-title">{{ tabLabel() }}</div>
      <div class="bar-right">
        <div class="toast" [class.tok]="toast.ok" [class.terr]="!toast.ok" *ngIf="toast.msg">{{ toast.msg }}</div>
      </div>
    </header>

    <!-- OVERVIEW -->
    <main class="page" *ngIf="tab==='overview'">
      <div class="empty" *ngIf="!totalStored">
        <div class="empty-box">
          <div class="empty-ico"><svg width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg></div>
          <h2>Import your first statement</h2>
          <p>Upload SuperMoney CSV exports. Multiple uploads are merged — get combined analytics across months.</p>
          <div class="empty-acts">
            <label class="btn-w"><input type="file" accept=".csv,.xlsx" (change)="onFile($event,'csv')">Import CSV</label>
            <button class="btn-o" (click)="downloadSample()">Sample CSV</button>
          </div>
        </div>
      </div>

      <div *ngIf="totalStored && analytics" class="dash">
        <div class="kpis">
          <div class="kpi"><div class="kn">₹{{ analytics.total_spent | number:'1.0-0' }}</div><div class="kl">Total spent</div><div class="ks">₹{{ analytics.avg_per_day | number:'1.0-0' }}/day</div></div>
          <div class="kpi"><div class="kn g">₹{{ analytics.total_received | number:'1.0-0' }}</div><div class="kl">Received</div></div>
          <div class="kpi"><div class="kn" [class.g]="analytics.net_flow>=0" [class.r]="analytics.net_flow<0">{{ analytics.net_flow>=0?'+':'' }}₹{{ analytics.net_flow | number:'1.0-0' }}</div><div class="kl">Net flow</div></div>
          <div class="kpi"><div class="kn">{{ analytics.transaction_count }}</div><div class="kl">Payments</div><div class="ks">₹{{ analytics.average_transaction | number:'1.0-0' }} avg</div></div>
          <div class="kpi"><div class="kn">{{ analytics.days_active }}</div><div class="kl">Days tracked</div></div>
        </div>

        <div class="grid">
          <!-- Pie -->
          <div class="card" *ngIf="pieData.length">
            <div class="ch">Spending by category</div>
            <div class="pie-wrap">
              <ngx-charts-pie-chart [results]="pieData" [legend]="false" [labels]="false"
                [doughnut]="true" [arcWidth]="0.38" [tooltipDisabled]="false"
                [view]="[220,220]" [scheme]="scheme">
              </ngx-charts-pie-chart>
              <div class="pie-legend">
                <div class="pl-row" *ngFor="let c of pieData">
                  <span class="pl-dot" [style.background]="c.color||''"></span>
                  <span class="pl-name">{{ c.name }}</span>
                  <span class="pl-val">{{ pct(c.value, analytics.total_spent) | number:'1.0-0' }}%</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Monthly bar -->
          <div class="card" *ngIf="monthlyData.length">
            <div class="ch">Monthly spending</div>
            <ngx-charts-bar-vertical [results]="monthlyData" [xAxis]="true" [yAxis]="true"
              [showDataLabel]="true" [tooltipDisabled]="false"
              [view]="[cardW, 240]" [scheme]="scheme">
            </ngx-charts-bar-vertical>
          </div>

          <!-- Top merchants -->
          <div class="card wide" *ngIf="merchantData.length">
            <div class="ch">Top merchants</div>
            <ngx-charts-bar-horizontal [results]="merchantData" [xAxis]="true" [yAxis]="true"
              [showDataLabel]="true" [tooltipDisabled]="false"
              [view]="[wideW, 280]" [scheme]="scheme">
            </ngx-charts-bar-horizontal>
          </div>

          <!-- Largest payments -->
          <div class="card" *ngIf="analytics.largest_transactions?.length">
            <div class="ch">Largest payments</div>
            <div class="rows">
              <div class="row-item" *ngFor="let t of analytics.largest_transactions">
                <div class="ri-l"><div class="ri-name">{{ t.merchant }}</div><div class="ri-sub">{{ t.date }} · {{ t.category }}</div></div>
                <div class="ri-val r">₹{{ t.amount | number:'1.0-0' }}</div>
              </div>
            </div>
          </div>

          <!-- Recurring -->
          <div class="card" *ngIf="analytics.recurring_merchants?.length">
            <div class="ch">Recurring <span class="tag">3+ times</span></div>
            <div class="rows">
              <div class="row-item" *ngFor="let r of analytics.recurring_merchants.slice(0,6)">
                <div class="ri-l"><div class="ri-name">{{ r.merchant }}</div><div class="ri-sub">{{ r.count }}× · ₹{{ r.avg | number:'1.0-0' }} avg</div></div>
                <div class="ri-val">₹{{ r.total | number:'1.0-0' }}</div>
              </div>
            </div>
          </div>

          <!-- Weekday -->
          <div class="card" *ngIf="dowData.length">
            <div class="ch">Spending by weekday</div>
            <ngx-charts-bar-vertical [results]="dowData" [xAxis]="true" [yAxis]="false"
              [showDataLabel]="true" [tooltipDisabled]="false"
              [view]="[cardW, 200]" [scheme]="scheme">
            </ngx-charts-bar-vertical>
          </div>

          <!-- Failed -->
          <div class="card" *ngIf="analytics.failed_transactions?.length">
            <div class="ch">Failed <span class="tag warn">{{ analytics.failed_count }}</span></div>
            <div class="rows">
              <div class="row-item" *ngFor="let f of analytics.failed_transactions">
                <div class="ri-l"><div class="ri-name">{{ f.merchant }}</div><div class="ri-sub">{{ f.date }}</div></div>
                <div class="ri-val dim">₹{{ f.amount | number:'1.0-0' }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>

    <!-- ANALYTICS -->
    <main class="page" *ngIf="tab==='analytics' && analytics">
      <div class="grid">

        <div class="card wide" *ngIf="weeklyData.length && weeklyData[0]?.series?.length > 1">
          <div class="ch">Weekly spending trend</div>
          <ngx-charts-line-chart [results]="weeklyData" [xAxis]="true" [yAxis]="true"
            [showGridLines]="true" [tooltipDisabled]="false"
            [view]="[wideW, 220]" [scheme]="scheme">
          </ngx-charts-line-chart>
        </div>

        <div class="card wide" *ngIf="pieData.length">
          <div class="ch">Category breakdown</div>
          <div class="cat-list">
            <div class="cat-row" *ngFor="let c of pieData">
              <span class="cat-dot" [style.background]="c.color"></span>
              <span class="cat-name">{{ c.name }}</span>
              <div class="cat-bar-wrap"><div class="cat-bar" [style.width.%]="pct(c.value,analytics.total_spent)" [style.background]="c.color"></div></div>
              <span class="cat-pct">{{ pct(c.value,analytics.total_spent) | number:'1.0-0' }}%</span>
              <span class="cat-amt">₹{{ c.value | number:'1.0-0' }}</span>
            </div>
          </div>
        </div>

        <div class="card" *ngIf="dowData.length">
          <div class="ch">Day of week</div>
          <ngx-charts-bar-vertical [results]="dowData" [xAxis]="true" [yAxis]="true"
            [showDataLabel]="true" [view]="[cardW, 220]" [scheme]="scheme">
          </ngx-charts-bar-vertical>
        </div>

        <div class="card" *ngIf="analytics.recurring_merchants?.length">
          <div class="ch">All recurring payments</div>
          <div class="rows">
            <div class="row-item" *ngFor="let r of analytics.recurring_merchants">
              <div class="ri-l"><div class="ri-name">{{ r.merchant }}</div><div class="ri-sub">{{ r.count }}× · ₹{{ r.avg|number:'1.0-0' }} avg</div></div>
              <div class="ri-val">₹{{ r.total|number:'1.0-0' }}</div>
            </div>
          </div>
        </div>

        <div class="card wide" *ngIf="merchantData.length">
          <div class="ch">Merchant comparison</div>
          <ngx-charts-bar-horizontal [results]="merchantData" [xAxis]="true" [yAxis]="true"
            [showDataLabel]="true" [view]="[wideW, 300]" [scheme]="scheme">
          </ngx-charts-bar-horizontal>
        </div>

      </div>
    </main>

    <!-- TRANSACTIONS -->
    <main class="page" *ngIf="tab==='transactions'">
      <div class="txn-bar">
        <span class="txn-ct">{{ filteredTxns.length }} transactions</span>
        <div class="txn-tools">
          <select class="ctl" [(ngModel)]="fType" (change)="applyFilter()">
            <option value="">All types</option><option value="sent">Sent</option><option value="received">Received</option>
          </select>
          <select class="ctl" [(ngModel)]="fCat" (change)="applyFilter()">
            <option value="">All categories</option>
            <option *ngFor="let c of allCats" [value]="c">{{ c }}</option>
          </select>
          <input class="ctl ctl-search" [(ngModel)]="fSearch" (input)="applyFilter()" placeholder="Search…">
        </div>
      </div>
      <div class="tbl-box">
        <table class="tbl">
          <thead><tr>
            <th>Merchant</th><th>Amount</th><th>Type</th><th>Date</th>
            <th>Category</th><th>Status</th><th title="Include in analytics">⬤</th>
          </tr></thead>
          <tbody>
            <tr *ngFor="let t of filteredTxns.slice(0,showN)" [class.excluded-row]="!t.included">
              <td class="td-m" [class.dim]="!t.included">{{ t.merchant }}</td>
              <td class="td-a" [class.r]="t.transaction_type==='sent'" [class.g]="t.transaction_type==='received'" [class.dim]="!t.included">
                {{ t.transaction_type==='sent'?'-':'+' }}₹{{ t.amount | number:'1.0-0' }}
              </td>
              <td><span class="pill" [class.ps]="t.transaction_type==='sent'" [class.pr]="t.transaction_type==='received'">{{ t.transaction_type }}</span></td>
              <td class="td-d" [class.dim]="!t.included">{{ t.date | date:'d MMM yy' }}</td>
              <td class="td-cat">
                <div *ngIf="editingCat !== t.id" class="cat-cell" (click)="startEditCat(t)">
                  <span class="cat-lbl" [class.custom-cat]="t.custom_category">{{ t.category }}</span>
                  <span class="cat-edit-ico">✎</span>
                </div>
                <div *ngIf="editingCat === t.id" class="cat-edit-wrap">
                  <select class="cat-sel" [(ngModel)]="editingCatVal" (change)="onCatChange(t)">
                    <option *ngFor="let c of allSystemCats" [value]="c">{{ c }}</option>
                    <option value="__custom__">+ Custom…</option>
                  </select>
                  <input *ngIf="editingCatVal==='__custom__'" class="cat-custom-in"
                    [(ngModel)]="customCatInput" placeholder="Custom category"
                    (keydown.enter)="saveCat(t)" (keydown.escape)="editingCat=null">
                  <button class="cat-save" (click)="saveCat(t)">✓</button>
                  <button class="cat-cancel" (click)="editingCat=null">✕</button>
                </div>
              </td>
              <td class="td-st" [class.g]="t.note==='SUCCESS'" [class.r]="t.note==='FAILED'" [class.dim]="!t.included">{{ t.note }}</td>
              <td class="td-toggle">
                <button class="toggle-btn" [class.on]="t.included" [class.off]="!t.included"
                  (click)="toggleIncluded(t)" [title]="t.included ? 'Included — click to exclude' : 'Excluded — click to include'">
                  {{ t.included ? '●' : '○' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <div class="load-more" *ngIf="filteredTxns.length>showN" (click)="showN=showN+100">
          Load {{ [filteredTxns.length-showN,100].sort()[0] }} more · {{ filteredTxns.length-showN }} remaining
        </div>
      </div>
    </main>

    <!-- AI -->
    <div class="ai-wrap" *ngIf="tab==='ai'">
      <div class="ai-side">
        <div class="as-sec">
          <div class="as-lbl">Ollama</div>
          <div class="as-status" [class.on]="ollamaOk" [class.off]="!ollamaOk">
            <span class="as-dot"></span>{{ ollamaOk ? (status?.active_model||'Online') : 'Offline' }}
          </div>
          <code class="as-cmd" *ngIf="!ollamaOk">ollama serve</code>
          <div class="as-idx" *ngIf="indexedCount">{{ indexedCount }} docs indexed</div>
          <button class="as-btn" (click)="reIndex()" [disabled]="indexing||!totalStored">{{ indexing?'Indexing…':'Re-index' }}</button>
        </div>
        <div class="as-div"></div>
        <div class="as-sec">
          <div class="as-lbl">Suggestions</div>
          <button class="as-q" *ngFor="let q of suggestions" (click)="ask(q)">{{ q }}</button>
        </div>
      </div>
      <div class="ai-chat">
        <div class="chat-msgs" #chatWin>
          <div class="chat-empty" *ngIf="!messages.length">
            <div class="ce-t">AI Transaction Analyst</div>
            <div class="ce-s">Import transactions then ask anything.</div>
          </div>
          <div *ngFor="let m of messages" class="msg-row" [class.user]="m.role==='user'">
            <div class="bub" [class.bu]="m.role==='user'" [class.bb]="m.role==='assistant'">
              <span *ngIf="m.loading" class="ld"><i></i><i></i><i></i></span>
              <span *ngIf="!m.loading" style="white-space:pre-wrap">{{ m.text }}</span>
              <div *ngIf="m.sources?.length" class="src">
                <details><summary>{{ m.sources!.length }} sources</summary>
                  <ul><li *ngFor="let s of m.sources">{{ s }}</li></ul>
                </details>
              </div>
            </div>
          </div>
        </div>
        <div class="chat-bar">
          <input class="chat-in" [(ngModel)]="question" (keydown.enter)="send()" [disabled]="chatLoading" placeholder="Ask about your spending…">
          <button class="chat-send" (click)="send()" [disabled]="chatLoading||!question.trim()">
            <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
          </button>
        </div>
      </div>
    </div>
  </div>
</div>
  `,
  styles: [`
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
    :host{display:block}
    input[type=file]{display:none}

    /* ── TOKENS ── */
    :root{
      --bg: #0d0d0d;
      --surface: #141414;
      --border: #202020;
      --border2: #2a2a2a;
      --text: #d4d4d4;
      --text2: #888;
      --text3: #444;
      --green: #4ade80;
      --red: #f87171;
      --blue: #60a5fa;
      --accent: #f0f0f0;
    }

    /* ── AUTH ── */
    .auth-screen{display:flex;align-items:center;justify-content:center;min-height:100vh;background:var(--bg)}
    .auth-box{width:360px;background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:36px 32px}
    .auth-logo{width:44px;height:44px;background:#fff;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:20px;font-weight:800;color:#0d0d0d;margin-bottom:16px}
    .auth-title{font-size:20px;font-weight:700;color:#f0f0f0;letter-spacing:-.4px;margin-bottom:4px}
    .auth-sub{font-size:13px;color:var(--text3);margin-bottom:24px}
    .auth-tabs{display:flex;gap:2px;background:#0d0d0d;border-radius:8px;padding:3px;margin-bottom:20px}
    .auth-tabs button{flex:1;padding:7px;border:none;background:none;color:var(--text2);border-radius:6px;cursor:pointer;font-size:13px;font-weight:500;transition:all .15s}
    .auth-tabs button.on{background:var(--surface);color:#f0f0f0;box-shadow:0 1px 4px rgba(0,0,0,.4)}
    .auth-form{display:flex;flex-direction:column;gap:10px}
    .auth-in{background:#0d0d0d;border:1px solid var(--border);color:#f0f0f0;border-radius:8px;padding:11px 14px;font-size:14px;outline:none;transition:border-color .15s}
    .auth-in:focus{border-color:var(--border2)}
    .auth-err{font-size:12px;color:var(--red);padding:4px 2px}
    .auth-btn{background:#f0f0f0;color:#0d0d0d;border:none;border-radius:8px;padding:12px;font-size:14px;font-weight:600;cursor:pointer;transition:background .15s;margin-top:4px}
    .auth-btn:hover:not(:disabled){background:#ddd}
    .auth-btn:disabled{opacity:.5;cursor:default}

    /* ── APP SHELL ── */
    .shell{display:flex;height:100vh;overflow:hidden;background:var(--bg);color:var(--text);font-family:-apple-system,'Inter','Segoe UI',sans-serif;font-size:13px}

    /* ── SIDEBAR ── */
    .sidebar{width:240px;min-width:240px;flex-shrink:0;background:#0a0a0a;border-right:1px solid var(--border);display:flex;flex-direction:column;height:100vh;overflow-y:auto;transition:transform .2s;position:relative}
    .sb-brand{display:flex;align-items:center;gap:10px;padding:18px 16px 14px;border-bottom:1px solid var(--border)}
    .sb-logo{width:32px;height:32px;background:#fff;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:800;color:#0a0a0a;flex-shrink:0}
    .sb-name{font-size:13px;font-weight:600;color:#f0f0f0;letter-spacing:-.2px}
    .sb-user{font-size:11px;color:var(--text3);margin-top:1px}
    .sb-nav{padding:10px 8px;display:flex;flex-direction:column;gap:2px}
    .sb-lnk{display:flex;align-items:center;gap:9px;padding:9px 10px;border-radius:8px;border:none;background:none;color:var(--text3);cursor:pointer;font-size:13px;font-weight:500;text-align:left;width:100%;transition:all .15s;position:relative}
    .sb-lnk:hover:not(:disabled){background:#131313;color:var(--text)}
    .sb-lnk.on{background:#181818;color:#f0f0f0}
    .sb-lnk:disabled{opacity:.2;cursor:default}
    .sb-pill{margin-left:auto;font-size:10px;background:#1a1a1a;color:var(--text3);padding:1px 7px;border-radius:10px}
    .sb-online{width:6px;height:6px;border-radius:50%;background:var(--green);margin-left:auto;animation:pg 2s infinite}
    @keyframes pg{0%,100%{box-shadow:0 0 0 0 rgba(74,222,128,.4)}50%{box-shadow:0 0 0 4px rgba(74,222,128,0)}}
    .sb-gap{flex:1;min-height:8px}

    .sb-filter{padding:12px 14px 8px;border-top:1px solid var(--border);flex-shrink:0}
    .sb-filter-lbl{font-size:10px;font-weight:600;color:var(--text3);text-transform:uppercase;letter-spacing:.7px;margin-bottom:8px}
    .sb-dates{display:flex;align-items:center;gap:6px;margin-bottom:6px}
    .din{background:#111;border:1px solid var(--border);color:var(--text2);border-radius:6px;padding:6px 7px;font-size:11px;width:100%;outline:none;color-scheme:dark}
    .din:focus{border-color:var(--border2);color:#e0e0e0}
    .din-sep{color:var(--text3);font-size:11px;flex-shrink:0}
    .date-actions{display:flex;gap:6px;margin-bottom:4px}
    .sb-reset{background:#141414;border:1px solid var(--border);color:var(--text2);font-size:11px;cursor:pointer;padding:4px 8px;border-radius:5px;transition:all .15s}
    .sb-reset:hover{border-color:var(--border2);color:#e0e0e0}
    .sb-reset:hover{color:var(--text2)}
    .sb-range-info{font-size:11px;color:var(--text3);margin-top:4px;margin-bottom:4px}

    .sb-foot{padding:12px;border-top:1px solid var(--border);display:flex;flex-direction:column;gap:6px;flex-shrink:0}
    .sb-import-btn{display:flex;align-items:center;gap:8px;padding:9px 12px;background:#151515;border:1px solid var(--border);border-radius:8px;color:var(--text2);cursor:pointer;font-size:12px;font-weight:500;transition:all .15s}
    .sb-import-btn:hover{border-color:var(--border2);color:#e0e0e0;background:#181818}
    .sb-clear-btn{background:none;border:1px solid var(--border);color:var(--text3);border-radius:6px;padding:7px;font-size:11px;cursor:pointer;transition:all .15s}
    .sb-clear-btn:hover{border-color:#3a1515;color:var(--red);background:#1a0a0a}
    .sb-logout{background:none;border:none;color:var(--text3);font-size:11px;cursor:pointer;padding:4px 0;text-align:left;transition:color .15s}
    .sb-logout:hover{color:var(--text2)}

    .overlay{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:40;display:none}

    /* ── MAIN ── */
    .main{flex:1;display:flex;flex-direction:column;min-width:0;overflow:hidden}
    .bar{height:50px;border-bottom:1px solid var(--border);display:flex;align-items:center;padding:0 20px;gap:12px;flex-shrink:0;background:#0a0a0a}
    .burger{display:none;background:none;border:none;color:var(--text3);cursor:pointer;padding:5px;border-radius:6px}
    .burger:hover{background:#181818;color:var(--text)}
    .bar-title{font-size:15px;font-weight:600;color:#f0f0f0;letter-spacing:-.2px}
    .bar-right{margin-left:auto}
    .toast{font-size:12px;padding:6px 12px;border-radius:7px}
    .toast.tok{background:#0a1f11;color:var(--green);border:1px solid #1a3a22}
    .toast.terr{background:#1f0a0a;color:var(--red);border:1px solid #3a1a1a}

    .page{flex:1;overflow-y:auto;padding:24px}

    /* ── EMPTY ── */
    .empty{display:flex;align-items:center;justify-content:center;height:100%}
    .empty-box{text-align:center;max-width:420px}
    .empty-ico{width:60px;height:60px;background:#151515;border:1px solid var(--border);border-radius:16px;display:flex;align-items:center;justify-content:center;margin:0 auto 20px;color:#2a2a2a}
    .empty-box h2{font-size:20px;font-weight:600;color:#e8e8e8;margin-bottom:8px;letter-spacing:-.3px}
    .empty-box p{color:#3a3a3a;line-height:1.7;margin-bottom:24px}
    .empty-acts{display:flex;gap:10px;justify-content:center}
    .btn-w{padding:10px 22px;background:var(--accent);color:#0a0a0a;border:none;border-radius:8px;cursor:pointer;font-size:13px;font-weight:600}
    .btn-w:hover{background:#ddd}
    .btn-o{padding:10px 22px;background:none;color:var(--text2);border:1px solid var(--border);border-radius:8px;cursor:pointer;font-size:13px}
    .btn-o:hover{border-color:var(--border2);color:var(--text)}

    /* ── KPIS ── */
    .dash{display:flex;flex-direction:column;gap:20px}
    .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:1px;background:var(--border);border:1px solid var(--border);border-radius:12px;overflow:hidden}
    .kpi{background:var(--bg);padding:18px 20px}
    .kn{font-size:22px;font-weight:700;color:#f0f0f0;letter-spacing:-.5px;font-variant-numeric:tabular-nums;line-height:1}
    .kn.g{color:var(--green)} .kn.r{color:var(--red)}
    .kl{font-size:10px;color:var(--text3);text-transform:uppercase;letter-spacing:.6px;margin-top:5px;font-weight:600}
    .ks{font-size:11px;color:var(--text3);margin-top:3px}

    /* ── GRID ── */
    .grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
    .card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;overflow:hidden}
    .card.wide{grid-column:1/-1}
    .ch{font-size:11px;font-weight:600;color:var(--text2);text-transform:uppercase;letter-spacing:.6px;margin-bottom:16px;display:flex;align-items:center;gap:8px}
    .tag{font-size:10px;font-weight:500;padding:2px 7px;border-radius:5px;background:#1a1a1a;color:var(--text3);text-transform:none;letter-spacing:0}
    .tag.warn{background:#1f1208;color:#fb923c}

    /* ── PIE + LEGEND ── */
    .pie-wrap{display:flex;align-items:center;gap:20px}
    .pie-legend{display:flex;flex-direction:column;gap:8px;flex:1}
    .pl-row{display:flex;align-items:center;gap:8px}
    .pl-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
    .pl-name{font-size:12px;color:var(--text2);flex:1}
    .pl-val{font-size:12px;font-weight:600;color:var(--text);font-variant-numeric:tabular-nums}

    /* ── ROWS ── */
    .rows{display:flex;flex-direction:column;gap:12px}
    .row-item{display:flex;align-items:center;gap:12px}
    .ri-l{flex:1;min-width:0}
    .ri-name{font-size:13px;color:#ccc;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .ri-sub{font-size:11px;color:var(--text3);margin-top:2px}
    .ri-val{font-size:13px;font-weight:600;font-variant-numeric:tabular-nums;flex-shrink:0;color:var(--text2)}
    .ri-val.r{color:var(--red)} .ri-val.g{color:var(--green)} .ri-val.dim{color:var(--text3)}

    /* ── CAT LIST ── */
    .cat-list{display:flex;flex-direction:column;gap:10px}
    .cat-row{display:flex;align-items:center;gap:10px}
    .cat-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
    .cat-name{font-size:12px;color:var(--text2);width:120px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex-shrink:0}
    .cat-bar-wrap{flex:1;height:4px;background:#1a1a1a;border-radius:2px;overflow:hidden}
    .cat-bar{height:100%;border-radius:2px;transition:width .4s}
    .cat-pct{font-size:11px;color:var(--text3);width:32px;text-align:right;flex-shrink:0}
    .cat-amt{font-size:12px;color:var(--text2);width:76px;text-align:right;font-variant-numeric:tabular-nums;flex-shrink:0}

    /* ── CHART OVERRIDES (visibility) ── */
    .ngx-charts text{fill:#888!important;font-size:11px!important;font-family:-apple-system,'Inter','Segoe UI',sans-serif!important}
    .ngx-charts .gridline-path,.ngx-charts .refline-path{stroke:#1e1e1e!important}
    .ngx-charts .tick line{stroke:#1e1e1e!important}
    .ngx-charts .data-label{fill:#c0c0c0!important;font-size:11px!important;font-weight:500!important}
    .ngx-charts .pie-label{fill:#bbb!important;font-size:11px!important}
    .ngx-charts .pie-label-line{stroke:#333!important}
    .ngx-charts .x.axis .tick text,.ngx-charts .y.axis .tick text{fill:#666!important;font-size:11px!important}
    .ngx-charts .axis-label{fill:#555!important}
    .ngx-charts .tooltip-anchor{fill:#fff!important}
    .ngx-charts .bar:hover,.ngx-charts .cell:hover{opacity:.85}
    .chart-legend .legend-label-text{color:#888!important;font-size:11px!important}
    .chart-legend .legend-title-text{color:#555!important;font-size:11px!important}

    /* ── TXNS ── */
    .txn-bar{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;flex-wrap:wrap;gap:10px}
    .txn-ct{font-size:11px;font-weight:600;color:var(--text3);text-transform:uppercase;letter-spacing:.6px}
    .txn-tools{display:flex;gap:8px;flex-wrap:wrap}
    .ctl{background:var(--surface);border:1px solid var(--border);color:var(--text2);border-radius:7px;padding:7px 10px;font-size:12px;outline:none;transition:all .15s}
    .ctl:focus,.ctl:hover{border-color:var(--border2);color:var(--text)}
    .ctl-search{min-width:170px}
    .tbl-box{background:var(--surface);border:1px solid var(--border);border-radius:12px;overflow:hidden}
    .tbl{width:100%;border-collapse:collapse}
    .tbl th{text-align:left;padding:10px 14px;font-size:10px;font-weight:600;color:var(--text3);text-transform:uppercase;letter-spacing:.6px;border-bottom:1px solid #161616}
    .tbl td{padding:10px 14px;border-bottom:1px solid #111;vertical-align:middle}
    .tbl tr:last-child td{border-bottom:none}
    .tbl tr:hover td{background:#111}
    .td-m{color:#ccc;max-width:220px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .td-a{font-weight:600;font-variant-numeric:tabular-nums}
    .td-a.r{color:var(--red)} .td-a.g{color:var(--green)}
    .td-d,.td-c{color:var(--text3);font-size:11px}
    .td-st{font-size:11px} .td-st.g{color:var(--green)} .td-st.r{color:var(--red)}
    .pill{padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600}
    .ps{background:#1f0e0e;color:var(--red)} .pr{background:#0e1f0e;color:var(--green)}
    .load-more{text-align:center;padding:14px;color:var(--text3);cursor:pointer;font-size:12px;border-top:1px solid #131313}
    .load-more:hover{color:var(--text2)}

    /* ── AI ── */
    .ai-wrap{display:flex;flex:1;overflow:hidden}
    .ai-side{width:210px;flex-shrink:0;border-right:1px solid var(--border);padding:16px 14px;overflow-y:auto;background:#0a0a0a;display:flex;flex-direction:column;gap:0}
    .as-sec{padding:10px 0;display:flex;flex-direction:column;gap:6px}
    .as-div{height:1px;background:var(--border)}
    .as-lbl{font-size:10px;font-weight:600;color:var(--text3);text-transform:uppercase;letter-spacing:.7px;margin-bottom:2px}
    .as-status{display:flex;align-items:center;gap:6px;font-size:11px;padding:7px 9px;border-radius:7px}
    .as-status.on{background:#0a1a0f;color:var(--green);border:1px solid #0f2a18}
    .as-status.off{background:#1a0a0a;color:var(--red);border:1px solid #2a0f0f}
    .as-dot{width:6px;height:6px;border-radius:50%;background:currentColor;flex-shrink:0}
    .as-cmd{display:block;font-size:11px;color:#444;padding:5px 8px;background:#111;border-radius:5px;font-family:monospace}
    .as-idx{font-size:10px;color:var(--green);opacity:.6}
    .as-btn{background:#141414;border:1px solid var(--border);color:var(--text3);border-radius:6px;padding:8px;font-size:11px;cursor:pointer;transition:all .15s}
    .as-btn:hover:not(:disabled){background:#1a1a1a;color:var(--text2)}
    .as-btn:disabled{opacity:.3;cursor:default}
    .as-q{background:none;border:none;color:var(--text3);font-size:11px;text-align:left;padding:5px 0;cursor:pointer;line-height:1.6;transition:color .15s}
    .as-q:hover{color:var(--text2)}
    .ai-chat{flex:1;display:flex;flex-direction:column;min-width:0}
    .chat-msgs{flex:1;overflow-y:auto;padding:24px;display:flex;flex-direction:column;gap:16px}
    .chat-empty{margin:auto;text-align:center}
    .ce-t{font-size:16px;font-weight:500;color:var(--text3);margin-bottom:6px}
    .ce-s{font-size:12px;color:#222}
    .msg-row{display:flex}
    .msg-row.user{justify-content:flex-end}
    .bub{max-width:75%;padding:11px 15px;border-radius:12px;font-size:13px;line-height:1.65}
    .bu{background:#181818;color:#e8e8e8;border:1px solid #222;border-bottom-right-radius:3px}
    .bb{background:#111;border:1px solid var(--border);color:#aaa;border-bottom-left-radius:3px}
    .ld{display:flex;gap:4px;align-items:center;height:18px}
    .ld i{display:block;width:5px;height:5px;background:#2a2a2a;border-radius:50%;animation:blink 1.2s infinite;font-style:normal}
    .ld i:nth-child(2){animation-delay:.2s} .ld i:nth-child(3){animation-delay:.4s}
    @keyframes blink{0%,80%,100%{opacity:.15}40%{opacity:1}}
    .src{margin-top:8px;font-size:10px}
    .src details summary{cursor:pointer;color:var(--text3)}
    .src ul{margin:4px 0 0 10px;color:var(--text3);line-height:1.7}
    .chat-bar{border-top:1px solid var(--border);padding:14px 18px;display:flex;gap:8px;flex-shrink:0}
    .chat-in{flex:1;background:#111;border:1px solid var(--border);color:#e8e8e8;border-radius:8px;padding:10px 14px;font-size:13px;outline:none;font-family:inherit;transition:border-color .15s}
    .chat-in:focus{border-color:var(--border2)}
    .chat-send{width:40px;height:40px;background:var(--surface);border:1px solid var(--border);color:var(--text2);border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all .15s}
    .chat-send:not(:disabled):hover{background:#222;color:var(--text);border-color:var(--border2)}
    .chat-send:disabled{opacity:.25;cursor:default}


    .excluded-row td { opacity:.45 }
    .dim { opacity:.4 }
    .td-cat { min-width:130px }
    .cat-cell { display:flex; align-items:center; gap:5px; cursor:pointer; padding:2px 4px; border-radius:4px; transition:background .15s }
    .cat-cell:hover { background:#1a1a1a }
    .cat-lbl { font-size:12px; color:var(--text2) }
    .cat-lbl.custom-cat { color:#a78bfa }
    .cat-edit-ico { font-size:10px; color:var(--text3); opacity:0; transition:opacity .15s }
    .cat-cell:hover .cat-edit-ico { opacity:1 }
    .cat-edit-wrap { display:flex; align-items:center; gap:4px; flex-wrap:wrap }
    .cat-sel { background:#111; border:1px solid var(--border2); color:var(--text); border-radius:5px; padding:4px 6px; font-size:11px; outline:none; max-width:140px }
    .cat-custom-in { background:#111; border:1px solid var(--border2); color:var(--text); border-radius:5px; padding:4px 8px; font-size:11px; outline:none; width:120px }
    .cat-save { background:#0a2a14; border:1px solid #1a5a2a; color:var(--green); border-radius:4px; padding:3px 7px; font-size:11px; cursor:pointer }
    .cat-cancel { background:#1a1a1a; border:1px solid var(--border); color:var(--text3); border-radius:4px; padding:3px 7px; font-size:11px; cursor:pointer }
    .td-toggle { text-align:center; width:40px }
    .toggle-btn { background:none; border:none; cursor:pointer; font-size:16px; padding:2px 6px; border-radius:4px; transition:all .15s; line-height:1 }
    .toggle-btn.on { color:var(--green) }
    .toggle-btn.off { color:var(--text3) }
    .toggle-btn:hover { background:#1a1a1a }
    .txn-excl { font-size:11px; color:var(--text3); font-weight:400 }
    @media(max-width:768px){
      .sidebar{position:fixed;left:-240px;top:0;z-index:50;transition:left .2s}
      .sidebar.open{left:0}
      .overlay{display:block}
      .burger{display:flex}
      .grid{grid-template-columns:1fr}
      .card.wide{grid-column:1}
      .ai-wrap{flex-direction:column}
      .ai-side{width:100%;border-right:none;border-bottom:1px solid var(--border)}
      .pie-wrap{flex-direction:column}
    }
  `]
})
export class AppComponent implements OnInit {
  @ViewChild('chatWin') chatWin!: ElementRef;

  // Auth
  currentUser: User | null = null;
  authMode = 'login';
  authName = ''; authEmail = ''; authPassword = '';
  authError = ''; authLoading = false;

  // App
  tab = 'overview';
  sidebarOpen = false;
  transactions: any[] = [];
  filteredTxns: any[] = [];
  analytics: any = null;
  totalStored = 0;
  dateMin = ''; dateMax = '';
  filterFrom = ''; filterTo = '';
  uploading = false;
  toast = { msg: '', ok: true };
  showN = 100;
  allCats: string[] = [];
  fType = ''; fCat = ''; fSearch = ''; fIncluded = '';
  allSystemCats: string[] = ['Credit Card','Education','Entertainment','Food & Grocery',
    'Healthcare','Other','Shopping','Transfer','Transport','Travel','Utilities'];
  editingCat: number|null = null;
  editingCatVal = '';
  customCatInput = '';

  // AI
  messages: Message[] = [];
  question = '';
  chatLoading = false;
  ollamaOk = false;
  indexedCount = 0;
  indexing = false;
  status: any = null;

  // Charts
  pieData:      any[] = [];
  monthlyData:  any[] = [];
  weeklyData:   any[] = [];
  dowData:      any[] = [];
  merchantData: any[] = [];
  cardW = 420;
  wideW = 860;

  scheme: any = { domain: ['#60a5fa','#f97316','#4ade80','#a78bfa','#fbbf24','#f87171','#22d3ee','#94a3b8','#fb923c','#34d399'] };

  private catColors: Record<string,string> = {
    'Travel':'#60a5fa','Food':'#f97316','Healthcare':'#4ade80','Shopping':'#a78bfa',
    'Transport':'#fbbf24','Credit Card':'#f87171','Utilities':'#22d3ee',
    'Transfer':'#94a3b8','Other':'#555555'
  };

  suggestions = [
    'How much did I spend total?',
    'What are my top expense categories?',
    'Which merchant cost me the most?',
    'Show my largest single payments',
    'How much did I receive vs spend?',
  ];

  private api = window.location.hostname === 'localhost'
    ? 'http://localhost:8000/api'
    : 'upi-analyzer-production-28c7.up.railway.app';

  constructor(private http: HttpClient) {}

  ngOnInit() {
    const saved = localStorage.getItem('upi_token');
    const user  = localStorage.getItem('upi_user');
    if (saved && user) {
      this.currentUser = JSON.parse(user);
      this.init();
    }
    this.onResize();
  }

  @HostListener('window:resize') onResize() {
    const w = window.innerWidth;
    const sidebar = w > 768 ? 240 : 0;
    const padding = 48;
    const avail = w - sidebar - padding;
    this.cardW = Math.max(300, Math.min(Math.floor(avail / 2) - 8, 480));
    this.wideW = Math.max(300, Math.min(avail - 16, 920));
  }

  // ── AUTH ──────────────────────────────────────────────────────────────────
  getHeaders(): HttpHeaders {
    const t = localStorage.getItem('upi_token') || '';
    return new HttpHeaders(t ? { Authorization: `Bearer ${t}` } : {});
  }

  submitAuth() {
    this.authError = ''; this.authLoading = true;
    const url  = this.authMode === 'login' ? `${this.api}/auth/login` : `${this.api}/auth/register`;
    const body = this.authMode === 'login'
      ? { email: this.authEmail, password: this.authPassword }
      : { email: this.authEmail, name: this.authName, password: this.authPassword };

    this.http.post<any>(url, body).subscribe({
      next: (res) => {
        localStorage.setItem('upi_token', res.token);
        localStorage.setItem('upi_user', JSON.stringify(res.user));
        this.currentUser = res.user;
        this.authLoading = false;
        this.init();
      },
      error: (err) => {
        this.authError = err.error?.detail || 'Something went wrong';
        this.authLoading = false;
      }
    });
  }

  logout() {
    localStorage.removeItem('upi_token');
    localStorage.removeItem('upi_user');
    this.currentUser = null;
    this.analytics = null;
    this.totalStored = 0;
    this.transactions = [];
  }

  init() {
    this.checkOllama();
    this.loadDateRange();
    this.loadCategories();
    // Recalculate chart sizes after DOM is ready
    setTimeout(() => this.onResize(), 100);
  }

  loadCategories() {
    this.http.get<any>(`${this.api}/categories`, { headers: this.getHeaders() }).subscribe({
      next: (r) => { if (r.categories?.length) this.allSystemCats = r.categories; },
      error: () => {}
    });
  }

  // ── HELPERS ───────────────────────────────────────────────────────────────
  tabLabel() { return ({overview:'Overview',analytics:'Analytics',transactions:'Transactions',ai:'AI Chat'} as any)[this.tab]||''; }
  go(t: string) { this.tab = t; this.sidebarOpen = false; }
  pct(v: number, total: number) { return total > 0 ? (v / total) * 100 : 0; }
  autoType(e: any) { return (e.target?.files?.[0]?.name||'').endsWith('.pdf') ? 'pdf' : 'csv'; }
  showToast(msg: string, ok = true) { this.toast={msg,ok}; setTimeout(()=>this.toast={msg:'',ok:true},4000); }

  // ── UPLOAD ────────────────────────────────────────────────────────────────
  onFile(e: any, type: string) {
    const f = e.target?.files?.[0]; e.target.value = '';
    if (f) this.process(f, type);
  }

  process(file: File, type: string) {
    this.uploading = true;
    const fd = new FormData(); fd.append('file', file);
    const url = type === 'pdf' ? `${this.api}/upload` : `${this.api}/upload-csv`;
    this.http.post<any>(url, fd, { headers: this.getHeaders() }).subscribe({
      next: (r) => {
        this.uploading = false;
        this.totalStored = r.total_stored;
        this.showToast(`${r.inserted} new · ${r.skipped} duplicates skipped · ${r.total_stored} total`);
        this.loadDateRange(); this.loadAnalytics(); this.autoIndex();
      },
      error: (err) => { this.uploading=false; this.showToast(err.error?.detail||'Import failed', false); }
    });
  }

  loadDateRange() {
    this.http.get<any>(`${this.api}/date-range`, { headers: this.getHeaders() }).subscribe({
      next: (r) => {
        this.totalStored = r.count || 0;
        this.dateMin = r.min || '';
        this.dateMax = r.max || '';
        if (!this.filterFrom) this.filterFrom = r.min || '';
        if (!this.filterTo)   this.filterTo   = r.max || '';
        if (this.totalStored > 0) this.loadAnalytics();
      },
      error: () => {}
    });
  }

  onDateFilter() { this.loadAnalytics(); }

  clearAllDates() {
    this.filterFrom = '';
    this.filterTo   = '';
    this.loadAnalytics();
  }

  resetDates() {
    this.filterFrom = this.dateMin;
    this.filterTo   = this.dateMax;
    this.loadAnalytics();
  }

  setThisMonth() {
    const now   = new Date();
    const first = new Date(now.getFullYear(), now.getMonth(), 1);
    const last  = new Date(now.getFullYear(), now.getMonth() + 1, 0);
    this.filterFrom = first.toISOString().slice(0,10);
    this.filterTo   = last.toISOString().slice(0,10);
    this.loadAnalytics();
  }

  setLast30() {
    const to   = new Date();
    const from = new Date(); from.setDate(from.getDate() - 30);
    this.filterFrom = from.toISOString().slice(0,10);
    this.filterTo   = to.toISOString().slice(0,10);
    this.loadAnalytics();
  }

  loadAnalytics() {
    const p: any = {};
    if (this.filterFrom) p['date_from'] = this.filterFrom;
    if (this.filterTo)   p['date_to']   = this.filterTo + 'T23:59:59';
    this.http.get<any>(`${this.api}/analytics`, { params: p, headers: this.getHeaders() }).subscribe({
      next: (a) => {
        this.analytics = a;
        this.buildCharts();
        this.loadTransactions();
      },
      error: (err) => {
        // 404 means no transactions in range — clear analytics
        if (err.status === 404) { this.analytics = null; this.transactions = []; this.filteredTxns = []; }
      }
    });
  }

  loadTransactions() {
    const p: any = {};
    if (this.filterFrom) p['date_from'] = this.filterFrom;
    if (this.filterTo)   p['date_to']   = this.filterTo + 'T23:59:59';
    this.http.get<any>(`${this.api}/transactions`, { params: p, headers: this.getHeaders() }).subscribe({
      next: (r) => {
        this.transactions = r.transactions || [];
        this.filteredTxns = [...this.transactions];
        this.allCats = [...new Set(this.transactions.map((t:any) => t.category).filter(Boolean))] as string[];
        this.applyFilter();
      },
      error: () => {}
    });
  }

  buildCharts() {
    const a = this.analytics; if (!a) return;

    const colors = ['#60a5fa','#f97316','#4ade80','#a78bfa','#fbbf24','#f87171','#22d3ee','#94a3b8','#fb923c','#34d399'];
    this.pieData = Object.entries(a.category_breakdown||{})
      .map(([name,value],i)=>({name,value:Math.abs(value as number),color:this.catColors[name]||colors[i%colors.length]}))
      .filter(d=>d.value>0).sort((a,b)=>b.value-a.value);

    this.monthlyData = Object.entries(a.monthly_trend||{})
      .map(([name,value])=>({name,value:Math.abs(value as number)}));

    const ws = Object.entries(a.weekly_trend||{});
    this.weeklyData = ws.length>1 ? [{ name:'Spending', series: ws.map(([n,v])=>({name:n.slice(5),value:Math.abs(v as number)})) }] : [];

    const dowOrder=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
    const dow = a.dow_spending||{};
    this.dowData = dowOrder.map(d=>({name:d.slice(0,3),value:dow[d]||0})).filter(d=>d.value>0);

    this.merchantData = (a.top_merchants||[]).slice(0,8).map((m:any)=>({
      name: m.name?.length>18 ? m.name.substring(0,18)+'…' : m.name, value: m.spent
    }));

    // Update scheme with category colors
    const catColors = this.pieData.map(d => d.color);
    const fullColors = [...new Set([...catColors, ...colors])];
    this.scheme = { name: 'upi', selectable: false, group: 'Ordinal', domain: fullColors };
  }

  applyFilter() {
    this.filteredTxns = this.transactions.filter(t=>{
      if (this.fType && t.transaction_type!==this.fType) return false;
      if (this.fCat  && t.category!==this.fCat) return false;
      if (this.fSearch && !t.merchant?.toLowerCase().includes(this.fSearch.toLowerCase())) return false;
      return true;
    });
    this.showN = 100;
  }

  confirmClear() {
    if (!confirm('Delete ALL your saved transactions? Cannot be undone.')) return;
    this.http.delete(`${this.api}/transactions`, { headers: this.getHeaders() }).subscribe({
      next: () => {
        this.totalStored=0; this.analytics=null; this.transactions=[];
        this.filteredTxns=[]; this.filterFrom=''; this.filterTo='';
        this.showToast('All transactions cleared');
      }
    });
  }

  downloadSample() {
    const d='Name,Bank,Amount,Date,Status\nHumsafar EHT,SBI 9299,-3000.00,30 May 2026,SUCCESS\nNusrat Fatima,SBI XXXXXX9299,+860.00,31 May 2026,SUCCESS\nNEW NATIONAL MEDICAL,SBI 9299,-120.00,30 May 2026,SUCCESS';
    const a=document.createElement('a');
    a.href=URL.createObjectURL(new Blob([d],{type:'text/csv'}));
    a.download='sample.csv'; a.click();
  }

  // ── AI ────────────────────────────────────────────────────────────────────
  checkOllama() {
    this.http.get<any>(`${this.api}/rag/status`).subscribe({
      next:(s)=>{ this.ollamaOk=s.ollama?.running; this.status=s.ollama; this.indexedCount=s.indexed_count; },
      error:()=>{ this.ollamaOk=false; }
    });
  }

  autoIndex() {
    this.http.post<any>(`${this.api}/rag/index`,{},{headers:this.getHeaders()}).subscribe({
      next:(r)=>{ this.indexedCount=r.indexed; }, error:()=>{}
    });
  }

  reIndex() {
    this.indexing=true;
    this.http.post<any>(`${this.api}/rag/index`,{},{headers:this.getHeaders()}).subscribe({
      next:(r)=>{ this.indexedCount=r.indexed; this.indexing=false; },
      error:()=>{ this.indexing=false; }
    });
  }

  ask(q:string){this.question=q;this.send();}

  send() {
    const q=this.question.trim(); if(!q||this.chatLoading) return;
    this.messages.push({role:'user',text:q}); this.question=''; this.chatLoading=true;
    const ph:Message={role:'assistant',text:'',loading:true};
    this.messages.push(ph); this.scroll();
    this.http.post<any>(`${this.api}/rag/query`,{question:q}).subscribe({
      next:(r)=>{ this.messages[this.messages.indexOf(ph)]={role:'assistant',text:r.answer,sources:r.sources}; this.chatLoading=false; this.scroll(); },
      error:()=>{ this.messages[this.messages.indexOf(ph)]={role:'assistant',text:'Error contacting backend.'}; this.chatLoading=false; }
    });
  }

  startEditCat(t: any) {
    this.editingCat = t.id;
    this.editingCatVal = t.category || '';
    this.customCatInput = '';
  }

  onCatChange(t: any) {}

  saveCat(t: any) {
    const cat = this.editingCatVal === '__custom__'
      ? this.customCatInput.trim()
      : this.editingCatVal;
    if (!cat) return;
    this.http.patch<any>(`${this.api}/transactions/${t.id}`,
      { category: cat }, { headers: this.getHeaders() }).subscribe({
      next: (r) => {
        t.category = r.category;
        t.custom_category = r.custom_category;
        this.editingCat = null;
        this.customCatInput = '';
        if (r.all_categories?.length) {
          this.allSystemCats = r.all_categories;
          this.allCats = r.all_categories;
        }
        this.loadAnalytics();
        this.showToast('Category updated to "' + cat + '"');
      },
      error: () => this.showToast('Failed to update category', false)
    });
  }

  toggleIncluded(t: any) {
    this.http.patch<any>(`${this.api}/transactions/${t.id}`,
      { included: !t.included }, { headers: this.getHeaders() }).subscribe({
      next: (r) => { t.included = r.included; this.loadAnalytics(); },
      error: () => this.showToast('Failed to update', false)
    });
  }

    private scroll(){setTimeout(()=>{if(this.chatWin?.nativeElement)this.chatWin.nativeElement.scrollTop=9999;},50);}
}
