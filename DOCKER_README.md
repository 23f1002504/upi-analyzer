# UPI Analyzer — Docker Setup

## Requirements
- Docker Desktop installed (https://www.docker.com/products/docker-desktop)

## File placement

```
E:\ProjectR\
├── backend\
│   ├── app\               ← your backend code
│   ├── run.py
│   ├── requirements.txt
│   └── Dockerfile         ← copy Dockerfile.backend here, rename to Dockerfile
│
├── frontend\
│   ├── src\               ← your frontend code
│   ├── package.json
│   ├── angular.json
│   ├── nginx.conf         ← copy nginx.conf here
│   └── Dockerfile         ← copy Dockerfile.frontend here, rename to Dockerfile
│
└── docker-compose.yml     ← place in E:\ProjectR\
```

## Steps

### 1. Copy files
- `Dockerfile.backend`  → `E:\ProjectR\backend\Dockerfile`
- `Dockerfile.frontend` → `E:\ProjectR\frontend\Dockerfile`
- `nginx.conf`          → `E:\ProjectR\frontend\nginx.conf`
- `docker-compose.yml`  → `E:\ProjectR\docker-compose.yml`

### 2. Update Angular build output path
In `E:\ProjectR\frontend\angular.json`, find `"outputPath"` and set:
```json
"outputPath": "dist/frontend"
```

### 3. Build and start
```cmd
cd E:\ProjectR
docker compose up --build
```
First run downloads ~3GB (Ollama, Python, Node). Subsequent starts are fast.

### 4. Pull Ollama model (first time only)
```cmd
docker exec -it upi-ollama ollama pull llama3
```
Or lighter model: `ollama pull phi3`

### 5. Access
- App: http://localhost
- API: http://localhost:8000
- API docs: http://localhost:8000/docs

## Commands
```cmd
docker compose up -d          # start in background
docker compose down           # stop
docker compose logs backend   # view backend logs
docker compose build          # rebuild after code changes
```
