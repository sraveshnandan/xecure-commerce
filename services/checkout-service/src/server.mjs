import http from "node:http";
import { ReliabilityClient } from "../../../packages/node-sdk/dist/index.mjs";

const PORT = process.env.PORT || 5001;
const SERVICE_ID = process.env.XECURECODE_SERVICE_ID || "a1111111-1111-4111-8111-111111111111";
const API_KEY = process.env.XECURECODE_API_KEY || "xc_live_node_checkout_test_abcdef1234567890";
const INGEST_URL = process.env.XECURECODE_ENDPOINT || "http://localhost:4000/api/v1/ingest";

const xc = new ReliabilityClient({
  apiKey: API_KEY,
  service_id: SERVICE_ID,
  mode: "production",
  endpoint: INGEST_URL,
  debug: true,
});

console.log(`[Checkout Service] Initialized with XecureCode SDK (Service ID: ${SERVICE_ID})`);

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);

  // Health check
  if (req.method === "GET" && url.pathname === "/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    return res.end(JSON.stringify({ status: "UP", service: "checkout-service", port: PORT, timestamp: new Date().toISOString() }));
  }

  // Normal order placement
  if (req.method === "POST" && url.pathname === "/api/orders") {
    let body = "";
    req.on("data", (chunk) => { body += chunk; });
    req.on("end", () => {
      const orderId = `ORD-${Date.now()}`;
      res.writeHead(201, { "Content-Type": "application/json" });
      return res.end(JSON.stringify({
        success: true,
        orderId,
        status: "CONFIRMED",
        itemsCount: 2,
        totalCents: 12450,
      }));
    });
    return;
  }

  // Checkout with incident injection capability
  if (req.method === "POST" && url.pathname === "/api/checkout") {
    let body = "";
    req.on("data", (chunk) => { body += chunk; });
    req.on("end", async () => {
      try {
        const simulateError = url.searchParams.get("simulate_error") !== "false";
        if (simulateError) {
          const dbErr = new Error(
            "DatabasePoolExhaustedError: Connection pool exhausted at db-cluster.internal:5432 after 30000ms. Active: 100/100 connections. Transaction aborted for order #ORD-8921."
          );
          dbErr.name = "DatabasePoolExhaustedError";
          throw dbErr;
        }

        res.writeHead(200, { "Content-Type": "application/json" });
        return res.end(JSON.stringify({ success: true, status: "PROCESSED" }));
      } catch (err) {
        // Redaction verification: ensure sensitive tokens/passwords in headers/body are redacted by SDK
        await xc.capture(err, {
          method: "POST",
          url: "/api/checkout",
          headers: {
            authorization: "Bearer secret-jwt-token-12345",
            cookie: "session=xyz987abc; token=my-session-token",
            "x-forwarded-for": "198.51.100.42",
          },
          body: {
            orderId: "ORD-8921",
            amountCents: 15400,
            password: "super_secret_user_password",
            creditCard: "4111-2222-3333-4444",
          },
        });

        res.writeHead(500, { "Content-Type": "application/json" });
        return res.end(JSON.stringify({
          error: "Internal Server Error",
          message: err.message,
          tracked: true,
        }));
      }
    });
    return;
  }

  // Force flush SDK buffer
  if (req.method === "POST" && url.pathname === "/flush") {
    try {
      await xc.flush();
      res.writeHead(200, { "Content-Type": "application/json" });
      return res.end(JSON.stringify({ flushed: true }));
    } catch (e) {
      res.writeHead(500, { "Content-Type": "application/json" });
      return res.end(JSON.stringify({ error: e.message }));
    }
  }

  res.writeHead(404, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ error: "Not Found" }));
});

server.listen(PORT, "0.0.0.0", () => {
  console.log(`[Checkout Service] Listening on http://0.0.0.0:${PORT}`);
});
