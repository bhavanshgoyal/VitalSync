package com.vitalsync.api;

import jakarta.servlet.http.HttpServletRequest;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.TreeMap;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.server.ResponseStatusException;

/**
 * Uniform error bodies.
 *
 * <p>Validation failures name the offending field and the reason, because the
 * telemetry contract is the thing a device integrator is most likely to get
 * wrong and a bare 400 gives them nothing to work with.
 */
@RestControllerAdvice
public class ApiExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(ApiExceptionHandler.class);

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Map<String, Object>> onValidation(
            MethodArgumentNotValidException e, HttpServletRequest request) {

        Map<String, String> fields = new TreeMap<>();
        e.getBindingResult().getFieldErrors().forEach(
                fe -> fields.put(fe.getField(), fe.getDefaultMessage()));

        return ResponseEntity.badRequest().body(body(
                HttpStatus.BAD_REQUEST, "Telemetry validation failed", request,
                Map.of("fieldErrors", fields)));
    }

    @ExceptionHandler(ResponseStatusException.class)
    public ResponseEntity<Map<String, Object>> onStatus(
            ResponseStatusException e, HttpServletRequest request) {
        HttpStatus status = HttpStatus.valueOf(e.getStatusCode().value());
        return ResponseEntity.status(status).body(
                body(status, e.getReason(), request, Map.of()));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, Object>> onUnexpected(
            Exception e, HttpServletRequest request) {
        log.error("Unhandled exception on {}", request.getRequestURI(), e);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(
                body(HttpStatus.INTERNAL_SERVER_ERROR,
                        "Unexpected server error", request, Map.of()));
    }

    private static Map<String, Object> body(
            HttpStatus status, String message, HttpServletRequest request,
            Map<String, Object> extra) {

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("timestamp", Instant.now().toString());
        out.put("status", status.value());
        out.put("error", status.getReasonPhrase());
        out.put("message", message == null ? status.getReasonPhrase() : message);
        out.put("path", request.getRequestURI());
        out.putAll(extra);
        return out;
    }
}
