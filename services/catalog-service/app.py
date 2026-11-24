import sys
import os
import json
from http.server import HTTPServer, BaseHTTPRequestHandler

# Import vendored Python SDK
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../packages/python-sdk"))
from reliability import ReliabilityClient, ReliabilityConfig

PORT = int(os.environ.get("PORT", 5002))
SERVICE_ID = os.environ.get("XECURECODE_SERVICE_ID", "a2222222-2222-4222-8222-222222222222")
API_KEY = os.environ.get("XECURECODE_API_KEY", "xc_live_python_order_test_abcdef1234567890")
INGEST_URL = os.environ.get("XECURECODE_ENDPOINT", "http://localhost:4000/api/v1/ingest")

config = ReliabilityConfig(
    api_key=API_KEY,
    service_id=SERVICE_ID,
    mode="production",
    endpoint=INGEST_URL,
    debug=True,
)

client = ReliabilityClient(config)
print(f"[Catalog Service] Initialized with XecureCode SDK (Service ID: {SERVICE_ID})", flush=True)

class MockRequest:
    def __init__(self):
        self.method = "POST"
        self.url = "/api/pricing/calculate"
        self.headers = {
            "Authorization": "Bearer py-secret-token-abcdef",
            "Cookie": "session=order-user-777; secret_auth=xyz",
        }
        self.json = {
            "tenant_id": "tenant_982",
            "items": ["ITEM-1", "ITEM-2"],
            "api_key": "raw_third_party_vendor_key",
            "user_password": "sensitive_password_do_not_leak",
        }
        self.client = type("Client", (), {"host": "127.0.0.1"})()

class CatalogHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "UP", "service": "catalog-service", "port": PORT}).encode("utf-8"))
            return

        if self.path == "/api/products":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            products = [
                {"id": "PROD-1", "name": "Cloud Enterprise License", "price": 499.00},
                {"id": "PROD-2", "name": "Dedicated Proxy Instance", "price": 149.00},
            ]
            self.wfile.write(json.dumps({"success": True, "data": products}).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path.startswith("/api/pricing/calculate"):
            try:
                # Check for error simulation toggle
                simulate_error = "simulate_error=false" not in self.path
                if simulate_error:
                    raise RuntimeError(
                        "OrderProcessingTimeoutError: Redis lock acquisition failed on key 'order:lock:tenant_982' - cluster partition timeout after 5000ms at redis-cluster.internal:6379"
                    )

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "discountedTotal": 548.00}).encode("utf-8"))
                return
            except Exception as e:
                # Capture with context (sensitive fields automatically sanitized by SDK)
                mock_req = MockRequest()
                client.capture(e, request=mock_req)
                client.flush()

                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "error": "Internal Server Error",
                    "message": str(e),
                    "tracked": True,
                }).encode("utf-8"))
                return

        if self.path == "/flush":
            client.flush()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"flushed": True}).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), CatalogHandler)
    print(f"[Catalog Service] Listening on http://0.0.0.0:{PORT}", flush=True)
    server.serve_forever()
