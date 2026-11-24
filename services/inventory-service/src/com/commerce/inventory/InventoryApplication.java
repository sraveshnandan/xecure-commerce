package com.commerce.inventory;

import com.sun.net.httpserver.HttpServer;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpExchange;
import com.xecurecode.reliability.ReliabilityClient;
import com.xecurecode.reliability.ReliabilityConfig;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.util.HashMap;
import java.util.Map;

public class InventoryApplication {
    private static final int PORT = Integer.parseInt(System.getenv().getOrDefault("PORT", "5003"));
    private static final String SERVICE_ID = System.getenv().getOrDefault("XECURECODE_SERVICE_ID", "a3333333-3333-4333-8333-333333333333");
    private static final String API_KEY = System.getenv().getOrDefault("XECURECODE_API_KEY", "xc_live_java_inventory_test_abcdef1234567890");
    private static final String INGEST_URL = System.getenv().getOrDefault("XECURECODE_ENDPOINT", "http://localhost:4000/api/v1/ingest");

    public static void main(String[] args) throws Exception {
        ReliabilityConfig config = new ReliabilityConfig.Builder()
            .apiKey(API_KEY)
            .serviceId(SERVICE_ID)
            .endpoint(INGEST_URL)
            .mode("production")
            .debug(true)
            .build();

        ReliabilityClient client = new ReliabilityClient(config);

        System.out.println("[Inventory Service] Initialized with XecureCode Java SDK (Service ID: " + SERVICE_ID + ")");

        HttpServer server = HttpServer.create(new InetSocketAddress(PORT), 0);

        server.createContext("/health", new HttpHandler() {
            @Override
            public void handle(HttpExchange exchange) throws IOException {
                if ("GET".equalsIgnoreCase(exchange.getRequestMethod())) {
                    String response = "{\"status\": \"UP\", \"service\": \"inventory-service\", \"port\": " + PORT + "}";
                    exchange.getResponseHeaders().set("Content-Type", "application/json");
                    exchange.sendResponseHeaders(200, response.getBytes().length);
                    try (OutputStream os = exchange.getResponseBody()) {
                        os.write(response.getBytes());
                    }
                } else {
                    exchange.sendResponseHeaders(405, -1);
                }
            }
        });

        server.createContext("/api/inventory/check", new HttpHandler() {
            @Override
            public void handle(HttpExchange exchange) throws IOException {
                if ("GET".equalsIgnoreCase(exchange.getRequestMethod())) {
                    String response = "{\"success\": true, \"sku\": \"SKU-CLOUD-01\", \"available\": 450}";
                    exchange.getResponseHeaders().set("Content-Type", "application/json");
                    exchange.sendResponseHeaders(200, response.getBytes().length);
                    try (OutputStream os = exchange.getResponseBody()) {
                        os.write(response.getBytes());
                    }
                } else {
                    exchange.sendResponseHeaders(405, -1);
                }
            }
        });

        server.createContext("/api/inventory/reserve", new HttpHandler() {
            @Override
            public void handle(HttpExchange exchange) throws IOException {
                if ("POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                    String query = exchange.getRequestURI().getQuery();
                    boolean simulateError = query == null || !query.contains("simulate_error=false");

                    if (simulateError) {
                        try {
                            throw new NullPointerException(
                                "StockAllocationException: Stock reservation lock failed for SKU-WAREHOUSE-9821. Transaction deadlock at warehouse-db.internal:5432 after 10000ms"
                            );
                        } catch (Exception ex) {
                            Map<String, Object> reqContext = new HashMap<>();
                            reqContext.put("method", "POST");
                            reqContext.put("url", "/api/inventory/reserve");

                            Map<String, Object> headers = new HashMap<>();
                            headers.put("Authorization", "Bearer java-super-secret-token");
                            headers.put("Cookie", "session=java-user-cookie; token=sensitive-token");
                            headers.put("X-Custom-Secret", "my-hidden-secret");
                            reqContext.put("headers", headers);

                            Map<String, Object> body = new HashMap<>();
                            body.put("sku", "SKU-WAREHOUSE-9821");
                            body.put("quantity", 5);
                            body.put("password", "confidential_warehouse_pass");
                            body.put("secretKey", "secret_warehouse_key_xyz");
                            reqContext.put("body", body);

                            client.capture(ex, reqContext);
                            client.flush();

                            String errorResp = "{\"error\": \"Internal Server Error\", \"message\": \"" + ex.getMessage() + "\", \"tracked\": true}";
                            exchange.getResponseHeaders().set("Content-Type", "application/json");
                            exchange.sendResponseHeaders(500, errorResp.getBytes().length);
                            try (OutputStream os = exchange.getResponseBody()) {
                                os.write(errorResp.getBytes());
                            }
                        }
                    } else {
                        String successResp = "{\"success\": true, \"reservationId\": \"RES-5544\"}";
                        exchange.getResponseHeaders().set("Content-Type", "application/json");
                        exchange.sendResponseHeaders(200, successResp.getBytes().length);
                        try (OutputStream os = exchange.getResponseBody()) {
                            os.write(successResp.getBytes());
                        }
                    }
                } else {
                    exchange.sendResponseHeaders(405, -1);
                }
            }
        });

        server.createContext("/flush", new HttpHandler() {
            @Override
            public void handle(HttpExchange exchange) throws IOException {
                client.flush();
                String response = "{\"flushed\": true}";
                exchange.getResponseHeaders().set("Content-Type", "application/json");
                exchange.sendResponseHeaders(200, response.getBytes().length);
                try (OutputStream os = exchange.getResponseBody()) {
                    os.write(response.getBytes());
                }
            }
        });

        server.setExecutor(null);
        server.start();
        System.out.println("[Inventory Service] Listening on http://0.0.0.0:" + PORT);
    }
}
