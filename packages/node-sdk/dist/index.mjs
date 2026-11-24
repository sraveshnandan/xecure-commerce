// src/errorParser.ts
import os from "os";

// src/utils/index.ts
import crypto from "crypto";

// src/utils/sanitize.ts
var SENSITIVE_KEYS = /* @__PURE__ */ new Set([
  "authorization",
  "cookie",
  "set-cookie",
  "x-api-key",
  "api-key",
  "apikey",
  "password",
  "token",
  "access_token",
  "refresh_token",
  "secret",
  "signature"
]);
var REDACTED = "[REDACTED]";
var normalizeKey = (key) => key.toLowerCase();
var sanitizeString = (value) => {
  if (!value) return value;
  return value.replace(/(bearer\s+)[a-z0-9._\-+/=]+/gi, "$1[REDACTED]").replace(/(token|password|secret|api[_-]?key)\s*[:=]\s*["']?[^"'\s]+/gi, "$1=[REDACTED]");
};
var sanitizeValue = (value) => {
  if (typeof value === "string") {
    return sanitizeString(value);
  }
  if (Array.isArray(value)) {
    return value.map((item) => sanitizeValue(item));
  }
  if (value && typeof value === "object") {
    const output = {};
    for (const [key, entry] of Object.entries(value)) {
      output[key] = SENSITIVE_KEYS.has(normalizeKey(key)) ? REDACTED : sanitizeValue(entry);
    }
    return output;
  }
  return value;
};
var sanitizeHeaders = (headers) => {
  if (!headers) return void 0;
  return sanitizeValue(headers);
};

// src/utils/index.ts
var generateFingerprint = (error) => {
  const stackLine = error.stack?.split("\n")[1] || "";
  return crypto.createHash("sha256").update(error.message + stackLine).digest("hex");
};
var classifyError = (error) => {
  const msg = error.message.toLowerCase();
  if (msg.includes("timeout") || msg.includes("econnrefused") || msg.includes("database") || msg.includes("sql")) {
    return "DATABASE";
  }
  if (msg.includes("network") || msg.includes("fetch") || msg.includes("socket")) {
    return "NETWORK";
  }
  if (error.name === "ValidationError" || msg.includes("validation")) {
    return "VALIDATION";
  }
  if (msg.includes("permission") || msg.includes("denied") || msg.includes("forbidden") || msg.includes("unauthorized") || msg.includes("jwt")) {
    return "AUTH";
  }
  if (error instanceof Error) {
    return "RUNTIME";
  }
  return "UNKNOWN";
};
var determineSeverity = (error) => {
  const msg = error.message.toLowerCase();
  if (msg.includes("database") || msg.includes("timeout") || msg.includes("econnrefused")) {
    return "critical";
  }
  return "medium";
};
var normalizeHeader = (value) => {
  if (Array.isArray(value)) return value.join(", ");
  return value;
};
var extractRequestContext = (req) => {
  if (!req) return void 0;
  const headers = req.headers ?? {};
  const forwardedFor = normalizeHeader(headers["x-forwarded-for"]);
  const userAgent = normalizeHeader(headers["user-agent"]);
  const context = {
    method: req.method,
    url: req.originalUrl || req.url,
    ip: req.ip || forwardedFor?.split(",")[0]?.trim()
  };
  if (userAgent) {
    context.userAgent = userAgent;
  }
  const sanitizedHeaders = sanitizeHeaders(headers);
  if (sanitizedHeaders) {
    context.headers = sanitizedHeaders;
  }
  if ("body" in req) {
    context.body = sanitizeValue(req.body);
  }
  return Object.values(context).some(Boolean) ? context : void 0;
};

// src/errorParser.ts
function normalizeError(error) {
  if (error instanceof Error) return error;
  const fallback = new Error(String(error));
  if (typeof error === "object" && error !== null) {
    const candidate = error;
    if (candidate.name) fallback.name = candidate.name;
    if (candidate.stack) fallback.stack = candidate.stack;
  }
  return fallback;
}
var parseError = (error, req, options) => {
  try {
    const normalizedError = normalizeError(error);
    const fingerprint = generateFingerprint(normalizedError);
    const errorType = classifyError(normalizedError);
    const severity = determineSeverity(normalizedError);
    return {
      message: normalizedError.message || "Unknown error",
      name: normalizedError.name || "Error",
      stack: normalizedError.stack ?? "",
      fingerprint,
      timestamp: Date.now(),
      service_id: "unknown-service",
      environment: "unknown-mode",
      version: options?.version,
      release: options?.release,
      commitHash: options?.commitHash,
      branch: options?.branch,
      buildId: options?.buildId,
      deploymentId: options?.deploymentId,
      severity,
      errorType,
      serviceContext: {
        pid: process.pid,
        runtime: "node",
        runtimeVersion: process.version,
        nodeVersion: process.version,
        platform: process.platform,
        hostname: os.hostname()
      },
      requestContext: extractRequestContext(req) ?? void 0
    };
  } catch (parseError2) {
    const parserFailure = parseError2 instanceof Error ? parseError2.message : "Unknown parser failure";
    return {
      message: `Parser failure: ${parserFailure}`,
      name: "ParserError",
      stack: "",
      fingerprint: "unknown",
      timestamp: Date.now(),
      service_id: "unknown-service",
      environment: "unknown-mode",
      version: options?.version,
      release: options?.release,
      commitHash: options?.commitHash,
      branch: options?.branch,
      buildId: options?.buildId,
      deploymentId: options?.deploymentId,
      severity: "critical",
      errorType: "UNKNOWN",
      serviceContext: {
        pid: process.pid,
        runtime: "node",
        runtimeVersion: process.version,
        nodeVersion: process.version,
        platform: process.platform,
        hostname: os.hostname()
      },
      requestContext: void 0
    };
  }
};

// src/utils/dedupe.ts
var cache = /* @__PURE__ */ new Map();
var DEDUP_WINDOW_MS = 6e4;
function recordFingerprint(fingerprint) {
  const now = Date.now();
  const entry = cache.get(fingerprint);
  if (!entry) {
    cache.set(fingerprint, { fingerprint, timestamp: now, count: 1 });
    return 1;
  }
  if (now - entry.timestamp > DEDUP_WINDOW_MS) {
    entry.timestamp = now;
    entry.count = 1;
    return 1;
  }
  entry.count++;
  return entry.count;
}
function consumeDuplicateCount(fingerprint) {
  const entry = cache.get(fingerprint);
  if (!entry) return 0;
  const count = entry.count;
  entry.count = 0;
  return count;
}
function cleanupCache() {
  const now = Date.now();
  for (const [key, entry] of cache) {
    if (now - entry.timestamp > DEDUP_WINDOW_MS) {
      cache.delete(key);
    }
  }
}
var cleanupInterval = setInterval(cleanupCache, DEDUP_WINDOW_MS);
cleanupInterval.unref?.();

// src/sender.ts
var MAX_RETRIES = 3;
var RETRY_DELAY_MS = 1e3;
var DEFAULT_ENDPOINT = "https://api.xecurecode.in/api/v1/ingest";
var SDK_VERSION = "node@0.3.0";
async function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
async function fetchWithRetry(url, options, timeoutMs, retries = MAX_RETRIES) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal
    });
    if (response.ok) {
      return { ok: true, status: response.status };
    }
    if (response.status >= 500 && retries > 0) {
      await sleep(RETRY_DELAY_MS * (MAX_RETRIES - retries + 1));
      return fetchWithRetry(url, options, timeoutMs, retries - 1);
    }
    return { ok: false, status: response.status };
  } catch (error) {
    if (retries > 0) {
      await sleep(RETRY_DELAY_MS * (MAX_RETRIES - retries + 1));
      return fetchWithRetry(url, options, timeoutMs, retries - 1);
    }
    return {
      ok: false,
      error: error instanceof Error ? error : new Error(String(error))
    };
  } finally {
    clearTimeout(timeout);
  }
}
function addSdkVersion(payload) {
  return {
    ...payload,
    sdk_version: SDK_VERSION
  };
}
async function sendToBackend(payload, config) {
  const endpoint = config.endpoint || DEFAULT_ENDPOINT;
  return fetchWithRetry(endpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "xc-api-key": config.apiKey,
      "xc-service-id": config.service_id
    },
    body: JSON.stringify(addSdkVersion(payload))
  }, config.timeout ?? 5e3);
}
async function sendBatchToBackend(payloads, config) {
  const endpoint = (config.endpoint || DEFAULT_ENDPOINT).replace("/ingest", "/ingest/batch");
  return fetchWithRetry(endpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "xc-api-key": config.apiKey,
      "xc-service-id": config.service_id
    },
    body: JSON.stringify(payloads.map(addSdkVersion))
  }, config.timeout ?? 5e3);
}

