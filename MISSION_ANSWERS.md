# Day 12 Lab - Mission Answers

> Student name: **Nguyễn Anh Chức**  
> Student ID: **2A202600617**  
> Date: 12/06/2026

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found

Các anti-pattern trong `01-localhost-vs-production/develop/app.py`:

1. Hardcode `OPENAI_API_KEY` trong source code, dễ làm lộ secret khi push GitHub.
2. Hardcode `DATABASE_URL`, bao gồm cả username và password database.
3. Không có config management tập trung; `DEBUG` và `MAX_TOKENS` nằm trực tiếp trong code.
4. Dùng `print()` thay cho structured logging.
5. Ghi API key vào log, làm secret xuất hiện trong terminal hoặc hệ thống log.
6. Không có endpoint `/health` để cloud platform kiểm tra process.
7. Bind server vào `localhost`, nên không truy cập được từ ngoài container.
8. Hardcode port `8000`, không đọc biến môi trường `PORT` do cloud cấp.
9. Luôn bật `reload=True`, không phù hợp production.
10. Không có readiness check để biết ứng dụng đã sẵn sàng nhận traffic hay chưa.
11. Không có graceful shutdown và cleanup khi nhận `SIGTERM`.
12. Không validate input và không xử lý lỗi từ LLM provider.

### Exercise 1.2: Basic version result

Basic version có thể chạy và trả lời request trên máy local, nhưng chưa production-ready vì phụ thuộc cấu hình cứng, chỉ lắng nghe trên localhost và thiếu health check, logging, validation, bảo mật và graceful shutdown.

### Exercise 1.3: Comparison table

| Feature | Develop | Production | Why Important? |
|---|---|---|---|
| Config | Hardcode trong `app.py` | Đọc từ environment qua `config.py` | Có thể đổi cấu hình giữa dev, staging và production mà không sửa code |
| Secrets | API key và database URL nằm trong source | Secret lấy từ environment | Tránh lộ secret trong GitHub và image |
| Logging | Dùng `print()`, có log secret | Structured JSON logging, không log secret | Dễ tìm kiếm, giám sát và đưa vào log aggregator |
| Health check | Không có | Có `GET /health` | Cloud biết process còn sống để restart khi cần |
| Readiness | Không có | Có `GET /ready`, có thể trả `503` | Chỉ route traffic đến instance đã sẵn sàng |
| Host | `localhost` | `0.0.0.0` | Cho phép truy cập ứng dụng từ ngoài container |
| Port | Hardcode `8000` | Đọc biến `PORT` | Tương thích Railway, Render và các cloud platform |
| Reload | Luôn bật | Chỉ bật khi debug | Tránh process phụ và reload ngoài ý muốn trong production |
| CORS | Không cấu hình | Đọc danh sách origin từ environment | Kiểm soát frontend được phép gọi API |
| Input validation | Gần như không có | Kiểm tra trường `question` | Trả lỗi rõ ràng thay vì để ứng dụng crash |
| Error handling | Không xử lý lỗi provider | Chuyển lỗi provider thành HTTP `502` | Client nhận status code có ý nghĩa |
| Shutdown | Không có cleanup | Dùng FastAPI lifespan và xử lý `SIGTERM` | Hoàn thành request đang chạy trước khi tắt |
| Monitoring | Không có | Có `/health`, `/ready`, `/metrics` | Hỗ trợ vận hành và quan sát hệ thống |

### Checkpoint 1

- Hardcode secret nguy hiểm vì secret có thể tồn tại trong source, image và lịch sử Git.
- Environment variables tách cấu hình khỏi code theo nguyên tắc 12-Factor App.
- Liveness cho biết process còn sống; readiness cho biết app có thể nhận traffic.
- Graceful shutdown cho phép server ngừng nhận request mới, hoàn tất request hiện tại và đóng connection trước khi thoát.

## Part 2: Docker

### Exercise 2.1: Dockerfile questions

