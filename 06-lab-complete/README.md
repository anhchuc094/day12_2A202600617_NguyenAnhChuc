# Lab 12 — Complete Production Agent

Kết hợp TẤT CẢ những gì đã học trong 1 project hoàn chỉnh.

## Checklist Deliverable

- [x] Dockerfile (multi-stage, < 500 MB)
- [x] docker-compose.yml (3 agents + redis + nginx)
- [x] .dockerignore
- [x] Health check endpoint (`GET /health`)
- [x] Readiness endpoint (`GET /ready`)
- [x] API Key authentication
- [x] Rate limiting
- [x] Cost guard
- [x] Config từ environment variables
- [x] Structured logging
- [x] Graceful shutdown
- [x] Public URL ready (Railway / Render config)

---

## Cấu Trúc

```
06-lab-complete/
├── app/
│   ├── main.py         # Entry point — kết hợp tất cả
│   ├── config.py       # 12-factor config
│   ├── auth.py         # API key authentication
│   ├── rate_limiter.py # Redis sliding-window rate limit
│   ├── cost_guard.py   # Redis monthly budget guard
│   └── redis_client.py # Conversation history + Redis connection
├── nginx/
│   └── nginx.conf      # Load balancer cho 3 agent instances
├── utils/
│   └── mock_llm.py     # LLM giả lập để tập trung vào deployment
├── Dockerfile          # Multi-stage, production-ready
├── docker-compose.yml  # Full stack
├── railway.toml        # Deploy Railway
├── render.yaml         # Deploy Render
├── .env.example        # Template
├── .dockerignore
└── requirements.txt
```

---

## Làm Lab Trên Windows/PowerShell

### Bước 1: Kiểm tra checklist

Đứng tại thư mục gốc repository:

```powershell
cd 06-lab-complete
python check_production_ready.py
```

Mục tiêu là hiểu từng check trước khi chạy ứng dụng.

### Bước 2: Tạo cấu hình local

Docker Compose đọc file `.env.local`, không phải `.env`:

```powershell
Copy-Item .env.example .env.local
```

Mở `.env.local` và thay ít nhất:

```env
AGENT_API_KEY=my-local-secret-key
APP_DEBUG=false
```

### Bước 3: Build và chạy full stack

Đảm bảo Docker Desktop đang chạy, sau đó:

```powershell
docker compose up --build
```

Compose khởi động ba loại service:

- `agent`: 3 FastAPI replicas trong Docker network
- `redis`: Redis nội bộ tại `redis:6379`
- `nginx`: public load balancer tại `http://localhost`

### Bước 4: Test health và readiness

Mở terminal PowerShell thứ hai:

```powershell
Invoke-RestMethod http://localhost/health
Invoke-RestMethod http://localhost/ready
```

### Bước 5: Test authentication và `/ask`

```powershell
$headers = @{ "X-API-Key" = "my-local-secret-key" }
$body = @{
  question = "What is deployment?"
  user_id = "user1"
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri http://localhost/ask `
  -Method Post `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

Thử bỏ `$headers` để quan sát lỗi `401 Unauthorized`.

### Bước 6: Test rate limit

```powershell
1..11 | ForEach-Object {
  try {
    Invoke-RestMethod -Uri http://localhost/ask -Method Post `
      -Headers $headers -ContentType "application/json" -Body $body
  } catch {
    $_.Exception.Response.StatusCode.value__
  }
}
```

Request vượt giới hạn trong một phút sẽ nhận `429`.

### Bước 7: Xem metrics

```powershell
Invoke-RestMethod http://localhost/metrics -Headers $headers
```

### Bước 8: Quan sát scale và stateless

Gọi nhiều lần và quan sát `instance_id` thay đổi:

```powershell
1..9 | ForEach-Object {
  (Invoke-RestMethod http://localhost/health).instance_id
}
```

Conversation history nằm trong Redis, nên `history_items` vẫn tăng dù hai request đi qua hai instance khác nhau.

### Bước 9: Dừng lab

```powershell
docker compose down
```

## Lệnh Bash Tương Đương

```bash
# 1. Setup
cp .env.example .env.local

# 2. Chạy với Docker Compose
docker compose up

# 3. Test
curl http://localhost/health

# 4. Lấy API key từ .env, test endpoint
API_KEY=$(grep AGENT_API_KEY .env.local | cut -d= -f2)
curl -H "X-API-Key: $API_KEY" \
     -X POST http://localhost/ask \
     -H "Content-Type: application/json" \
     -d '{"question": "What is deployment?", "user_id": "user1"}'
```

---

## Deploy Railway (< 5 phút)

```bash
# Cài Railway CLI
npm i -g @railway/cli

# Login và deploy
railway login
railway init
railway variables set AGENT_API_KEY=your-secret-key
railway variables set REDIS_URL=redis://your-railway-redis-url
railway variables set ENVIRONMENT=production
railway up

# Nhận public URL!
railway domain
```

---

## Deploy Render

1. Push repo lên GitHub
2. Render Dashboard → New → Blueprint
3. Chọn Blueprint path `06-lab-complete/render.yaml`
4. Blueprint tạo web service và Render Key Value, đồng thời tự sinh `AGENT_API_KEY`
5. Deploy và lấy public URL

---

## Kiểm Tra Production Readiness

```bash
python check_production_ready.py

# Khi stack đang chạy
python check_production_ready.py --runtime --url http://localhost \
  --api-key my-local-secret-key
```

Script này kiểm tra tất cả items trong checklist và báo cáo những gì còn thiếu.