// src/ReliabilityClient.ts
var DEFAULT_MIN_INTERVAL_MS = 100;
var DEFAULT_MAX_PENDING = 100;
var DEFAULT_BATCH_SIZE = 10;
var DEFAULT_BATCH_FLUSH_MS = 5e3;
var ReliabilityClient = class {
  config;
  initialized = false;
  handleUncaught;
  handleRejection;
  lastSentTime = 0;
  pendingSends = 0;
  minIntervalMs;
  maxPending;
  sampleRate;
  debug;
  batchQueue = [];
  batchFlushTimer = null;
  batchSize;
  batchFlushMs;
  constructor(config) {
    if (!config.apiKey) {
      throw new Error("API Key required");
    }
    if (config.sampleRate !== void 0 && (config.sampleRate < 0 || config.sampleRate > 1)) {
      throw new Error("sampleRate must be between 0 and 1");
    }
    this.config = config;
    this.minIntervalMs = config.rateLimit?.minIntervalMs ?? DEFAULT_MIN_INTERVAL_MS;
    this.maxPending = config.rateLimit?.maxPending ?? DEFAULT_MAX_PENDING;
    this.sampleRate = config.sampleRate ?? 1;
    this.debug = config.debug ?? false;
    this.batchSize = DEFAULT_BATCH_SIZE;
    this.batchFlushMs = DEFAULT_BATCH_FLUSH_MS;
    this.handleUncaught = (err) => this.capture(err);
    this.handleRejection = (reason) => this.capture(reason instanceof Error ? reason : new Error(String(reason)));
    this.initGlobalHandlers();
    this.initialized = true;
    if (this.debug) {
      this.log("ReliabilityClient initialized", {
        serviceId: this.config.service_id,
        mode: this.config.mode,
        sampleRate: this.sampleRate,
        rateLimit: { minIntervalMs: this.minIntervalMs, maxPending: this.maxPending }
      });
    }
  }
  initGlobalHandlers() {
    process.on("uncaughtException", this.handleUncaught);
    process.on("unhandledRejection", this.handleRejection);
  }
  canSend() {
    const now = Date.now();
    if (now - this.lastSentTime < this.minIntervalMs) return false;
    if (this.pendingSends >= this.maxPending) return false;
    return true;
  }
  shouldSample() {
    if (this.sampleRate >= 1) return true;
    if (this.sampleRate <= 0) return false;
    return Math.random() < this.sampleRate;
  }
  log(message, data) {
    if (this.debug) {
      console.debug(`[xecurecode] ${message}`, data ?? "");
    }
  }
  scheduleBatchFlush() {
    if (this.batchFlushTimer) return;
    this.batchFlushTimer = setTimeout(() => {
      this.batchFlushTimer = null;
      void this.flushBatch();
    }, this.batchFlushMs);
    this.batchFlushTimer.unref?.();
  }
  async flushBatch() {
    if (this.batchQueue.length === 0) return;
    const batch = this.batchQueue.splice(0, this.batchSize);
    const payloads = batch.map((item) => item.payload);
    const fingerprints = batch.map((item) => item.fingerprint);
    this.pendingSends++;
    this.lastSentTime = Date.now();
    try {
      const result = await sendBatchToBackend(payloads, this.config);
      if (result.ok) {
        for (const fp of fingerprints) {
          consumeDuplicateCount(fp);
        }
        for (const item of batch) {
          item.resolve({ ok: true, status: result.status });
        }
        this.log("Batch sent successfully", { count: payloads.length });
      } else {
        const failureError = new Error(`Batch failed with status ${result.status}`);
        for (const item of batch) {
          item.resolve({ ok: false, status: result.status, error: failureError });
        }
        this.log("Batch send failed", { status: result.status, count: payloads.length });
      }
    } catch (error) {
      const err = error instanceof Error ? error : new Error(String(error));
      for (const item of batch) {
        item.resolve({ ok: false, error: err });
      }
      this.log("Batch send error", { error: err.message, count: payloads.length });
    } finally {
      this.pendingSends--;
      if (this.batchQueue.length > 0) {
        this.scheduleBatchFlush();
      }
    }
  }
  capture(error, req) {
    if (!this.initialized) return Promise.resolve({ ok: true });
    if (!this.shouldSample()) {
      this.log("Dropped: sampling", { sampleRate: this.sampleRate });
      return Promise.resolve({ ok: true });
    }
    const parsed = parseError(error, req, {
      service: this.config.service_id,
      environment: this.config.mode,
      version: this.config.version,
      release: this.config.release,
      commitHash: this.config.commitHash,
      branch: this.config.branch,
      buildId: this.config.buildId,
      deploymentId: this.config.deploymentId
    });
    const occurrenceCount = recordFingerprint(parsed.fingerprint);
    if (!this.canSend()) {
      this.log("Dropped: rate limited", { pendingSends: this.pendingSends, maxPending: this.maxPending });
      return Promise.resolve({ ok: false, error: new Error("Rate limited") });
    }
    const { service_id: _serviceId, ...eventPayload } = parsed;
    const payload = {
      ...eventPayload,
      service: this.config.service_id,
      environment: this.config.mode,
      occurrenceCount
    };
    this.log("Captured error", { fingerprint: parsed.fingerprint, message: parsed.message });
    return new Promise((resolve, reject) => {
      this.batchQueue.push({ payload, fingerprint: parsed.fingerprint, resolve, reject });
      this.log("Queued for batch send", { queueLength: this.batchQueue.length });
      if (this.batchQueue.length >= this.batchSize) {
        void this.flushBatch();
      } else {
        this.scheduleBatchFlush();
      }
    }).catch((err) => {
      this.log("Batch promise rejected", { error: err.message });
      return { ok: false, error: err instanceof Error ? err : new Error(String(err)) };
    });
  }
  captureSync(error, req) {
    if (!this.initialized) return;
    if (!this.shouldSample()) {
      this.log("Dropped: sampling", { sampleRate: this.sampleRate });
      return;
    }
    const parsed = parseError(error, req, {
      service: this.config.service_id,
      environment: this.config.mode,
      version: this.config.version,
      release: this.config.release,
      commitHash: this.config.commitHash,
      branch: this.config.branch,
      buildId: this.config.buildId,
      deploymentId: this.config.deploymentId
    });
    const occurrenceCount = recordFingerprint(parsed.fingerprint);
    if (!this.canSend()) {
      this.log("Dropped: rate limited", { pendingSends: this.pendingSends, maxPending: this.maxPending });
      return;
    }
    const { service_id: _serviceId, ...eventPayload } = parsed;
    const payload = {
      ...eventPayload,
      service: this.config.service_id,
      environment: this.config.mode,
      occurrenceCount
    };
    this.log("Captured error (sync)", { fingerprint: parsed.fingerprint, message: parsed.message });
    this.pendingSends++;
    this.lastSentTime = Date.now();
    setImmediate(async () => {
      try {
        await sendToBackend(payload, this.config);
        consumeDuplicateCount(parsed.fingerprint);
        this.log("Sent successfully (sync)", { fingerprint: parsed.fingerprint });
      } catch (err) {
        this.log("Send failed (sync)", { error: err instanceof Error ? err.message : String(err) });
      } finally {
        this.pendingSends--;
      }
    });
  }
  middleware() {
    const self = this;
    return function errorHandler(err, req, _res, next) {
      self.captureSync(err, req);
      next(err);
    };
  }
  async flush() {
    await this.flushBatch();
    while (this.pendingSends > 0) {
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  }
  shutdown() {
    process.removeListener("uncaughtException", this.handleUncaught);
    process.removeListener("unhandledRejection", this.handleRejection);
    if (this.batchFlushTimer) {
      clearTimeout(this.batchFlushTimer);
      this.batchFlushTimer = null;
    }
    void this.flush();
  }
};

// src/integrations.ts
function createExpressMiddleware(client) {
  return function errorHandler(err, req, _res, next) {
    client.captureSync(err, req);
    next(err);
  };
}
function createNestInterceptor(client) {
  return {
    intercept(context, next) {
      try {
        return next;
      } catch (err) {
        const req = context && typeof context === "object" && "switchToHttp" in context ? context.switchToHttp().getRequest() : void 0;
        client.captureSync(err, req);
        throw err;
      }
    }
  };
}
function createKoaMiddleware(client) {
  return async function koaErrorHandler(ctx, next) {
    try {
      await next();
    } catch (err) {
      client.captureSync(err, ctx.request);
      throw err;
    }
  };
}
function createNextjsMiddleware(client) {
  return function nextjsErrorHandler(request, response, next) {
    const originalJson = response.json;
    if (originalJson) {
      response.json = function(data) {
        if (data && typeof data === "object" && "error" in data) {
          const req = {
            method: request.method,
            url: request.nextUrl.pathname,
            originalUrl: request.nextUrl.href,
            headers: Object.fromEntries(request.headers.entries()),
            body: request.body
          };
          client.captureSync(data.error, req);
        }
        return originalJson.call(response, data);
      };
    }
    next();
  };
}
function createFastifyPlugin(client) {
  return async function fastifyPlugin(fastify) {
    fastify.setErrorHandler((err, req, reply) => {
      const requestLike = {
        method: req.method,
        url: req.url,
        originalUrl: req.raw?.url,
        headers: req.headers,
        body: req.body,
        query: req.query,
        ip: req.ip
      };
      client.captureSync(err, requestLike);
      reply.send(err);
    });
  };
}
export {
  ReliabilityClient,
  createExpressMiddleware,
  createFastifyPlugin,
  createKoaMiddleware,
  createNestInterceptor,
  createNextjsMiddleware
};
//# sourceMappingURL=index.mjs.map