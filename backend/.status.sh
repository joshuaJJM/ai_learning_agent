#!/bin/bash
APP=/home/hackathon/haoxue-backend
BASE=http://127.0.0.1:17283
PID=$(cat $APP/haoxue.pid 2>/dev/null)

echo "=== 1) process ==="
ps -o pid,etime,rss,pcpu,pmem,cmd -p $PID 2>/dev/null || echo "pid $PID NOT RUNNING"

echo
echo "=== 2) system resources ==="
uptime
echo "--- memory ---"
free -h
echo "--- disk ---"
df -h / | tail -1
echo "--- load ---"
cat /proc/loadavg

echo
echo "=== 3) listening ports ==="
ss -ltnp 2>/dev/null | grep -E '17283|41928' || echo "none"

echo
echo "=== 4) service.log: restart / traceback scan ==="
echo "--- log size + mtime ---"
ls -l --time-style=+%Y-%m-%d_%H:%M:%S $APP/service.log
echo "--- START markers (each start.sh writes pid line) ---"
grep -c "Started server process" $APP/service.log 2>/dev/null || echo 0
grep -n "Application startup complete" $APP/service.log 2>/dev/null | tail -5
echo "--- tracebacks / errors ---"
grep -cE "Traceback|ERROR|CRITICAL" $APP/service.log 2>/dev/null || echo 0
grep -nE "Traceback|ERROR|CRITICAL" $APP/service.log 2>/dev/null | tail -10
echo "--- 5xx responses ---"
grep -cE '" 5[0-9][0-9] ' $APP/service.log 2>/dev/null || echo 0

echo
echo "=== 5) AI/chat call history (today) ==="
grep -E "POST /api/v1/ai/chat" $APP/service.log 2>/dev/null | tail -10
echo "--- siliconflow upstream calls ---"
grep -c "api.siliconflow.cn" $APP/service.log 2>/dev/null || echo 0
grep "api.siliconflow.cn" $APP/service.log 2>/dev/null | tail -5

echo
echo "=== 6) recent requests (last 15 lines) ==="
tail -15 $APP/service.log

echo
echo "=== 7) live end-to-end: streaming chat on loopback ==="
curl -s --max-time 90 -N -X POST $BASE/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Reply with exactly: PONG","stream":true,"max_tokens":24}' \
  -o /tmp/_ping.txt -w "stream http=%{http_code} total=%{time_total}s\n"
echo "event types seen:"
grep -o '^event: .*' /tmp/_ping.txt | sort | uniq -c
echo "done payload:"
grep '^data: {"reply"' /tmp/_ping.txt | head -1 | cut -c1-200
rm -f /tmp/_ping.txt
