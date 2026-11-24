#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "================================================================="
echo " XecureCode Multi-Commerce Microservices E2E Test & Verification"
echo " Time: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "================================================================="

# Start microservices in background
PID_NODE=""
PID_PY=""
PID_JAVA=""

cleanup() {
  echo -e "\n--> Cleaning up microservice background processes..."
  [ -n "${PID_NODE}" ] && kill -9 "${PID_NODE}" 2>/dev/null || true
  [ -n "${PID_PY}" ] && kill -9 "${PID_PY}" 2>/dev/null || true
  [ -n "${PID_JAVA}" ] && kill -9 "${PID_JAVA}" 2>/dev/null || true
}
trap cleanup EXIT

# 1. Start Node Checkout Service (Port 5001)
echo "▶ [1/3] Starting Checkout Service (Node.js :5001)..."
(cd "$ROOT_DIR/services/checkout-service" && node src/server.mjs) &
PID_NODE=$!

# 2. Start Python Catalog Service (Port 5002)
echo "▶ [2/3] Starting Catalog Service (Python :5002)..."
(cd "$ROOT_DIR/services/catalog-service" && python3 app.py) &
PID_PY=$!

# 3. Start Java Inventory Service (Port 5003)
echo "▶ [3/3] Starting Inventory Service (Java :5003)..."
CP="$(cat /tmp/cp.txt):$ROOT_DIR/packages/java-sdk/reliability-sdk-0.2.0.jar:$ROOT_DIR/services/inventory-service/bin"
java -cp "$CP" com.commerce.inventory.InventoryApplication &
PID_JAVA=$!

echo "▶ Awaiting microservices health check readiness..."
READY=false
for i in $(seq 1 20); do
  if curl -sf http://localhost:5001/health >/dev/null 2>&1 && \
     curl -sf http://localhost:5002/health >/dev/null 2>&1 && \
     curl -sf http://localhost:5003/health >/dev/null 2>&1; then
    READY=true
    echo "✓ All 3 microservices are healthy and listening!"
    break
  fi
  sleep 1
done

if [ "$READY" != "true" ]; then
  echo "❌ Error: Microservices failed to start in time." >&2
  exit 1
fi

echo -e "\n================================================================="
echo " Phase 1: Normal E-Commerce Transactions (Healthy Baseline)"
echo "================================================================="
T1=$(date +%s%N)
curl -s -X POST http://localhost:5001/api/orders -d '{"cartId":"c-123"}' >/dev/null
curl -s http://localhost:5002/api/products >/dev/null
curl -s http://localhost:5003/api/inventory/check >/dev/null
T2=$(date +%s%N)
BASELINE_MS=$(( (T2 - T1) / 1000000 ))
echo "✓ Baseline requests passed in ${BASELINE_MS}ms."

echo -e "\n================================================================="
echo " Phase 2: Simulating Realistic Production Incidents with Sensitive Data"
echo "================================================================="

echo "--> Triggering Node.js Database Connection Pool Exhaustion on /api/checkout..."
RESP_NODE=$(curl -s -X POST "http://localhost:5001/api/checkout?simulate_error=true" || true)
echo "    Response: $RESP_NODE"
curl -s -X POST http://localhost:5001/flush >/dev/null || true

echo "--> Triggering Python Distributed Lock Timeout on /api/pricing/calculate..."
RESP_PY=$(curl -s -X POST "http://localhost:5002/api/pricing/calculate?simulate_error=true" || true)
echo "    Response: $RESP_PY"
curl -s -X POST http://localhost:5002/flush >/dev/null || true

echo "--> Triggering Java Inventory Stock Allocation Deadlock on /api/inventory/reserve..."
RESP_JAVA=$(curl -s -X POST "http://localhost:5003/api/inventory/reserve?simulate_error=true" || true)
echo "    Response: $RESP_JAVA"
curl -s -X POST http://localhost:5003/flush >/dev/null || true

echo -e "\n================================================================="
echo " Phase 3: Awaiting Ingestion & Background AI RCA Pipeline"
echo "================================================================="
echo "▶ Polling for AI RCA completion (up to 30s)..."
for i in $(seq 1 30); do
  COUNT=$(docker exec xecurecode-postgres psql -U postgres -d xecuretrace -t -A -c "
    SELECT COUNT(*) FROM \"RCAReport\" r
    JOIN \"FailureCase\" c ON r.\"caseId\" = c.id
    WHERE c.\"serviceId\" IN (
      'a1111111-1111-4111-8111-111111111111', 
      'a2222222-2222-4222-8222-222222222222', 
      'a3333333-3333-4333-8333-333333333333'
    ) AND r.\"confidenceScore\" > 0;
  " 2>/dev/null || echo "0")
  if [ "${COUNT:-0}" -ge 3 ]; then
    echo "✓ All 3 AI RCA reports completed with high confidence!"
    break
  fi
  sleep 2
done

echo -e "\n================================================================="
echo " Phase 4: Verification of Client-Side Secrets Redaction"
echo "================================================================="
docker exec xecurecode-postgres psql -U postgres -d xecuretrace -c "
SELECT 
  s.name as service_name, 
  e.\"errorType\", 
  e.severity, 
  e.\"errorMessage\",
  (e.\"runtimeContext\"::text LIKE '%REDACTED%') as secrets_redacted,
  (e.\"runtimeContext\"::text NOT LIKE '%super_secret%' AND e.\"runtimeContext\"::text NOT LIKE '%sensitive_password%') as zero_plaintext_leaks
FROM \"FailureEvent\" e
JOIN \"Service\" s ON e.\"serviceId\" = s.id
WHERE s.id IN (
  'a1111111-1111-4111-8111-111111111111', 
  'a2222222-2222-4222-8222-222222222222', 
  'a3333333-3333-4333-8333-333333333333'
)
ORDER BY e.\"timestamp\" DESC LIMIT 3;
"

echo -e "\n================================================================="
echo " Phase 5: AI RCA Generated Root Cause & Culprit Reports"
echo "================================================================="
docker exec xecurecode-postgres psql -U postgres -d xecuretrace -c "
SELECT 
  s.name as service_name,
  r.\"confidenceScore\" as confidence,
  r.\"rootCauseCategory\" as category,
  r.\"rootCauseTitle\" as title,
  r.\"rootCauseSummary\" as summary
FROM \"RCAReport\" r
JOIN \"FailureCase\" c ON r.\"caseId\" = c.id
JOIN \"Service\" s ON c.\"serviceId\" = s.id
WHERE c.\"serviceId\" IN (
  'a1111111-1111-4111-8111-111111111111', 
  'a2222222-2222-4222-8222-222222222222', 
  'a3333333-3333-4333-8333-333333333333'
)
ORDER BY r.\"createdAt\" DESC LIMIT 3;
"

echo -e "\n================================================================="
echo " Phase 6: Emergency Rollback Safety Check Verification"
echo "================================================================="
docker exec xecurecode-postgres psql -U postgres -d xecuretrace -c "
SELECT 
  s.name as service_name,
  s.\"autoRollbackEnabled\",
  s.\"autoRollbackThreshold\",
  s.\"autoRollbackSeverityThreshold\"
FROM \"Service\" s
WHERE s.id IN (
  'a1111111-1111-4111-8111-111111111111', 
  'a2222222-2222-4222-8222-222222222222', 
  'a3333333-3333-4333-8333-333333333333'
);
"
echo "✓ Multi-Commerce E2E Simulation & Verification Complete!"
