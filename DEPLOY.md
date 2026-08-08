# Deployment Guide — Railway + Vercel

## Architecture
- Frontend → Vercel (free, CDN, always on)
- Backend  → Railway (free $5 credit/mo)
- AI Chat  → Claude API (Anthropic, zero data retention)
- Database → SQLite on Railway persistent volume

---

## Step 1 — Get API Keys

### Claude API (for AI chat)
1. Go to https://console.anthropic.com
2. Sign up → API Keys → Create Key
3. Copy: sk-ant-xxxxxxxxxxxx
4. Free $5 credit on signup (~500k tokens)

---

## Step 2 — Push to GitHub

Run in E:\ProjectR:
```
git init
copy .gitignore_root .gitignore
git add .
git commit -m "UPI Analyzer"
```

Create repo at github.com/new → name: upi-analyzer → Public or Private

```
git remote add origin https://github.com/YOUR_USERNAME/upi-analyzer.git
git branch -M main
git push -u origin main
```

---

## Step 3 — Deploy Backend on Railway

1. Go to https://railway.app → Login with GitHub
2. New Project → Deploy from GitHub repo → select upi-analyzer
3. Set Root Directory: backend
4. Add environment variables (Settings → Variables):

```
ANTHROPIC_API_KEY = sk-ant-your-key-here
SECRET_KEY        = any-long-random-string-32-chars
DATABASE_URL      = sqlite:///./data/upi.db
CLAUDE_MODEL      = claude-haiku-4-5
```

5. Add Volume (Settings → Volumes):
   - Mount path: /app/data
   - This persists your SQLite database

6. Railway auto-deploys. Copy your URL:
   https://upi-analyzer-xxxx.up.railway.app

---

## Step 4 — Update Frontend API URL

Edit frontend/src/environments/environment.prod.ts:
```typescript
export const environment = {
  production: true,
  apiUrl: 'https://upi-analyzer-xxxx.up.railway.app/api'
};
```

Also update app.component.ts — change:
```typescript
private api = 'http://localhost:8000/api';
```
to:
```typescript
private api = environment.production
  ? 'https://YOUR-RAILWAY-URL.up.railway.app/api'
  : 'http://localhost:8000/api';
```

---

## Step 5 — Deploy Frontend on Vercel

1. Go to https://vercel.com → Login with GitHub
2. New Project → Import upi-analyzer repo
3. Set:
   - Framework: Angular
   - Root Directory: frontend
   - Build Command: ng build --configuration production
   - Output Directory: dist/frontend/browser
4. Deploy

Your app is live at: https://upi-analyzer-xxxx.vercel.app

---

## Cost Summary
| Service | Cost |
|---------|------|
| Vercel  | Free forever |
| Railway | Free ($5 credit/mo) |
| Claude API | ~$0.25 per 1M tokens (haiku) |
| Total   | ~$0/mo for personal use |

---

## Local Dev (still works)
```
cd backend && venv\Scripts\activate && python run.py
cd frontend && ng serve
```
Ollama + deepseek-r1:8b used locally, Claude API used in production.
