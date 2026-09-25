package com.vitalsync.api;

import com.vitalsync.api.dto.Dtos;
import com.vitalsync.security.JwtService;
import jakarta.validation.Valid;
import java.security.MessageDigest;
import java.nio.charset.StandardCharsets;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Demo token issuance.
 *
 * <p>A single environment-configured credential pair, not a user store. This is
 * adequate for a research prototype that never sees real data, and is called
 * out as inadequate for anything else in the security notes.
 */
@RestController
@RequestMapping("/api/v1/auth")
public class AuthController {

    private final JwtService jwtService;
    private final String demoUser;
    private final String demoPassword;

    public AuthController(
            JwtService jwtService,
            @Value("${vitalsync.security.demo-user:clinician}") String demoUser,
            @Value("${vitalsync.security.demo-password:vitalsync-demo}") String demoPassword) {
        this.jwtService = jwtService;
        this.demoUser = demoUser;
        this.demoPassword = demoPassword;
    }

    @PostMapping("/token")
    public ResponseEntity<?> token(@Valid @RequestBody Dtos.TokenRequest request) {
        boolean ok = constantTimeEquals(request.username(), demoUser)
                & constantTimeEquals(request.password(), demoPassword);

        if (!ok) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                    .body(java.util.Map.of("error", "Invalid credentials"));
        }

        String token = jwtService.issue(request.username(), "CLINICIAN");
        return ResponseEntity.ok(new Dtos.TokenResponse(
                token, "Bearer", jwtService.ttlSeconds(), request.username(), "CLINICIAN"));
    }

    /**
     * Compares without an early exit.
     *
     * <p>Both comparisons above are evaluated with a non-short-circuiting {@code &}
     * for the same reason: a username check that returns early leaks which half
     * of the credential was wrong.
     */
    private static boolean constantTimeEquals(String a, String b) {
        if (a == null || b == null) {
            return false;
        }
        return MessageDigest.isEqual(
                a.getBytes(StandardCharsets.UTF_8),
                b.getBytes(StandardCharsets.UTF_8));
    }
}