1. **Base image:** `python:3.11`.
2. **Working directory:** `/app`.
3. **Tại sao copy `requirements.txt` trước source code:** Docker cache layer cài dependency. Khi chỉ sửa code mà requirements không đổi, Docker không cần cài lại toàn bộ package.
4. **CMD và ENTRYPOINT:** `ENTRYPOINT` xác định executable chính và khó bị thay thế hơn; `CMD` cung cấp command hoặc argument mặc định và có thể override dễ dàng khi chạy `docker run`.

### Exercise 2.2: Build and run

Lệnh thực hiện từ repository root:

```powershell
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run --rm -p 8000:8000 my-agent:develop
Invoke-RestMethod http://localhost:8000/health
```

Kết quả mong đợi của `/health` là status `ok`, có uptime và `container: true`.

### Exercise 2.3: Multi-stage build

- **Stage 1 - builder:** dùng `python:3.11-slim`, cài compiler/build dependencies và Python packages.
- **Stage 2 - runtime:** chỉ lấy Python packages đã cài và source cần chạy; không mang theo compiler và build cache.
- Image nhỏ và an toàn hơn vì runtime không chứa công cụ build không cần thiết.
- Runtime chạy bằng non-root user `appuser` và có Docker `HEALTHCHECK`.

#### Image size comparison

| Image | Measured size |
|---|---:|
| `my-agent:develop` (single-stage) | 1.66 GB |
| `my-agent:advanced` (multi-stage) | 236 MB |
| Difference | Giảm khoảng 85.8% (nhỏ hơn khoảng 1.42 GB) |

Lệnh đo:

```powershell
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
docker images my-agent:develop my-agent:advanced
```

### Exercise 2.4: Docker Compose stack

Stack production của Part 2 gồm:

- `nginx`: public reverse proxy/load balancer.
- `agent`: FastAPI service, có thể chạy nhiều replica.
- `redis`: cache/session/rate-limit storage.
- `qdrant`: vector database cho RAG.

Luồng giao tiếp:

```text
Client -> Nginx -> Agent replicas
                    |-> Redis
                    `-> Qdrant
