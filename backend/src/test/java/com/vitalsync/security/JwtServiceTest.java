package com.vitalsync.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.Test;

class JwtServiceTest {

    private static final String SECRET = "test-secret-key-that-is-long-enough-32";

    private static JwtService service(long ttlSeconds) {
        JwtService s = new JwtService(SECRET, ttlSeconds, "vitalsync");
        s.init();
        return s;
    }

    @Test
    void issuesAndVerifiesAToken() {
        JwtService jwt = service(3600);
        String token = jwt.issue("clinician", "CLINICIAN");

        var claims = jwt.verify(token);
        assertThat(claims).isPresent();
        assertThat(claims.get().getSubject()).isEqualTo("clinician");
        assertThat(claims.get().get("role", String.class)).isEqualTo("CLINICIAN");
    }

    @Test
    void rejectsATamperedToken() {
        JwtService jwt = service(3600);
        String token = jwt.issue("clinician", "CLINICIAN");

        // Flip a character in the payload segment; the signature no longer matches.
        String[] parts = token.split("\\.");
        char[] payload = parts[1].toCharArray();
        payload[0] = payload[0] == 'a' ? 'b' : 'a';
        String tampered = parts[0] + "." + new String(payload) + "." + parts[2];

        assertThat(jwt.verify(tampered)).isEmpty();
    }

    @Test
    void rejectsATokenSignedWithADifferentSecret() {
        JwtService issuer = service(3600);
        JwtService verifier = new JwtService(
                "a-completely-different-secret-key-32b!", 3600, "vitalsync");
        verifier.init();

        assertThat(verifier.verify(issuer.issue("clinician", "CLINICIAN"))).isEmpty();
    }

    @Test
    void rejectsAnExpiredToken() throws InterruptedException {
        // One-second lifetime, then wait past it.
        JwtService jwt = service(1);
        String token = jwt.issue("clinician", "CLINICIAN");
        assertThat(jwt.verify(token)).isPresent();

        Thread.sleep(1500);
        assertThat(jwt.verify(token)).isEmpty();
    }

    @Test
    void rejectsGarbage() {
        JwtService jwt = service(3600);
        assertThat(jwt.verify("not-a-token")).isEmpty();
        assertThat(jwt.verify("")).isEmpty();
    }

    @Test
    void refusesToStartWithATooShortSecret() {
        JwtService weak = new JwtService("short", 3600, "vitalsync");
        assertThatThrownBy(weak::init)
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("at least 32 bytes");
    }
}
