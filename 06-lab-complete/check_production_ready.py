"""Static and runtime production-readiness checks for the final lab."""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid


BASE = os.path.dirname(__file__)


def read(path: str) -> str:
    with open(os.path.join(BASE, path), encoding="utf-8") as file:
        return file.read()


def report(name: str, passed: bool, detail: str = "") -> bool:
    icon = "PASS" if passed else "FAIL"
    suffix = f" - {detail}" if detail else ""
    print(f"  [{icon}] {name}{suffix}")
    return passed


def request(
    base_url: str,
    path: str,
    method: str = "GET",
    api_key: str | None = None,
    body: dict | None = None,
) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def static_checks() -> list[bool]:
    print("\nStatic checks")
    results: list[bool] = []
    required = [
        "app/__init__.py",
        "app/main.py",
        "app/config.py",
        "app/auth.py",
        "app/rate_limiter.py",
        "app/cost_guard.py",
        "app/redis_client.py",
        "utils/mock_llm.py",
        "Dockerfile",
        "docker-compose.yml",
        "nginx/nginx.conf",
        ".env.example",
        ".dockerignore",
        "requirements.txt",
        "railway.toml",
        "render.yaml",
    ]
    for path in required:
        results.append(report(f"{path} exists", os.path.exists(os.path.join(BASE, path))))

    main = read("app/main.py")
    config = read("app/config.py")
    rate = read("app/rate_limiter.py")
    cost = read("app/cost_guard.py")
    redis_client = read("app/redis_client.py")
    dockerfile = read("Dockerfile")
    compose = read("docker-compose.yml")
    dockerignore = read(".dockerignore")

    checks = [
        ("Environment-based config", "BaseSettings" in config and "redis_url" in config),
        ("Health endpoint", '"/health"' in main),
        ("Readiness checks Redis", '"/ready"' in main and "ping_redis" in main),
        ("API-key authentication", "verify_api_key" in main),
        ("Redis sliding-window rate limit", "ZREMRANGEBYSCORE" in rate),
        ("Redis monthly cost guard", "INCRBYFLOAT" in cost and "monthly_budget" in cost),
        ("Conversation history in Redis", "lpush" in redis_client and "lrange" in redis_client),
        ("Structured JSON logging", "JsonFormatter" in main and "json.dumps" in main),
        ("SIGTERM/graceful shutdown", "SIGTERM" in main and "lifespan" in main),
        ("Multi-stage Docker build", "AS builder" in dockerfile and "AS runtime" in dockerfile),
        ("Non-root container", "USER agent" in dockerfile),
        ("Docker health check", "HEALTHCHECK" in dockerfile),
        ("Three agent replicas", "replicas: 3" in compose),
        ("Redis service", "redis:" in compose and "redis-data" in compose),
        ("Nginx load balancer", "nginx:" in compose and "nginx/nginx.conf" in compose),
        ("Secrets excluded from image", ".env" in dockerignore),
    ]
    results.extend(report(name, passed) for name, passed in checks)
    return results


def runtime_checks(base_url: str, api_key: str) -> list[bool]:
    print(f"\nRuntime checks against {base_url}")
    results: list[bool] = []

    status, health = request(base_url, "/health")
    results.append(report("GET /health returns 200", status == 200, str(health)))

    status, ready = request(base_url, "/ready")
    results.append(report("GET /ready returns 200", status == 200, str(ready)))

    user_id = f"check-{uuid.uuid4().hex[:8]}"
    body = {"question": "What is deployment?", "user_id": user_id}
    status, _ = request(base_url, "/ask", method="POST", body=body)
    results.append(report("POST /ask requires authentication", status == 401))

    status, answer = request(base_url, "/ask", method="POST", api_key=api_key, body=body)
    results.append(
        report(
            "Authenticated POST /ask returns 200",
            status == 200 and answer.get("user_id") == user_id,
            str(answer),
        )
    )

    statuses = []
    for index in range(10):
        status, _ = request(
            base_url,
            "/ask",
            method="POST",
            api_key=api_key,
            body={"question": f"rate test {index}", "user_id": user_id},
        )
        statuses.append(status)
    results.append(report("Rate limit returns 429", 429 in statuses, str(statuses)))

    status, metrics = request(base_url, "/metrics", api_key=api_key)
    results.append(report("Protected metrics returns 200", status == 200, str(metrics)))

    history_user = f"history-{uuid.uuid4().hex[:8]}"
    history_results = []
    for question in ("first message", "second message"):
        status, response = request(
            base_url,
            "/ask",
            method="POST",
            api_key=api_key,
            body={"question": question, "user_id": history_user},
        )
        history_results.append((status, response))
    history_passed = (
        history_results[0][0] == 200
        and history_results[1][0] == 200
        and history_results[0][1].get("history_items") == 1
        and history_results[1][1].get("history_items") == 2
    )
    results.append(report("Conversation history persists in Redis", history_passed))

    instance_ids = set()
    for _ in range(9):
        status, response = request(base_url, "/health")
        if status == 200 and response.get("instance_id"):
            instance_ids.add(response["instance_id"])
    results.append(
        report(
            "Nginx distributes traffic across agent replicas",
            len(instance_ids) >= 2,
            str(sorted(instance_ids)),
        )
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", action="store_true")
    parser.add_argument("--url", default="http://localhost")
    parser.add_argument(
        "--api-key",
        default=os.getenv("AGENT_API_KEY", "my-local-secret-key"),
    )
    args = parser.parse_args()

    results = static_checks()
    if args.runtime:
        results.extend(runtime_checks(args.url, args.api_key))

    passed = sum(results)
    print(f"\nResult: {passed}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