```

Các service liên lạc bằng service name trên Docker network, ví dụ `redis:6379` và `qdrant:6333`. Chỉ Nginx cần publish port ra host.

### Checkpoint 2

- Dockerfile tạo môi trường chạy tái lập được.
- Multi-stage build tách công cụ build khỏi runtime.
- Docker Compose mô tả và khởi động toàn bộ stack.
- Debug container bằng `docker compose logs`, `docker ps` và `docker exec -it <container> /bin/sh`.

## Part 3: Cloud Deployment

### Exercise 3.1: Railway deployment

- Platform: **Railway**
- Public URL: https://responsible-courage-production-b18b.up.railway.app
- Health: https://responsible-courage-production-b18b.up.railway.app/health
- Readiness: https://responsible-courage-production-b18b.up.railway.app/ready
- Deployment environment: `production`
- Redis: Railway Redis service, kết nối qua private network.
- Screenshot: **TODO - thêm `screenshots/railway-dashboard.png` và chèn link tại đây**.

Kết quả kiểm thử ngày 12/06/2026:

```json
{"status":"ok","version":"1.0.0","environment":"production","instance_id":"6e3ef6fe1148"}
```

```json
{"ready":true,"redis":"ok","instance_id":"6e3ef6fe1148"}
```

Các biến production đã cấu hình gồm `ENVIRONMENT`, `AGENT_API_KEY`, `LLM_MODEL`, `APP_DEBUG` và `REDIS_URL`. Giá trị secret không được ghi vào báo cáo hoặc commit lên Git.

### Exercise 3.2: Render vs Railway configuration

| Railway (`railway.toml`) | Render (`render.yaml`) |
|---|---|
| Dùng cú pháp TOML | Dùng cú pháp YAML |
| Tập trung vào build/deploy của một service | Blueprint có thể khai báo nhiều resource |
| Railway tự inject `PORT` | Render cũng inject `PORT` cho web service |
| Variables thường đặt bằng Dashboard/CLI/reference | `envVars` có thể khai báo trực tiếp, generate hoặc yêu cầu nhập trên Dashboard |
| Có health check và restart policy | Có health check, region, plan và auto-deploy |
| Redis thường được thêm thành service riêng | Blueprint có thể khai báo Redis cùng web service |

### Exercise 3.3: GCP Cloud Run (optional)

`cloudbuild.yaml` mô tả pipeline build/push container image. `service.yaml` mô tả Cloud Run service, container image, port, resource, scaling và environment variables. Cloud Run phù hợp production hơn khi cần managed autoscaling, nhưng cấu hình và tài khoản GCP phức tạp hơn Railway.

### Checkpoint 3

- Đã deploy thành công lên Railway.
- Public URL đang hoạt động.
- Biến môi trường và Redis reference được cấu hình trên cloud.
- Có thể xem build/deployment logs trên Railway Dashboard hoặc bằng `railway logs`.

## Part 4: API Security

### Exercise 4.1: API key authentication

- API key được lấy từ biến môi trường `AGENT_API_KEY`.
- Client gửi key trong header `X-API-Key`.
- Dependency `verify_api_key` chạy trước endpoint `/ask`.
- Thiếu hoặc sai key trả `401` trong final project (`develop` demo tách thiếu key `401`, sai key `403`).
- Rotate key bằng cách đổi `AGENT_API_KEY` trên Railway rồi redeploy, không cần sửa source code.
- Final project dùng `secrets.compare_digest` để so sánh key an toàn hơn phép so sánh chuỗi thông thường.

Kết quả thực tế khi không gửi API key:

```text
HTTP 401
{"detail":"Invalid or missing API key. Include X-API-Key header."}
```

Kết quả request hợp lệ:

```json
{
  "question": "What is cloud deployment?",
  "answer": "Deployment dua ung dung len server de nguoi dung co the truy cap.",
  "user_id": "report-user-20260612",
  "model": "mock",
  "history_items": 1,
  "monthly_cost_usd": 0.0000168
}
```

### Exercise 4.2: JWT authentication

Flow JWT trong `04-api-gateway/production`:

1. Client gửi username/password tới `POST /auth/token`.
2. `authenticate_user` kiểm tra thông tin đăng nhập.
3. `create_token` tạo JWT ký bằng `HS256`, chứa subject, role, thời điểm tạo và expiry 60 phút.
4. Client gửi `Authorization: Bearer <token>` khi gọi endpoint bảo vệ.
5. `verify_token` decode chữ ký, kiểm tra expiry và trả user/role cho endpoint.
6. Token hết hạn trả `401`; token không hợp lệ trả `403`.

JWT là stateless authentication vì server có thể xác minh chữ ký mà không cần lưu session token trong memory. Trong production phải đặt `JWT_SECRET` mạnh qua environment variable.

### Exercise 4.3: Rate limiting

- Part 4 production dùng **sliding window** với deque timestamps trong memory.
- User thường: 10 request/60 giây.
- Admin: 100 request/60 giây; đây là mức giới hạn riêng theo role, không phải bỏ hoàn toàn rate limit.
- Khi vượt giới hạn, API trả `429 Too Many Requests` và `Retry-After`.
- Final project nâng cấp thành Redis-backed sliding window dùng sorted set và Lua script atomic, nên dùng được khi có nhiều instance.

Kết quả production Railway với một user riêng:

```text
Request status: 200,200,200,200,200,200,200,200,200,429
```

Request thứ 11 tính cả request hợp lệ trước đó đã bị chặn đúng giới hạn 10 request/phút.

### Exercise 4.4: Cost guard

Final project triển khai monthly cost guard trong Redis:

1. Ước lượng chi phí từ input/output token.
2. Tạo key theo user và tháng: `budget:<user_id>:<YYYY-MM>`.
3. Lua script đọc tổng hiện tại và kiểm tra `current + estimated_cost` với budget.
4. Nếu vượt budget, trả HTTP `402 Monthly budget exhausted`.
5. Nếu còn budget, dùng `INCRBYFLOAT` để cộng chi phí.
6. Đặt TTL 32 ngày để key cũ tự hết hạn.
7. Lua script làm check-and-increment atomic, tránh race condition giữa nhiều request/instance.

Budget cấu hình hiện tại là `$10/user/month` qua `MONTHLY_BUDGET_USD`.

### Checkpoint 4

- API production được bảo vệ bằng API key.
- Đã hiểu flow JWT và role-based access của Part 4.
- Rate limiting trả `429` đúng khi vượt 10 request/phút.
- Cost guard và rate-limit state được lưu trong Redis để hỗ trợ scale.

## Part 5: Scaling & Reliability

### Exercise 5.1: Health and readiness

- `GET /health` là liveness probe: trả `200` nếu process FastAPI còn chạy.
- `GET /ready` là readiness probe: gọi `PING` tới Redis; trả `503` nếu storage không khả dụng.
- Tách hai probe giúp tránh restart process chỉ vì dependency tạm thời lỗi, đồng thời ngăn load balancer gửi traffic tới instance chưa sẵn sàng.

Kết quả Railway:

```json
{"status":"ok","environment":"production"}
```

```json
{"ready":true,"redis":"ok"}
```

### Exercise 5.2: Graceful shutdown

Ứng dụng dùng FastAPI lifespan:

1. Startup kiểm tra Redis và đặt readiness state.
2. Uvicorn nhận `SIGTERM`, ngừng nhận traffic mới và chờ in-flight request theo timeout graceful shutdown.
3. Lifespan shutdown đặt app thành not-ready và ghi structured shutdown log.
4. Container có `drainingSeconds = 30` trên Railway để có thời gian drain request.

Điều này tránh dừng process đột ngột giữa request và hỗ trợ rolling deployment.

### Exercise 5.3: Stateless design

Conversation history không lưu trong dictionary của từng process. Final project lưu trong Redis list:

- Key: `history:<user_id>`.
- `LPUSH` thêm question/answer.
- `LTRIM` giữ giới hạn lịch sử.
- `EXPIRE` xóa lịch sử sau 30 ngày.

Vì mọi instance cùng dùng Redis, request tiếp theo vẫn đọc được history dù load balancer chuyển sang instance khác.

### Exercise 5.4: Load balancing

Local full stack có ba agent replica và Nginx:

```text
Client -> Nginx -> agent replica 1
                -> agent replica 2
                -> agent replica 3
                         |
                         `-> Redis shared state
```

