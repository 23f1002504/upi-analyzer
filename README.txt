UPI Analyzer - full clean update
================================
Copy these into your project (same paths), replacing what is there:

  backend/requirements.txt
  backend/app/main.py  auth.py  database.py  rag_service.py  seed_admin.py
  backend/app/analytics.py  csv_parsers.py (NEW)  models.py
  frontend/src/app/app.component.ts  app.component.html (NEW)  app.component.css (NEW)

Leave pdf_parser.py, run.py, Dockerfile, app.config.ts as they are.

Then:  git add .  &&  git commit -m "clean rewrite"  &&  git push

Render env vars
  GROQ_API_KEY   your key (quotes/spaces are tolerated)
  GROQ_MODEL     DELETE this variable. The server now picks a live model by itself.
  RAG_VECTOR     optional. Set to 0 to force keyword search on a very small server.
  ADMIN_RESET_PASSWORD=1  only if you ever need to reset the admin password back to ADMIN_PASSWORD.

If Vercel reports a component-style budget error, raise anyComponentStyle
maximumError to "100kb" in frontend/angular.json.

The backend URL lives on line 11 of app.component.ts (const API).
