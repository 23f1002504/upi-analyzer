import sys, os, traceback
 
print("Starting UPI Analyzer...")
print(f"Python: {sys.version}")
print(f"DATABASE_URL set: {'DATABASE_URL' in os.environ}")
print(f"SECRET_KEY set: {'SECRET_KEY' in os.environ}")
 
# Load .env if present
from pathlib import Path
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())
 
try:
    print("Importing app...")
    from app.main import app
    print("App imported successfully")
except Exception as e:
    print(f"IMPORT ERROR: {e}")
    traceback.print_exc()
    sys.exit(1)
 
try:
    import uvicorn
    port = int(os.environ.get('PORT', 10000))
    print(f"Starting uvicorn on port {port}...")
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)
except Exception as e:
    print(f"STARTUP ERROR: {e}")
    traceback.print_exc()
    sys.exit(1)
 