Nginx dùng Docker DNS name `agent:8000`, proxy request tới agent cluster và retry instance khác khi gặp error/timeout/`503`. Response có instance identifier để quan sát request được phục vụ bởi instance nào.

Lệnh local:

```powershell
docker compose up --build --scale agent=3
1..9 | ForEach-Object { (Invoke-RestMethod http://localhost/health).instance_id }
docker compose logs agent
```

### Exercise 5.5: Stateless test

`test_stateless.py` thực hiện:

1. Tạo session mới.
2. Gửi năm câu hỏi liên tiếp với cùng session ID.
3. Ghi nhận `served_by` để thấy request có thể qua các instance khác nhau.
4. Đọc lại toàn bộ conversation history.
5. Xác nhận history còn nguyên vì được lưu trong Redis.

Trên Railway hiện dùng một app replica, nhưng storage đã được xác nhận hoạt động qua `/ready` và request `/ask` đã tạo `history_items: 1`. Thiết kế Redis cho phép tăng replica mà không thay đổi cách lưu state.

### Production metrics result

Kết quả `GET /metrics` trong lúc kiểm thử:

```json
{
  "total_requests": 28,
  "error_count": 0,
  "monthly_budget_usd": 10.0,
  "instance_id": "6e3ef6fe1148"
}
```

### Checkpoint 5

- Health và readiness đã hoạt động trên public deployment.
- Graceful shutdown được xử lý bởi Uvicorn, lifespan và Railway draining.
- Conversation state nằm trong Redis, không phụ thuộc memory của instance.
- Local Compose/Nginx hỗ trợ ba agent replica.
- Public deployment đã xác nhận Redis connection và conversation history.

## Items Requiring Student Action

1. Điền họ tên và mã sinh viên ở đầu file.
2. Tạo thư mục `screenshots/` và thêm ảnh Railway dashboard, trang web đang chạy, kết quả `/ready` và test `/ask`.
3. Kiểm tra không có `.env.local`, API key hoặc Redis password trong Git trước khi commit.
