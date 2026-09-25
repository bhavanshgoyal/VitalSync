package com.vitalsync.security;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import jakarta.annotation.PostConstruct;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Date;
import java.util.Optional;
import javax.crypto.SecretKey;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * Issues and verifies demo JWTs.
 *
 * <p>This is prototype authentication, not a production identity design: there
 * is no refresh, no revocation list, no key rotation and no external identity
 * provider. It exists so the API is not open by default, and so the paper can
 * describe an authenticated ingestion path honestly.
 */
@Service
public class JwtService {

    private static final Logger log = LoggerFactory.getLogger(JwtService.class);

    /** HMAC-SHA256 needs at least 256 bits of key material. */
    private static final int MIN_SECRET_BYTES = 32;

    private final String configuredSecret;
    private final long ttlSeconds;
    private final String issuer;
    private SecretKey key;

    public JwtService(
            @Value("${vitalsync.security.jwt-secret}") String configuredSecret,
            @Value("${vitalsync.security.jwt-ttl-seconds:3600}") long ttlSeconds,
            @Value("${vitalsync.security.jwt-issuer:vitalsync}") String issuer) {
        this.configuredSecret = configuredSecret;
        this.ttlSeconds = ttlSeconds;
        this.issuer = issuer;
    }

    @PostConstruct
    void init() {
        byte[] bytes = configuredSecret.getBytes(StandardCharsets.UTF_8);
        if (bytes.length < MIN_SECRET_BYTES) {
            throw new IllegalStateException(
                    "vitalsync.security.jwt-secret must be at least "
                            + MIN_SECRET_BYTES
                            + " bytes for HS256; got "
                            + bytes.length);
        }
        this.key = Keys.hmacShaKeyFor(bytes);
        if (configuredSecret.startsWith("change-me")) {
            log.warn("Using the built-in demo JWT secret. Override "
                    + "VITALSYNC_JWT_SECRET before exposing this service.");
        }
    }

    public String issue(String subject, String role) {
        Instant now = Instant.now();
        return Jwts.builder()
                .subject(subject)
                .issuer(issuer)
                .claim("role", role)
                .issuedAt(Date.from(now))
                .expiration(Date.from(now.plusSeconds(ttlSeconds)))
                .signWith(key)
                .compact();
    }

    /** Returns the claims when the token is valid and unexpired, else empty. */
    public Optional<Claims> verify(String token) {
        try {
            Claims claims = Jwts.parser()
                    .verifyWith(key)
                    .requireIssuer(issuer)
                    .build()
                    .parseSignedClaims(token)
                    .getPayload();
            return Optional.of(claims);
        } catch (JwtException | IllegalArgumentException e) {
            // Expired, tampered, wrong issuer, or structurally invalid. The
            // reason is deliberately not returned to the caller.
            log.debug("Rejected JWT: {}", e.getMessage());
            return Optional.empty();
        }
    }

    public long ttlSeconds() {
        return ttlSeconds;
    }
}
