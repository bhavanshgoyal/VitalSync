package com.vitalsync;

import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Controllable stand-in for the Python triage service.
 *
 * <p>Lets a test make the ML tier slow, broken or absent on demand, which is how
 * the decoupling and degraded-mode claims are exercised without depending on a
 * real Python process.
 */
final class StubMlServer implements AutoCloseable {

    private final HttpServer server;
    private final AtomicLong delayMs = new AtomicLong(0);
    private final AtomicInteger status = new AtomicInteger(200);
    private final AtomicInteger requestCount = new AtomicInteger(0);
    private final AtomicReference<String> band = new AtomicReference<>("MEDIUM");

    private static final String BODY_TEMPLATE = """
            {
              "risk": "%s",
              "probabilities": {"LOW": 0.10, "MEDIUM": 0.75, "HIGH": 0.15},
              "confidence": 0.75,
              "news2": {"total": 5, "band": "MEDIUM", "max_single": 2},
              "derived": {"shock_index": 0.72, "pulse_pressure": 42.0, "map_mmhg": 92.0},
              "model_version": "stub-1.0.0",
              "inference_ms": 0.9
            }
            """;

    StubMlServer() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);

        server.createContext("/health", exchange -> {
            byte[] out = "{\"status\":\"ok\",\"model_loaded\":true}".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, out.length);
            try (OutputStream os = exchange.getResponseBody()) {
                os.write(out);
            }
        });

        server.createContext("/predict", exchange -> {
            requestCount.incrementAndGet();
            long delay = delayMs.get();
            if (delay > 0) {
                try {
                    Thread.sleep(delay);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            }
            int code = status.get();
            byte[] out = (code == 200
                    ? BODY_TEMPLATE.formatted(band.get())
                    : "{\"error\":\"stub failure\"}").getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(code, out.length);
            try (OutputStream os = exchange.getResponseBody()) {
                os.write(out);
            }
        });

        server.setExecutor(java.util.concurrent.Executors.newFixedThreadPool(8));
        server.start();
    }

    String baseUrl() {
        return "http://127.0.0.1:" + server.getAddress().getPort();
    }

    void setDelayMs(long ms) {
        delayMs.set(ms);
    }

    void setStatus(int code) {
        status.set(code);
    }

    void setBand(String value) {
        band.set(value);
    }

    int requestCount() {
        return requestCount.get();
    }

    void reset() {
        delayMs.set(0);
        status.set(200);
        band.set("MEDIUM");
        requestCount.set(0);
    }

    @Override
    public void close() {
        server.stop(0);
    }
}
