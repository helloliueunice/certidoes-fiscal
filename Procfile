web: uvicorn web.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips '*' --limit-concurrency 50 --timeout-keep-alive 15 --timeout-graceful-shutdown 30
