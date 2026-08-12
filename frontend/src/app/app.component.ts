import { Component, OnInit, ViewChild, ElementRef, HostListener, ViewEncapsulation } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { NgxChartsModule, LegendPosition } from '@swimlane/ngx-charts';

interface Message { role:'user'|'assistant'; text:string; sources?:string[]; loading?:boolean; }
interface User { id:number; email:string; name:string; is_admin?:boolean; }

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
      <button class="sb-lnk admin-lnk" [class.on]="tab==='admin'" (click)="go('admin'); loadAdminData()" *ngIf="isAdmin">
        <svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
        Admin
        <span class="sb-badge-red" *ngIf="adminStats?.online_now">{{ adminStats?.online_now }}</span>
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
      <button class="sb-logout secondary" (click)="showChangePw=!showChangePw">Change password</button>
      <div class="pw-form" *ngIf="showChangePw">
        <input class="pw-in" type="password" [(ngModel)]="pwCurrent" placeholder="Current password">
        <input class="pw-in" type="password" [(ngModel)]="pwNew"     placeholder="New password">
        <input class="pw-in" type="password" [(ngModel)]="pwConfirm" placeholder="Confirm new">
        <div class="pw-msg" [class.ok]="pwOk" [class.err]="!pwOk" *ngIf="pwMsg">{{ pwMsg }}</div>
        <button class="pw-save" (click)="changePassword()">Save</button>
      </div>
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

      <!-- Received summary strip -->
      <div class="recv-strip" *ngIf="analytics.total_received > 0">
        <div class="recv-kpi">
          <div class="recv-val">₹{{ analytics.total_received | number:'1.0-0' }}</div>
          <div class="recv-lbl">Total received</div>
        </div>
        <div class="recv-kpi">
          <div class="recv-val">{{ analytics.received_count || 0 }}</div>
          <div class="recv-lbl">Incoming transactions</div>
        </div>
        <div class="recv-kpi">
          <div class="recv-val" [class.g]="analytics.net_flow>=0" [class.r]="analytics.net_flow<0">
            {{ analytics.net_flow>=0?'+':'' }}₹{{ analytics.net_flow | number:'1.0-0' }}
          </div>
          <div class="recv-lbl">Net flow</div>
        </div>
        <div class="recv-kpi">
          <div class="recv-val">₹{{ analytics.average_transaction | number:'1.0-0' }}</div>
          <div class="recv-lbl">Avg payment</div>
        </div>
      </div>

      <div class="grid">

        <!-- Monthly compared: Spent vs Received -->
        <div class="card wide" *ngIf="monthlyComparedData.length && monthlyComparedData[0]?.series?.length">
          <div class="ch">Monthly — Spent vs Received</div>
          <ngx-charts-bar-vertical-2d [results]="monthlyComparedData"
            [xAxis]="true" [yAxis]="true" [showDataLabel]="true"
            [groupPadding]="4" [view]="[wideW, 240]" [scheme]="schemeCompare">
          </ngx-charts-bar-vertical-2d>
        </div>

        <!-- Spending category breakdown -->
        <div class="card" *ngIf="pieData.length">
          <div class="ch">Spending by category</div>
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

        <!-- Received sources -->
        <div class="card" *ngIf="receivedSourceData.length">
          <div class="ch">Income sources</div>
          <ngx-charts-bar-horizontal [results]="receivedSourceData"
            [xAxis]="true" [yAxis]="true" [showDataLabel]="true"
            [view]="[cardW, 220]" [scheme]="schemeGreen">
          </ngx-charts-bar-horizontal>
        </div>

        <!-- Weekly trend -->
        <div class="card wide" *ngIf="weeklyData.length && weeklyData[0]?.series?.length > 1">
          <div class="ch">Weekly spending trend</div>
          <ngx-charts-line-chart [results]="weeklyData" [xAxis]="true" [yAxis]="true"
            [showGridLines]="true" [tooltipDisabled]="false"
            [view]="[wideW, 200]" [scheme]="scheme">
          </ngx-charts-line-chart>
        </div>

        <!-- Day of week -->
        <div class="card" *ngIf="dowData.length">
          <div class="ch">Spending by weekday</div>
          <ngx-charts-bar-vertical [results]="dowData" [xAxis]="true" [yAxis]="true"
            [showDataLabel]="true" [view]="[cardW, 220]" [scheme]="scheme">
          </ngx-charts-bar-vertical>
        </div>

        <!-- Top merchants -->
        <div class="card" *ngIf="merchantData.length">
          <div class="ch">Top spending merchants</div>
          <ngx-charts-bar-horizontal [results]="merchantData" [xAxis]="true" [yAxis]="true"
            [showDataLabel]="true" [view]="[cardW, 260]" [scheme]="scheme">
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
      <!-- Compact top bar for AI settings -->
      <div class="ai-topbar">
        <div class="ai-status-row">
          <div class="ait-status" [class.on]="ollamaOk" [class.off]="!ollamaOk">
            <span class="ait-dot"></span>
            {{ ollamaOk ? (status?.provider==='groq' ? 'Groq AI' : status?.active_model||'Online') : 'AI Offline' }}
          </div>
          <div class="ait-idx" *ngIf="indexedCount">{{ indexedCount }} docs</div>
          <button class="ait-btn" (click)="reIndex()" [disabled]="indexing||!totalStored">
            {{ indexing ? 'Indexing…' : 'Re-index' }}
          </button>
        </div>
        <div class="ai-suggestions">
          <button class="ait-sugg" *ngFor="let q of suggestions" (click)="ask(q)">{{ q }}</button>
        </div>
      </div>

      <!-- Chat area -->
      <div class="ai-chat">
        <div class="chat-msgs" #chatWin>
          <div class="chat-empty" *ngIf="!messages.length">
            <div class="ce-t">AI Transaction Analyst</div>
            <div class="ce-s">Import transactions then ask anything about your spending.</div>
            <div class="ce-s" *ngIf="!ollamaOk" style="color:#f87171;margin-top:8px">
              AI unavailable — check GROQ_API_KEY in Railway environment variables
            </div>
          </div>
          <div *ngFor="let m of messages" class="msg-row" [class.user]="m.role==='user'">
            <div class="bub" [class.bu]="m.role==='user'" [class.bb]="m.role==='assistant'">
              <span *ngIf="m.loading" class="ld"><i></i><i></i><i></i></span>
              <span *ngIf="!m.loading" style="white-space:pre-wrap">{{ m.text }}</span>
            </div>
          </div>
        </div>
        <div class="chat-bar">
          <input class="chat-in" [(ngModel)]="question" (keydown.enter)="send()"
                 [disabled]="chatLoading" placeholder="Ask about your spending…">
          <button class="chat-send" (click)="send()" [disabled]="chatLoading||!question.trim()">
            <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
          </button>
        </div>
      </div>
    </div>

        <!-- ADMIN TAB -->
    <main class="page" *ngIf="tab==='admin' && isAdmin">

      <div class="adm-header">
        <div>
          <div class="adm-title">Admin Dashboard</div>
          <div class="adm-sub">Platform overview · auto-refreshes every 30s</div>
        </div>
        <button class="adm-refresh" (click)="loadAdminData()" [disabled]="adminLoading">
          {{ adminLoading ? '…' : '↻ Refresh' }}
        </button>
      </div>

      <!-- Stats cards -->
      <div class="adm-kpis" *ngIf="adminStats">
        <div class="adm-kpi">
          <div class="adm-kpi-n">{{ adminStats.total_users }}</div>
          <div class="adm-kpi-l">Total users</div>
        </div>
        <div class="adm-kpi adm-kpi-green">
          <div class="adm-kpi-n">{{ adminStats.online_now }}</div>
          <div class="adm-kpi-l">● Online now</div>
        </div>
        <div class="adm-kpi">
          <div class="adm-kpi-n">{{ adminStats.new_today }}</div>
          <div class="adm-kpi-l">New today</div>
        </div>
        <div class="adm-kpi">
          <div class="adm-kpi-n">{{ adminStats.total_txns | number }}</div>
          <div class="adm-kpi-l">Total transactions</div>
        </div>
      </div>

      <!-- Users table -->
      <div class="adm-card">
        <div class="adm-card-head">
          Users
          <span class="adm-online-badge" *ngIf="adminStats?.online_now">
            {{ adminStats.online_now }} online
          </span>
          <span class="adm-total-badge">{{ adminUsers.length }} total</span>
        </div>
        <div *ngIf="!adminUsers.length && !adminLoading" class="adm-empty">
          No users yet — click Refresh
        </div>
        <table class="adm-tbl" *ngIf="adminUsers.length">
          <thead>
            <tr>
              <th>Status</th>
              <th>Name</th>
              <th>Email</th>
              <th>Transactions</th>
              <th>Last data</th>
              <th>Last active</th>
              <th>Role</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr *ngFor="let u of adminUsers" [class.adm-row-online]="u.online">
              <td>
                <span class="adm-status" [class.adm-online]="u.online" [class.adm-offline]="!u.online">
                  {{ u.online ? '●' : '○' }}
                </span>
              </td>
              <td class="adm-name">{{ u.name }}</td>
              <td class="adm-email">{{ u.email }}</td>
              <td class="adm-num">{{ u.txn_count }}</td>
              <td class="adm-dim">{{ u.latest_txn_date ? (u.latest_txn_date | date:'d MMM yy') : '—' }}</td>
              <td class="adm-dim">{{ u.last_seen ? (u.last_seen | date:'d MMM, h:mm a') : 'Never' }}</td>
              <td>
                <span class="adm-role" [class.adm-role-admin]="u.is_admin">
                  {{ u.is_admin ? 'Admin' : 'User' }}
                </span>
              </td>
              <td>
                <button class="adm-del" *ngIf="!u.is_admin"
                  (click)="deleteUser(u)" title="Delete user">✕</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

    </main>

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
      --surface: #161616;
      --border: #252525;
      --border2: #333333;
      --text: #e0e0e0;
      --text2: #aaa;
      --text3: #666;
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
    .auth-sub{font-size:13px;color:#666;margin-bottom:24px}
    .auth-tabs{display:flex;gap:2px;background:#0d0d0d;border-radius:8px;padding:3px;margin-bottom:20px}
    .auth-tabs button{flex:1;padding:7px;border:none;background:none;color:#aaa;border-radius:6px;cursor:pointer;font-size:13px;font-weight:500;transition:all .15s}
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
    .sb-user{font-size:11px;color:#666;margin-top:1px}
    .sb-nav{padding:10px 8px;display:flex;flex-direction:column;gap:2px}
    .sb-lnk{display:flex;align-items:center;gap:9px;padding:9px 10px;border-radius:8px;border:none;background:none;color:#666;cursor:pointer;font-size:13px;font-weight:500;text-align:left;width:100%;transition:all .15s;position:relative}
    .sb-lnk:hover:not(:disabled){background:#1a1a1a;color:#e0e0e0}
    .sb-lnk.on{background:#1e1e1e;color:#ffffff}
    .sb-lnk:disabled{opacity:.2;cursor:default}
    .sb-pill{margin-left:auto;font-size:10px;background:#1a1a1a;color:#666;padding:1px 7px;border-radius:10px}
    .sb-online{width:6px;height:6px;border-radius:50%;background:var(--green);margin-left:auto;animation:pg 2s infinite}
    @keyframes pg{0%,100%{box-shadow:0 0 0 0 rgba(74,222,128,.4)}50%{box-shadow:0 0 0 4px rgba(74,222,128,0)}}
    .sb-gap{flex:1;min-height:8px}

    .sb-filter{padding:12px 14px 8px;border-top:1px solid var(--border);flex-shrink:0}
    .sb-filter-lbl{font-size:10px;font-weight:600;color:#666;text-transform:uppercase;letter-spacing:.7px;margin-bottom:8px}
    .sb-dates{display:flex;align-items:center;gap:6px;margin-bottom:6px}
    .din{background:#111;border:1px solid var(--border);color:#aaa;border-radius:6px;padding:6px 7px;font-size:11px;width:100%;outline:none;color-scheme:dark}
    .din:focus{border-color:var(--border2);color:#e0e0e0}
    .din-sep{color:#666;font-size:11px;flex-shrink:0}
    .date-actions{display:flex;gap:6px;margin-bottom:4px}
    .sb-reset{background:#141414;border:1px solid var(--border);color:#aaa;font-size:11px;cursor:pointer;padding:4px 8px;border-radius:5px;transition:all .15s}
    .sb-reset:hover{border-color:var(--border2);color:#e0e0e0}
    .sb-reset:hover{color:#aaa}
    .sb-range-info{font-size:11px;color:#666;margin-top:4px;margin-bottom:4px}

    .sb-foot{padding:12px;border-top:1px solid var(--border);display:flex;flex-direction:column;gap:6px;flex-shrink:0}
    .sb-import-btn{display:flex;align-items:center;gap:8px;padding:9px 12px;background:#151515;border:1px solid var(--border);border-radius:8px;color:#aaa;cursor:pointer;font-size:12px;font-weight:500;transition:all .15s}
    .sb-import-btn:hover{border-color:var(--border2);color:#e0e0e0;background:#181818}
    .sb-clear-btn{background:none;border:1px solid var(--border);color:#666;border-radius:6px;padding:7px;font-size:11px;cursor:pointer;transition:all .15s}
    .sb-clear-btn:hover{border-color:#3a1515;color:var(--red);background:#1a0a0a}
    .sb-logout{background:none;border:none;color:#666;font-size:11px;cursor:pointer;padding:4px 0;text-align:left;transition:color .15s}
    .sb-logout:hover{color:#aaa}

    .overlay{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:40;display:none}

    /* ── MAIN ── */
    .main{flex:1;display:flex;flex-direction:column;min-width:0;overflow:hidden}
    .bar{height:50px;border-bottom:1px solid var(--border);display:flex;align-items:center;padding:0 20px;gap:12px;flex-shrink:0;background:#0a0a0a}
    .burger{display:none;background:none;border:none;color:#666;cursor:pointer;padding:5px;border-radius:6px}
    .burger:hover{background:#181818;color:var(--text)}
    .bar-title{font-size:15px;font-weight:600;color:#ffffff;letter-spacing:-.2px}
    .bar-right{margin-left:auto}
    .toast{font-size:12px;padding:6px 12px;border-radius:7px}
    .toast.tok{background:#0a1f11;color:var(--green);border:1px solid #1a3a22}
    .toast.terr{background:#1f0a0a;color:var(--red);border:1px solid #3a1a1a}

    .page{flex:1;overflow-y:auto;padding:24px}

    /* ── EMPTY ── */
    .empty{display:flex;align-items:center;justify-content:center;height:100%}
    .empty-box{text-align:center;max-width:420px}
    .empty-ico{width:60px;height:60px;background:#151515;border:1px solid var(--border);border-radius:16px;display:flex;align-items:center;justify-content:center;margin:0 auto 20px;color:#2a2a2a}
    .empty-box h2{font-size:22px;font-weight:600;color:#f0f0f0;margin-bottom:8px;letter-spacing:-.3px}
    .empty-box p{color:#555;line-height:1.7;margin-bottom:24px}
    .empty-acts{display:flex;gap:10px;justify-content:center}
    .btn-w{padding:10px 22px;background:var(--accent);color:#0a0a0a;border:none;border-radius:8px;cursor:pointer;font-size:13px;font-weight:600}
    .btn-w:hover{background:#ddd}
    .btn-o{padding:10px 22px;background:none;color:#aaa;border:1px solid var(--border);border-radius:8px;cursor:pointer;font-size:13px}
    .btn-o:hover{border-color:var(--border2);color:var(--text)}

    /* ── KPIS ── */
    .dash{display:flex;flex-direction:column;gap:20px}
    .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:1px;background:var(--border);border:1px solid var(--border);border-radius:12px;overflow:hidden}
    .kpi{background:var(--bg);padding:18px 20px}
    .kn{font-size:24px;font-weight:700;color:#ffffff;letter-spacing:-.5px;font-variant-numeric:tabular-nums;line-height:1}
    .kn.g{color:var(--green)} .kn.r{color:var(--red)}
    .kl{font-size:10px;color:#666;text-transform:uppercase;letter-spacing:.6px;margin-top:5px;font-weight:600}
    .ks{font-size:11px;color:#666;margin-top:3px}

    /* ── GRID ── */
    .grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
    .card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;overflow:hidden}
    .card.wide{grid-column:1/-1}
    .ch{font-size:11px;font-weight:600;color:#aaa;text-transform:uppercase;letter-spacing:.6px;margin-bottom:16px;display:flex;align-items:center;gap:8px}
    .tag{font-size:10px;font-weight:500;padding:2px 7px;border-radius:5px;background:#1a1a1a;color:#666;text-transform:none;letter-spacing:0}
    .tag.warn{background:#1f1208;color:#fb923c}

    /* ── PIE + LEGEND ── */
    .pie-wrap{display:flex;align-items:center;gap:20px}
    .pie-legend{display:flex;flex-direction:column;gap:8px;flex:1}
    .pl-row{display:flex;align-items:center;gap:8px}
    .pl-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
    .pl-name{font-size:12px;color:#aaa;flex:1}
    .pl-val{font-size:12px;font-weight:600;color:var(--text);font-variant-numeric:tabular-nums}

    /* ── ROWS ── */
    .rows{display:flex;flex-direction:column;gap:12px}
    .row-item{display:flex;align-items:center;gap:12px}
    .ri-l{flex:1;min-width:0}
    .ri-name{font-size:13px;color:#ccc;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .ri-sub{font-size:11px;color:#666;margin-top:2px}
    .ri-val{font-size:13px;font-weight:600;font-variant-numeric:tabular-nums;flex-shrink:0;color:#aaa}
    .ri-val.r{color:var(--red)} .ri-val.g{color:var(--green)} .ri-val.dim{color:#666}

    /* ── CAT LIST ── */
    .cat-list{display:flex;flex-direction:column;gap:10px}
    .cat-row{display:flex;align-items:center;gap:10px}
    .cat-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
    .cat-name{font-size:12px;color:#aaa;width:120px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex-shrink:0}
    .cat-bar-wrap{flex:1;height:4px;background:#1a1a1a;border-radius:2px;overflow:hidden}
    .cat-bar{height:100%;border-radius:2px;transition:width .4s}
    .cat-pct{font-size:11px;color:#666;width:32px;text-align:right;flex-shrink:0}
    .cat-amt{font-size:12px;color:#aaa;width:76px;text-align:right;font-variant-numeric:tabular-nums;flex-shrink:0}

    /* ── CHART OVERRIDES (visibility) ── */
    .ngx-charts text{fill:#888!important;font-size:11px!important;font-family:-apple-system,'Inter','Segoe UI',sans-serif!important}
    .ngx-charts .gridline-path,.ngx-charts .refline-path{stroke:#1e1e1e!important}
    .ngx-charts .tick line{stroke:#1e1e1e!important}
    .ngx-charts .data-label{fill:#d0d0d0!important;font-size:11px!important;font-weight:600!important}
    .ngx-charts .pie-label{fill:#bbb!important;font-size:11px!important}
    .ngx-charts .pie-label-line{stroke:#333!important}
    .ngx-charts .x.axis .tick text,.ngx-charts .y.axis .tick text{fill:#888!important;font-size:11px!important}
    .ngx-charts .axis-label{fill:#555!important}
    .ngx-charts .tooltip-anchor{fill:#fff!important}
    .ngx-charts .bar:hover,.ngx-charts .cell:hover{opacity:.85}
    .chart-legend .legend-label-text{color:#888!important;font-size:11px!important}
    .chart-legend .legend-title-text{color:#555!important;font-size:11px!important}

    /* ── TXNS ── */
    .txn-bar{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;flex-wrap:wrap;gap:10px}
    .txn-ct{font-size:11px;font-weight:600;color:#666;text-transform:uppercase;letter-spacing:.6px}
    .txn-tools{display:flex;gap:8px;flex-wrap:wrap}
    .ctl{background:var(--surface);border:1px solid var(--border);color:#aaa;border-radius:7px;padding:7px 10px;font-size:12px;outline:none;transition:all .15s}
    .ctl:focus,.ctl:hover{border-color:var(--border2);color:var(--text)}
    .ctl-search{min-width:170px}
    .tbl-box{background:var(--surface);border:1px solid var(--border);border-radius:12px;overflow:hidden}
    .tbl{width:100%;border-collapse:collapse}
    .tbl th{text-align:left;padding:10px 14px;font-size:10px;font-weight:600;color:#666;text-transform:uppercase;letter-spacing:.6px;border-bottom:1px solid #161616}
    .tbl td{padding:10px 14px;border-bottom:1px solid #111;vertical-align:middle}
    .tbl tr:last-child td{border-bottom:none}
    .tbl tr:hover td{background:#111}
    .td-m{color:#ddd;max-width:220px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .td-a{font-weight:600;font-variant-numeric:tabular-nums}
    .td-a.r{color:var(--red)} .td-a.g{color:var(--green)}
    .td-d,.td-c{color:#666;font-size:11px}
    .td-st{font-size:11px} .td-st.g{color:var(--green)} .td-st.r{color:var(--red)}
    .pill{padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600}
    .ps{background:#1f0e0e;color:var(--red)} .pr{background:#0e1f0e;color:var(--green)}
    .load-more{text-align:center;padding:14px;color:#666;cursor:pointer;font-size:12px;border-top:1px solid #131313}
    .load-more:hover{color:#aaa}

    /* ── AI ── */
    .ai-wrap{display:flex;flex:1;overflow:hidden}
    .ai-side{width:210px;flex-shrink:0;border-right:1px solid var(--border);padding:16px 14px;overflow-y:auto;background:#0a0a0a;display:flex;flex-direction:column;gap:0}
    .as-sec{padding:10px 0;display:flex;flex-direction:column;gap:6px}
    .as-div{height:1px;background:var(--border)}
    .as-lbl{font-size:10px;font-weight:600;color:#666;text-transform:uppercase;letter-spacing:.7px;margin-bottom:2px}
    .as-status{display:flex;align-items:center;gap:6px;font-size:11px;padding:7px 9px;border-radius:7px}
    .as-status.on{background:#0a1a0f;color:var(--green);border:1px solid #0f2a18}
    .as-status.off{background:#1a0a0a;color:var(--red);border:1px solid #2a0f0f}
    .as-dot{width:6px;height:6px;border-radius:50%;background:currentColor;flex-shrink:0}
    .as-cmd{display:block;font-size:11px;color:#444;padding:5px 8px;background:#111;border-radius:5px;font-family:monospace}
    .as-idx{font-size:10px;color:var(--green);opacity:.6}
    .as-btn{background:#141414;border:1px solid var(--border);color:#666;border-radius:6px;padding:8px;font-size:11px;cursor:pointer;transition:all .15s}
    .as-btn:hover:not(:disabled){background:#1a1a1a;color:#aaa}
    .as-btn:disabled{opacity:.3;cursor:default}
    .as-q{background:none;border:none;color:#666;font-size:11px;text-align:left;padding:5px 0;cursor:pointer;line-height:1.6;transition:color .15s}
    .as-q:hover{color:#aaa}
    .ai-chat{flex:1;display:flex;flex-direction:column;min-width:0}
    .chat-msgs{flex:1;overflow-y:auto;padding:24px;display:flex;flex-direction:column;gap:16px}
    .chat-empty{margin:auto;text-align:center}
    .ce-t{font-size:16px;font-weight:500;color:#666;margin-bottom:6px}
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
    .src details summary{cursor:pointer;color:#666}
    .src ul{margin:4px 0 0 10px;color:#666;line-height:1.7}
    .chat-bar{border-top:1px solid var(--border);padding:14px 18px;display:flex;gap:8px;flex-shrink:0}
    .chat-in{flex:1;background:#111;border:1px solid var(--border);color:#e8e8e8;border-radius:8px;padding:10px 14px;font-size:13px;outline:none;font-family:inherit;transition:border-color .15s}
    .chat-in:focus{border-color:var(--border2)}
    .chat-send{width:40px;height:40px;background:var(--surface);border:1px solid var(--border);color:#aaa;border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all .15s}
    .chat-send:not(:disabled):hover{background:#222;color:var(--text);border-color:var(--border2)}
    .chat-send:disabled{opacity:.25;cursor:default}


    .excluded-row td { opacity:.45 }
    .dim { opacity:.4 }
    .td-cat { min-width:130px }
    .cat-cell { display:flex; align-items:center; gap:5px; cursor:pointer; padding:2px 4px; border-radius:4px; transition:background .15s }
    .cat-cell:hover { background:#1a1a1a }
    .cat-lbl { font-size:12px; color:#aaa }
    .cat-lbl.custom-cat { color:#a78bfa }
    .cat-edit-ico { font-size:10px; color:#666; opacity:0; transition:opacity .15s }
    .cat-cell:hover .cat-edit-ico { opacity:1 }
    .cat-edit-wrap { display:flex; align-items:center; gap:4px; flex-wrap:wrap }
    .cat-sel { background:#111; border:1px solid var(--border2); color:var(--text); border-radius:5px; padding:4px 6px; font-size:11px; outline:none; max-width:140px }
    .cat-custom-in { background:#111; border:1px solid var(--border2); color:var(--text); border-radius:5px; padding:4px 8px; font-size:11px; outline:none; width:120px }
    .cat-save { background:#0a2a14; border:1px solid #1a5a2a; color:var(--green); border-radius:4px; padding:3px 7px; font-size:11px; cursor:pointer }
    .cat-cancel { background:#1a1a1a; border:1px solid var(--border); color:#666; border-radius:4px; padding:3px 7px; font-size:11px; cursor:pointer }
    .td-toggle { text-align:center; width:40px }
    .toggle-btn { background:none; border:none; cursor:pointer; font-size:16px; padding:2px 6px; border-radius:4px; transition:all .15s; line-height:1 }
    .toggle-btn.on { color:var(--green) }
    .toggle-btn.off { color:#666 }
    .toggle-btn:hover { background:#1a1a1a }
    .txn-excl { font-size:11px; color:#666; font-weight:400 }

    /* ── Received strip ── */
    .recv-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;background:var(--border);border:1px solid var(--border);border-radius:10px;overflow:hidden;margin-bottom:20px}
    .recv-kpi{background:#0f1a0f;padding:16px 20px}
    .recv-val{font-size:20px;font-weight:700;color:#4ade80;letter-spacing:-.5px;font-variant-numeric:tabular-nums}
    .recv-val.r{color:var(--red)} .recv-val.g{color:var(--green)}
    .recv-lbl{font-size:10px;color:#2a5a2a;text-transform:uppercase;letter-spacing:.6px;margin-top:4px;font-weight:600}

    /* ── Admin ── */
    .admin-lnk{color:#f59e0b!important}
    .admin-lnk.on{background:#1a1505!important;color:#fbbf24!important}
    .sb-badge-red{margin-left:auto;font-size:10px;background:#4ade80;color:#0a0a0a;padding:1px 6px;border-radius:10px;font-weight:700}
    .admin-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px}
    .admin-title{font-size:18px;font-weight:600;color:#f0f0f0}
    .admin-refresh{background:#141414;border:1px solid var(--border);color:#aaa;padding:7px 14px;border-radius:7px;cursor:pointer;font-size:12px}
    .admin-refresh:hover{border-color:var(--border2);color:#e0e0e0}
    .admin-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1px;background:var(--border);border:1px solid var(--border);border-radius:10px;overflow:hidden;margin-bottom:24px}
    .admin-kpi{background:var(--bg);padding:18px 20px}
    .admin-kpi.online{background:#0a1a0a}
    .ak-val{font-size:24px;font-weight:700;color:#f0f0f0;letter-spacing:-.5px}
    .ak-val.g{color:#4ade80}
    .ak-lbl{font-size:10px;color:#666;text-transform:uppercase;letter-spacing:.6px;margin-top:4px;display:flex;align-items:center;gap:4px}
    .online-dot{color:#4ade80;animation:pg 2s infinite}
    .admin-section{background:var(--surface);border:1px solid var(--border);border-radius:12px;overflow:hidden}
    .admin-section-title{font-size:11px;font-weight:600;color:#666;text-transform:uppercase;letter-spacing:.6px;padding:14px 16px;border-bottom:1px solid var(--border)}
    .admin-tbl-box{overflow-x:auto}
    .admin-tbl{width:100%;border-collapse:collapse}
    .admin-tbl th{text-align:left;padding:10px 14px;font-size:10px;font-weight:600;color:#666;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid #161616}
    .admin-tbl td{padding:10px 14px;border-bottom:1px solid #111;font-size:13px}
    .admin-tbl tr:last-child td{border-bottom:none}
    .online-row td{background:#0a1209}
    .au-name{color:#e0e0e0;font-weight:500}
    .au-email{color:#aaa}
    .au-txn{color:#aaa;font-variant-numeric:tabular-nums}
    .au-time{color:#666;font-size:11px}
    .status-pill{padding:3px 9px;border-radius:10px;font-size:11px;font-weight:600}
    .online-pill{background:#0a2a14;color:#4ade80;border:1px solid #1a5a2a}
    .offline-pill{background:#1a1a1a;color:#666;border:1px solid var(--border)}
    .role-pill{padding:3px 9px;border-radius:10px;font-size:11px;background:#1a1a1a;color:#666}
    .admin-pill{background:#1a1505;color:#fbbf24}


    .sb-logout.secondary{color:#555;font-size:11px;background:none;border:none;cursor:pointer;text-align:left;padding:3px 0}
    .pw-form{display:flex;flex-direction:column;gap:6px;padding:8px;background:#0d0d0d;border-radius:8px;border:1px solid var(--border)}
    .pw-in{background:#111;border:1px solid var(--border);color:#e0e0e0;border-radius:6px;padding:7px 10px;font-size:12px;outline:none}
    .pw-in:focus{border-color:var(--border2)}
    .pw-msg{font-size:11px;padding:3px 0}
    .pw-msg.ok{color:#4ade80} .pw-msg.err{color:#f87171}
    .pw-save{background:#f0f0f0;color:#0a0a0a;border:none;border-radius:6px;padding:7px;font-size:12px;font-weight:600;cursor:pointer}
    .pw-save:hover{background:#ddd}
    .online-count{margin-left:auto;font-size:11px;color:#4ade80;font-weight:400;text-transform:none;letter-spacing:0}
    .au-del{background:none;border:none;color:#3a2020;cursor:pointer;font-size:14px;padding:2px 6px;border-radius:4px;transition:all .15s}
    .au-del:hover{background:#1f0a0a;color:#f87171}
    .admin-section-title{font-size:11px;font-weight:600;color:#666;text-transform:uppercase;letter-spacing:.6px;padding:14px 16px;border-bottom:1px solid var(--border);display:flex;align-items:center}

    /* AI tab - single column, no side panel */
    .ai-wrap{display:flex;flex-direction:column;flex:1;overflow:hidden}
    .ai-topbar{border-bottom:1px solid var(--border);padding:10px 20px;background:#0a0a0a;flex-shrink:0}
    .ai-status-row{display:flex;align-items:center;gap:12px;margin-bottom:8px}
    .ait-status{display:flex;align-items:center;gap:6px;font-size:12px;padding:5px 10px;border-radius:6px}
    .ait-status.on{background:#0a1a0f;color:#4ade80;border:1px solid #1a4a2a}
    .ait-status.off{background:#1a0a0a;color:#f87171;border:1px solid #4a1a1a}
    .ait-dot{width:6px;height:6px;border-radius:50%;background:currentColor;flex-shrink:0}
    .ait-idx{font-size:11px;color:#555}
    .ait-btn{background:#161616;border:1px solid var(--border);color:#888;border-radius:6px;padding:5px 12px;font-size:11px;cursor:pointer;transition:all .15s}
    .ait-btn:hover:not(:disabled){background:#1e1e1e;color:#ccc}
    .ait-btn:disabled{opacity:.3;cursor:default}
    .ai-suggestions{display:flex;gap:6px;flex-wrap:wrap}
    .ait-sugg{background:#111;border:1px solid var(--border);color:#666;border-radius:6px;padding:5px 10px;font-size:11px;cursor:pointer;transition:all .15s;white-space:nowrap}
    .ait-sugg:hover{border-color:var(--border2);color:#bbb;background:#161616}

    /* ── Admin Dashboard ── */
    .adm-header{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:24px}
    .adm-title{font-size:20px;font-weight:600;color:#f0f0f0;letter-spacing:-.3px}
    .adm-sub{font-size:12px;color:#555;margin-top:3px}
    .adm-refresh{background:#1a1a1a;border:1px solid #252525;color:#888;padding:8px 16px;border-radius:7px;cursor:pointer;font-size:13px;transition:all .15s}
    .adm-refresh:hover:not(:disabled){background:#222;color:#e0e0e0}
    .adm-refresh:disabled{opacity:.4;cursor:default}

    .adm-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:1px;background:#252525;border:1px solid #252525;border-radius:12px;overflow:hidden;margin-bottom:20px}
    .adm-kpi{background:#0f0f0f;padding:20px 22px}
    .adm-kpi-green{background:#0a150a}
    .adm-kpi-n{font-size:28px;font-weight:700;color:#ffffff;letter-spacing:-1px;font-variant-numeric:tabular-nums}
    .adm-kpi-green .adm-kpi-n{color:#4ade80}
    .adm-kpi-l{font-size:11px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-top:5px;font-weight:600}

    .adm-card{background:#111;border:1px solid #1e1e1e;border-radius:12px;overflow:hidden;margin-bottom:16px}
    .adm-card-head{padding:14px 18px;font-size:11px;font-weight:600;color:#666;text-transform:uppercase;letter-spacing:.6px;border-bottom:1px solid #161616;display:flex;align-items:center;gap:10px}
    .adm-online-badge{font-size:11px;background:#0a2a14;color:#4ade80;padding:2px 9px;border-radius:10px;font-weight:600;text-transform:none;letter-spacing:0}
    .adm-total-badge{font-size:11px;background:#1a1a1a;color:#555;padding:2px 9px;border-radius:10px;font-weight:400;text-transform:none;letter-spacing:0;margin-left:auto}
    .adm-empty{padding:32px;text-align:center;color:#333;font-size:13px}

    .adm-tbl{width:100%;border-collapse:collapse}
    .adm-tbl th{text-align:left;padding:10px 14px;font-size:10px;font-weight:600;color:#333;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid #161616}
    .adm-tbl td{padding:11px 14px;border-bottom:1px solid #111;vertical-align:middle}
    .adm-tbl tr:last-child td{border-bottom:none}
    .adm-row-online td{background:#0a120a}
    .adm-status{font-size:14px;font-weight:700}
    .adm-online{color:#4ade80}
    .adm-offline{color:#2a2a2a}
    .adm-name{font-size:13px;color:#e0e0e0;font-weight:500}
    .adm-email{font-size:12px;color:#888}
    .adm-num{font-size:13px;color:#aaa;font-variant-numeric:tabular-nums}
    .adm-dim{font-size:11px;color:#444}
    .adm-role{font-size:11px;padding:3px 9px;border-radius:5px;background:#1a1a1a;color:#555}
    .adm-role-admin{background:#1a1505;color:#fbbf24}
    .adm-del{background:none;border:none;color:#2a1515;cursor:pointer;font-size:14px;padding:3px 8px;border-radius:5px;transition:all .15s}
    .adm-del:hover{background:#1f0a0a;color:#f87171}

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

    /* UI ENHANCEMENT LAYER — visual only, functionality unchanged */
    :host{
      --bg:#0b0c0e;--surface:#121417;--surface2:#171a1e;
      --border:#252a31;--border2:#353c45;--text:#f1f3f5;
      --text2:#a9b0b8;--text3:#68717c;--green:#4ade80;--red:#f87171;
      --blue:#60a5fa;--shadow:0 18px 55px rgba(0,0,0,.28);
      display:block;color-scheme:dark;
    }
    *{scrollbar-width:thin;scrollbar-color:#30353c transparent}
    *::-webkit-scrollbar{width:7px;height:7px}
    *::-webkit-scrollbar-track{background:transparent}
    *::-webkit-scrollbar-thumb{background:#2c3138;border-radius:20px}
    *::-webkit-scrollbar-thumb:hover{background:#414852}

    .page,.ai-wrap{animation:uiFade .3s ease both}
    @keyframes uiFade{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}
    @keyframes cardIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
    @keyframes toastIn{from{opacity:0;transform:translateY(-5px)}to{opacity:1;transform:none}}
    @keyframes livePulse{0%,100%{box-shadow:0 0 0 0 rgba(74,222,128,0)}50%{box-shadow:0 0 0 5px rgba(74,222,128,.08)}}

    /* Auth */
    .auth-screen{
      position:relative;overflow:hidden;
      background:radial-gradient(circle at 18% 20%,rgba(96,165,250,.09),transparent 30%),
                 radial-gradient(circle at 82% 78%,rgba(74,222,128,.07),transparent 28%),var(--bg);
    }
    .auth-screen:before{
      content:"";position:absolute;inset:0;pointer-events:none;
      background-image:linear-gradient(rgba(255,255,255,.018) 1px,transparent 1px),
                       linear-gradient(90deg,rgba(255,255,255,.018) 1px,transparent 1px);
      background-size:38px 38px;
    }
    .auth-box{
      position:relative;z-index:1;width:min(390px,calc(100vw - 32px));
      padding:38px;background:rgba(18,20,23,.88);
      border-color:rgba(255,255,255,.08);border-radius:22px;
      box-shadow:0 30px 90px rgba(0,0,0,.45);backdrop-filter:blur(18px);
      animation:cardIn .45s cubic-bezier(.2,.8,.2,1) both;
    }
    .auth-logo{box-shadow:0 8px 24px rgba(255,255,255,.08);transition:.25s}
    .auth-logo:hover{transform:translateY(-2px) rotate(-2deg)}
    .auth-in{background:rgba(8,9,10,.78);border-color:#272d34;transition:.2s}
    .auth-in:focus{border-color:#4a5562;box-shadow:0 0 0 3px rgba(96,165,250,.07);transform:translateY(-1px)}
    .auth-btn{box-shadow:0 8px 22px rgba(0,0,0,.2);transition:transform .2s,box-shadow .2s,background .2s!important}
    .auth-btn:hover:not(:disabled){transform:translateY(-1px);box-shadow:0 12px 28px rgba(0,0,0,.3)}

    /* Shell + sidebar */
    .shell{background:radial-gradient(circle at 75% -20%,rgba(96,165,250,.035),transparent 28%),var(--bg)}
    .sidebar{
      background:rgba(9,10,11,.92);border-right-color:rgba(255,255,255,.075);
      backdrop-filter:blur(16px);box-shadow:12px 0 40px rgba(0,0,0,.12);
    }
    .sb-brand{padding:20px 16px 16px;border-bottom-color:rgba(255,255,255,.065)}
    .sb-logo{box-shadow:0 6px 18px rgba(255,255,255,.07);transition:transform .2s}
    .sb-brand:hover .sb-logo{transform:scale(1.04)}
    .sb-lnk{color:#737b85;overflow:hidden}
    .sb-lnk:before{
      content:"";position:absolute;left:0;top:7px;bottom:7px;width:2px;border-radius:2px;
      background:#fff;opacity:0;transform:scaleY(.35);transition:.2s;
    }
    .sb-lnk:hover:not(:disabled){background:linear-gradient(90deg,#171a1e,#121417);color:#f0f2f4;transform:translateX(1px)}
    .sb-lnk.on{background:linear-gradient(90deg,#1b1f24,#15181c);color:#fff;box-shadow:inset 0 1px 0 rgba(255,255,255,.035)}
    .sb-lnk.on:before{opacity:1;transform:scaleY(1)}
    .sb-pill{background:#20252b;color:#9aa3ad;border:1px solid rgba(255,255,255,.035)}
    .sb-filter{border-top-color:rgba(255,255,255,.065)}
    .sb-reset,.sb-import-btn,.sb-clear-btn{transition:transform .18s,border-color .18s,color .18s,background .18s}
    .sb-reset:hover,.sb-import-btn:hover,.sb-clear-btn:hover{transform:translateY(-1px)}
    .sb-import-btn{background:linear-gradient(180deg,#181b1f,#131619)}
    .overlay{backdrop-filter:blur(3px)}

    /* Header */
    .bar{
      height:58px;padding:0 22px;background:rgba(9,10,11,.86);
      border-bottom-color:rgba(255,255,255,.07);backdrop-filter:blur(16px);position:relative;z-index:5;
    }
    .bar:after{
      content:"";position:absolute;left:0;right:0;bottom:-1px;height:1px;
      background:linear-gradient(90deg,transparent,rgba(96,165,250,.2),transparent);
    }
    .toast{animation:toastIn .28s cubic-bezier(.2,.8,.2,1) both;box-shadow:0 8px 24px rgba(0,0,0,.2)}

    /* Content + KPI */
    .page{padding:28px;background:radial-gradient(circle at 95% 0%,rgba(96,165,250,.025),transparent 26%)}
    .dash{gap:22px}
    .kpis{border-color:rgba(255,255,255,.075);box-shadow:var(--shadow)}
    .kpi{
      position:relative;background:linear-gradient(180deg,#111417,#0e1012);
      min-height:100px;overflow:hidden;transition:transform .22s,background .22s;
    }
    .kpi:after{
      content:"";position:absolute;width:90px;height:90px;right:-42px;top:-48px;border-radius:50%;
      background:rgba(255,255,255,.025);transition:transform .3s;
    }
    .kpi:hover{transform:translateY(-2px);background:linear-gradient(180deg,#15191d,#101316)}
    .kpi:hover:after{transform:scale(1.35)}
    .kn{font-size:26px;text-shadow:0 1px 16px rgba(255,255,255,.04)}
    .kn.g{text-shadow:0 0 24px rgba(74,222,128,.12)}
    .kn.r{text-shadow:0 0 24px rgba(248,113,113,.1)}

    /* Cards */
    .grid{gap:18px}
    .card{
      position:relative;background:linear-gradient(180deg,rgba(23,26,30,.96),rgba(17,20,23,.96));
      border-color:rgba(255,255,255,.075);border-radius:15px;
      box-shadow:0 10px 32px rgba(0,0,0,.16);
      transition:transform .22s,border-color .22s,box-shadow .22s;
      animation:cardIn .42s ease both;
    }
    .card:hover{transform:translateY(-2px);border-color:rgba(255,255,255,.12);box-shadow:0 16px 42px rgba(0,0,0,.23)}
    .card:nth-child(2){animation-delay:.035s}.card:nth-child(3){animation-delay:.07s}
    .card:nth-child(4){animation-delay:.105s}.card:nth-child(5){animation-delay:.14s}
    .card:nth-child(6){animation-delay:.175s}.card:nth-child(7){animation-delay:.21s}
    .ch{color:#b5bcc5;font-size:10px;letter-spacing:.8px}
    .ch:after{content:"";flex:1;height:1px;background:linear-gradient(90deg,rgba(255,255,255,.07),transparent)}

    /* Lists + category bars */
    .pl-row,.cat-row,.row-item{transition:background .18s,transform .18s}
    .pl-row{padding:6px 8px;border-radius:7px}
    .pl-row:hover,.cat-row:hover{background:#1a1e22;transform:translateX(2px)}
    .row-item{padding:8px 9px;margin:-3px -9px;border-radius:8px}
    .row-item:hover{background:#1a1e22;transform:translateX(2px)}
    .ri-name{color:#d7dce1}
    .cat-row{padding:5px 7px;margin:-2px -7px;border-radius:7px}
    .cat-bar-wrap{height:5px;background:#20242a;box-shadow:inset 0 1px 2px rgba(0,0,0,.25)}
    .cat-bar{box-shadow:0 0 12px rgba(96,165,250,.08)}

    /* Charts */
    .ngx-charts{filter:drop-shadow(0 5px 12px rgba(0,0,0,.12))}
    .ngx-charts .bar,.ngx-charts .cell{transition:opacity .18s,filter .18s}
    .ngx-charts .bar:hover,.ngx-charts .cell:hover{opacity:1!important;filter:brightness(1.18)}
    .ngx-charts .gridline-path,.ngx-charts .refline-path{stroke:#252b32!important;stroke-dasharray:3 5}
    .ngx-charts .tick line{stroke:#20262d!important}

    /* Transactions */
    .txn-ct{color:#87909a}
    .ctl{background:#121519;border-color:#292f36;min-height:34px}
    .ctl:hover{background:#171b20}
    .tbl-box{border-color:rgba(255,255,255,.075);box-shadow:0 14px 38px rgba(0,0,0,.18)}
    .tbl th{background:#111417;position:sticky;top:0;z-index:1}
    .tbl td{padding-top:12px;padding-bottom:12px;border-bottom-color:#181c21}
    .tbl tbody tr{transition:background .16s}
    .tbl tbody tr:hover td{background:#181c21}
    .tbl tbody tr:hover .td-m{color:#fff}
    .toggle-btn{transition:transform .18s,background .18s,color .18s}
    .toggle-btn:hover{transform:scale(1.08)}
    .toggle-btn.on{text-shadow:0 0 12px rgba(74,222,128,.28)}
    .load-more{background:linear-gradient(180deg,#15181c,#111417);transition:.18s}
    .load-more:hover{background:#1a1e23;color:#ddd}

    /* Received */
    .recv-strip{border-color:rgba(74,222,128,.12);box-shadow:0 10px 32px rgba(0,0,0,.14)}
    .recv-kpi{background:linear-gradient(180deg,#0e1b12,#0b1510);transition:.2s}
    .recv-kpi:hover{background:linear-gradient(180deg,#112216,#0c1811);transform:translateY(-1px)}
    .recv-val{text-shadow:0 0 22px rgba(74,222,128,.11)}

    /* AI */
    .ai-wrap{background:radial-gradient(circle at 70% 20%,rgba(96,165,250,.035),transparent 28%),var(--bg)}
    .ai-topbar{padding:12px 22px;background:rgba(9,10,11,.82);border-bottom-color:rgba(255,255,255,.07);backdrop-filter:blur(14px)}
    .ait-status.on{animation:livePulse 2.8s infinite}
    .ait-btn,.ait-sugg{transition:transform .18s,border-color .18s,background .18s,color .18s}
    .ait-btn:hover:not(:disabled),.ait-sugg:hover{transform:translateY(-1px)}
    .ait-sugg{background:#121519;border-color:#292f36}
    .ait-sugg:hover{background:#1a1e23;border-color:#3a424c;color:#e0e4e8}
    .chat-msgs{padding:28px;background:radial-gradient(circle at 50% 10%,rgba(96,165,250,.025),transparent 30%)}
    .chat-empty{padding:34px 42px;border:1px solid rgba(255,255,255,.055);border-radius:18px;background:rgba(18,20,23,.5);box-shadow:0 18px 55px rgba(0,0,0,.16)}
    .ce-t{color:#aeb6bf;font-size:18px}.ce-s{color:#58616b}
    .bub{box-shadow:0 8px 28px rgba(0,0,0,.12);animation:cardIn .24s ease both}
    .bu{background:linear-gradient(180deg,#1d2228,#181c21);border-color:#2c333b;color:#edf0f2}
    .bb{background:linear-gradient(180deg,#15191d,#111417);border-color:#272e35}
    .chat-bar{padding:15px 22px;background:rgba(9,10,11,.84);backdrop-filter:blur(14px)}
    .chat-in{min-height:42px;background:#101316;border-color:#292f36}
    .chat-send{width:42px;height:42px;background:linear-gradient(180deg,#1b2025,#15191d);transition:.18s}
    .chat-send:not(:disabled):hover{transform:translateY(-1px) scale(1.02);background:#222830;color:#fff}

    /* Admin */
    .adm-title{font-size:21px}.adm-sub{color:#69727d}
    .adm-refresh{background:linear-gradient(180deg,#1b2025,#15191d);border-color:#2b323a;transition:.18s}
    .adm-refresh:hover:not(:disabled){transform:translateY(-1px);background:#20262c;border-color:#3a424b}
    .adm-kpis{box-shadow:var(--shadow)}
    .adm-kpi{background:linear-gradient(180deg,#121518,#0f1113);transition:.2s}
    .adm-kpi:hover{transform:translateY(-2px);background:linear-gradient(180deg,#161a1e,#111417)}
    .adm-kpi-green{background:linear-gradient(180deg,#0d1a11,#0a140d)}
    .adm-card{background:linear-gradient(180deg,#121519,#0f1215);border-color:rgba(255,255,255,.075);box-shadow:0 14px 38px rgba(0,0,0,.18)}
    .adm-card-head,.adm-tbl th{background:#111417}
    .adm-tbl th{position:sticky;top:0;z-index:1}
    .adm-tbl tbody tr:hover td{background:#181c21}
    .adm-row-online td{background:rgba(10,30,17,.55)}
    .adm-del{transition:.18s}.adm-del:hover{transform:scale(1.08)}

    /* Inputs / focus */
    .din,.ctl,.pw-in,.cat-sel,.cat-custom-in,.chat-in{box-shadow:inset 0 1px 0 rgba(255,255,255,.02)}
    button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid rgba(96,165,250,.55);outline-offset:2px}

    /* CHAT FIX: keep the composer visible and let only the message list scroll */
    .main{min-height:0}
    .ai-wrap{min-height:0!important;height:auto;overflow:hidden!important}
    .ai-chat{min-height:0!important;height:auto;overflow:hidden}
    .chat-msgs{
      min-height:0!important;
      height:auto;
      flex:1 1 auto!important;
      overflow-y:auto!important;
      overflow-x:hidden!important;
      overscroll-behavior:contain;
      -webkit-overflow-scrolling:touch;
    }
    .chat-bar{
      position:relative;
      z-index:3;
      flex:0 0 auto!important;
      min-height:70px;
    }
    .chat-in{min-width:0}
    @media(max-width:768px){
      .ai-wrap,.ai-chat{min-height:0!important}
      .chat-msgs{min-height:0!important}
      .chat-bar{min-height:62px}
    }

    /* Responsive */
    @media(max-width:1000px){
      .page{padding:22px}.grid{gap:14px}.card{padding:17px}.kpi{padding:16px}.kn{font-size:23px}
    }
    @media(max-width:768px){
      .page{padding:16px}.bar{height:54px;padding:0 14px}
      .sidebar{width:270px;min-width:270px;left:-270px}.sidebar.open{left:0}
      .grid{grid-template-columns:1fr}.card.wide{grid-column:1}
      .kpis{grid-template-columns:repeat(2,1fr)}.kpi:last-child{grid-column:1/-1}
      .pie-wrap{flex-direction:column;align-items:stretch}
      .txn-bar{align-items:stretch}.txn-tools{width:100%}
      .ctl{flex:1;min-width:0}.ctl-search{min-width:140px}
      .tbl-box,.adm-card{overflow-x:auto}.tbl{min-width:760px}.adm-tbl{min-width:780px}
      .ai-topbar{padding:10px 14px}.ai-status-row{flex-wrap:wrap}
      .chat-msgs{padding:16px}.bub{max-width:88%}.chat-bar{padding:10px}
      .chat-empty{padding:24px 18px}.adm-title{font-size:18px}
    }
    @media(max-width:480px){
      .auth-box{padding:28px 22px;border-radius:18px}
      .kpis{grid-template-columns:1fr}.kpi:last-child{grid-column:auto}
      .empty-box h2{font-size:19px}.empty-acts{flex-direction:column}
      .btn-w,.btn-o{width:100%}.ai-suggestions{overflow-x:auto;flex-wrap:nowrap;padding-bottom:3px}
      .ait-sugg{flex:0 0 auto}
    }
    @media(prefers-reduced-motion:reduce){
      *,*:before,*:after{animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}
    }

  `]
})
export class AppComponent implements OnInit {
  @ViewChild('chatWin') chatWin!: ElementRef;

  // Auth
  currentUser: User | null = null;
  isAdmin = false;
  adminStats: any = null;
  adminUsers: any[] = [];
  adminLoading = false;
  showChangePw = false;
  pwCurrent = ''; pwNew = ''; pwConfirm = '';
  pwMsg = ''; pwOk = false;
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
  merchantData:        any[] = [];
  receivedSourceData:  any[] = [];
  monthlyComparedData: any[] = [];
  receivedCatData:     any[] = [];
  cardW = 420;
  wideW = 860;

  schemeCompare: any = { name:'compare', selectable:false, group:'Ordinal', domain:['#f87171','#4ade80'] };
  schemeGreen:   any = { name:'green',   selectable:false, group:'Ordinal', domain:['#4ade80','#34d399','#6ee7b7','#a7f3d0'] };
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
    : 'https://upi-analyzer-production-28c7.up.railway.app/api';

  constructor(private http: HttpClient) {}

  ngOnInit() {
    const saved = localStorage.getItem('upi_token');
    const user  = localStorage.getItem('upi_user');
    if (saved && user) {
      this.currentUser = JSON.parse(user);
      this.isAdmin = !!this.currentUser?.is_admin;
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
        this.isAdmin = !!res.user?.is_admin;
        localStorage.setItem('upi_user', JSON.stringify(res.user));
        // Clear previous user data
        this.transactions = []; this.filteredTxns = [];
        this.messages = []; this.analytics = null;
        this.totalStored = 0; this.tab = 'overview';
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
    this.isAdmin     = false;
    this.analytics   = null;
    this.totalStored = 0;
    this.transactions = [];
    this.filteredTxns = [];
    this.messages     = [];
    this.question     = '';
    this.tab          = 'overview';
    this.filterFrom   = '';
    this.filterTo     = '';
    this.pieData = []; this.monthlyData = []; this.merchantData = [];
    this.receivedSourceData = []; this.monthlyComparedData = [];
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
  go(t: string) {
    if (t !== 'admin') clearTimeout((this as any)._adminTimer);
    this.tab = t;
    this.sidebarOpen = false;
  }
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

  reloadAnalyticsOnly() {
    const p: any = {};
    if (this.filterFrom) p['date_from'] = this.filterFrom;
    if (this.filterTo)   p['date_to']   = this.filterTo + 'T23:59:59';
    this.http.get<any>(`${this.api}/analytics`, { params: p, headers: this.getHeaders() }).subscribe({
      next: (a) => { this.analytics = a; this.buildCharts(); },
      error: () => {}
    });
  }

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

    this.receivedSourceData = (a.top_received_sources||[]).map((r:any)=>({
      name: r.name?.length>18 ? r.name.substring(0,18)+'…' : r.name, value: r.received
    }));

    this.monthlyComparedData = [
      { name: 'Spent',    series: (a.monthly_combined||[]).map((m:any)=>({name:m.month, value:m.spent}))    },
      { name: 'Received', series: (a.monthly_combined||[]).map((m:any)=>({name:m.month, value:m.received})) },
    ].filter(s => s.series.some((p:any) => p.value > 0));

    this.receivedCatData = Object.entries(a.received_category||{})
      .map(([name,value])=>({name, value: value as number}))
      .filter(d=>d.value>0).sort((a,b)=>b.value-a.value);

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
        t.category        = r.category;        // update in place
        t.custom_category = r.custom_category;
        this.editingCat   = null;
        this.customCatInput = '';
        if (r.all_categories?.length) {
          this.allSystemCats = [...r.all_categories];
          this.allCats       = [...r.all_categories];
        }
        // Only reload charts, NOT the transaction list
        this.reloadAnalyticsOnly();
        this.showToast('Category set to "' + cat + '"');
      },
      error: () => this.showToast('Failed to update category', false)
    });
  }

  toggleIncluded(t: any) {
    const newVal = !t.included;
    t.included = newVal; // optimistic update immediately
    this.http.patch<any>(`${this.api}/transactions/${t.id}`,
      { included: newVal }, { headers: this.getHeaders() }).subscribe({
      next: (r) => {
        t.included = r.included; // confirm from server
        // Only reload analytics charts, NOT transactions list
        this.reloadAnalyticsOnly();
      },
      error: () => {
        t.included = !newVal; // revert on error
        this.showToast('Failed to update', false);
      }
    });
  }

    changePassword() {
    if (this.pwNew !== this.pwConfirm) {
      this.pwMsg = 'Passwords do not match'; this.pwOk = false; return;
    }
    if (this.pwNew.length < 6) {
      this.pwMsg = 'Min 6 characters'; this.pwOk = false; return;
    }
    this.http.post<any>(`${this.api}/auth/change-password`,
      { current_password: this.pwCurrent, new_password: this.pwNew },
      { headers: this.getHeaders() }).subscribe({
      next: () => {
        this.pwMsg = 'Password changed!'; this.pwOk = true;
        this.pwCurrent = ''; this.pwNew = ''; this.pwConfirm = '';
        setTimeout(() => { this.showChangePw = false; this.pwMsg = ''; }, 2000);
      },
      error: (e) => { this.pwMsg = e.error?.detail || 'Failed'; this.pwOk = false; }
    });
  }

  deleteUser(u: any) {
    if (!confirm(`Delete ${u.name} (${u.email}) and ALL their transactions? Cannot be undone.`)) return;
    this.http.delete(`${this.api}/admin/users/${u.id}`, { headers: this.getHeaders() }).subscribe({
      next: () => {
        this.adminUsers = this.adminUsers.filter(x => x.id !== u.id);
        this.showToast(`${u.name} deleted`);
        this.loadAdminData();
      },
      error: (e) => this.showToast(e.error?.detail || 'Delete failed', false)
    });
  }

  loadAdminData() {
    this.adminLoading = true;
    // auto-refresh every 30s when on admin tab
    if (this.tab === 'admin') {
      clearTimeout((this as any)._adminTimer);
      (this as any)._adminTimer = setTimeout(() => this.loadAdminData(), 30000);
    }
    this.http.get<any>(`${this.api}/admin/stats`, { headers: this.getHeaders() }).subscribe({
      next: (s) => { this.adminStats = s; },
      error: () => {}
    });
    this.http.get<any>(`${this.api}/admin/users`, { headers: this.getHeaders() }).subscribe({
      next: (r) => { this.adminUsers = r.users || []; this.adminLoading = false; },
      error: () => { this.adminLoading = false; }
    });
  }

  private scroll(){
    setTimeout(()=>{
      const el = this.chatWin?.nativeElement;
      if(el) el.scrollTo({top:el.scrollHeight,behavior:'smooth'});
    },50);
  }
}
