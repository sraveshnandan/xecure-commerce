type Mode = "development" | "production";
type Severity = "critical" | "high" | "medium" | "low" | "warning";
type ErrorType = "RUNTIME" | "DATABASE" | "NETWORK" | "VALIDATION" | "AUTH" | "UNKNOWN";
interface RateLimitConfig {
    minIntervalMs?: number;
    maxPending?: number;
}
interface ReliabilityConfig {
    apiKey: string;
    service_id: string;
    mode: Mode;
    timeout?: number;
    endpoint?: string;
    version?: string;
    release?: string;
    commitHash?: string;
    branch?: string;
    buildId?: string;
    deploymentId?: string;
    sampleRate?: number;
    rateLimit?: RateLimitConfig;
    debug?: boolean;
}
interface RequestLike {
    method?: string;
    url?: string;
    originalUrl?: string;
    ip?: string;
    headers?: Record<string, string | string[] | undefined>;
    body?: unknown;
    query?: unknown;
    cookies?: unknown;
    raw?: {
        url?: string;
    };
}
interface RequestContext {
    method?: string;
    url?: string;
    ip?: string;
    userAgent?: string;
    headers?: Record<string, unknown>;
    body?: unknown;
    query?: unknown;
    cookies?: unknown;
}
interface ServiceContext {
    pid: number;
    runtime: "node";
    runtimeVersion: string;
    nodeVersion: string;
    platform: string;
    hostname: string;
}
interface ParsedErrorPayload {
    message: string;
    name: string;
    stack?: string;
    fingerprint: string;
    timestamp: number;
    service_id: string;
    environment: string;
    version?: string;
    release?: string;
    commitHash?: string;
    branch?: string;
    buildId?: string;
    deploymentId?: string;
    severity: Severity;
    errorType: ErrorType;
    serviceContext: ServiceContext;
    requestContext?: RequestContext;
}
interface IngestPayload extends Omit<ParsedErrorPayload, "service_id"> {
    service: string;
    occurrenceCount: number;
}
interface DeliveryResult {
    ok: boolean;
    status?: number;
    error?: Error;
}

declare class ReliabilityClient {
    private config;
    private initialized;
    private handleUncaught;
    private handleRejection;
    private lastSentTime;
    private pendingSends;
    private minIntervalMs;
    private maxPending;
    private sampleRate;
    private debug;
    private batchQueue;
    private batchFlushTimer;
    private batchSize;
    private batchFlushMs;
    constructor(config: ReliabilityConfig);
    private initGlobalHandlers;
    private canSend;
    private shouldSample;
    private log;
    private scheduleBatchFlush;
    private flushBatch;
    capture(error: unknown, req?: RequestLike): Promise<{
        ok: boolean;
        status?: number;
        error?: Error;
    }>;
    captureSync(error: unknown, req?: RequestLike): void;
    middleware(): (err: unknown, req: RequestLike, _res: unknown, next: (err?: unknown) => void) => void;
    flush(): Promise<void>;
    shutdown(): void;
}

declare function createExpressMiddleware(client: ReliabilityClient): (err: unknown, req: RequestLike, _res: unknown, next: (err?: unknown) => void) => void;
declare function createNestInterceptor(client: ReliabilityClient): {
    intercept(context: unknown, next: unknown): unknown;
};
declare function createKoaMiddleware(client: ReliabilityClient): (ctx: {
    request: RequestLike;
}, next: () => Promise<void>) => Promise<void>;
declare function createNextjsMiddleware(client: ReliabilityClient): (request: {
    nextUrl: URL;
    headers: Headers;
    method: string;
    body?: unknown;
}, response: unknown, next: (err?: unknown) => void) => void;
declare function createFastifyPlugin(client: ReliabilityClient): (fastify: {
    setErrorHandler: (handler: (err: Error, req: RequestLike, reply: {
        send: (data: unknown) => void;
    }) => void) => void;
}) => Promise<void>;

export { type DeliveryResult, type ErrorType, type IngestPayload, type Mode, type ParsedErrorPayload, type RateLimitConfig, ReliabilityClient, type ReliabilityConfig, type RequestContext, type RequestLike, type ServiceContext, type Severity, createExpressMiddleware, createFastifyPlugin, createKoaMiddleware, createNestInterceptor, createNextjsMiddleware };
