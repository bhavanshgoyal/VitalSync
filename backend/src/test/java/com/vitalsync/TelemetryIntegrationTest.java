package com.vitalsync;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.vitalsync.repo.RiskAssessmentRepository;
import com.vitalsync.repo.VitalReadingRepository;
import java.io.IOException;
import java.time.Duration;
import java.util.Map;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Testcontainers;

/**
 * End-to-end ingestion tests against a real PostgreSQL instance.
 *
 * <p>Uses Testcontainers rather than an in-memory database because the schema
 * relies on PostgreSQL-specific behaviour (INSERT ... RETURNING, ON CONFLICT,
 * TIMESTAMPTZ); passing on H2 would prove nothing about the deployed system.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@Testcontainers
class TelemetryIntegrationTest {

    @SuppressWarnings("resource")
    static final PostgreSQLContainer<?> POSTGRES =
            new PostgreSQLContainer<>("postgres:16-alpine")
                    .withDatabaseName("vitalsync")
                    .withUsername("vitalsync")
                    .withPassword("vitalsync");

    static StubMlServer ML;

    static {
        POSTGRES.start();
        try {
            ML = new StubMlServer();
        } catch (IOException e) {
            throw new ExceptionInInitializerError(e);
        }
    }

    @DynamicPropertySource
    static void properties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
        registry.add("vitalsync.ml.base-url", ML::baseUrl);
        registry.add("vitalsync.ml.read-timeout-ms", () -> "1500");
        registry.add("vitalsync.security.jwt-secret",
                () -> "integration-test-secret-key-long-enough");
    }

    @AfterAll
    static void tearDown() {
        ML.close();
    }

    @LocalServerPort
    int port;

    @Autowired
    TestRestTemplate rest;

    @Autowired
    VitalReadingRepository readings;

    @Autowired
    RiskAssessmentRepository assessments;

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @BeforeEach
    void resetStub() {
        ML.reset();
    }

    // ------------------------------------------------------------------ auth

    private String token() {
        ResponseEntity<String> res = rest.postForEntity(
                url("/api/v1/auth/token"),
                json(Map.of("username", "clinician", "password", "vitalsync-demo")),
                String.class);
        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.OK);
        try {
            return MAPPER.readTree(res.getBody()).get("token").asText();
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    private String url(String path) {
        return "http://localhost:" + port + path;
    }

    private static HttpEntity<Object> json(Object body) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        return new HttpEntity<>(body, headers);
    }

    private HttpEntity<Object> authed(Object body) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.setBearerAuth(token());
        return new HttpEntity<>(body, headers);
    }

    private static Map<String, Object> telemetry(String patientId, double hr) {
        return Map.of(
                "patientId", patientId,
                "heartRate", hr,
                "spo2", 96.5,
                "temperatureC", 37.1,
                "respiratoryRate", 18,
                "systolicBp", 118,
                "diastolicBp", 76);
    }

    @Test
    void unauthenticatedRequestsAreRejected() {
        ResponseEntity<String> res = rest.postForEntity(
                url("/api/v1/telemetry"), json(telemetry("P001", 88)), String.class);
        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
    }

    @Test
    void invalidCredentialsAreRejected() {
        ResponseEntity<String> res = rest.postForEntity(
                url("/api/v1/auth/token"),
                json(Map.of("username", "clinician", "password", "wrong")),
                String.class);
        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
    }

    @Test
    void healthEndpointIsPublic() {
        ResponseEntity<String> res = rest.getForEntity(url("/actuator/health"), String.class);
        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.OK);
    }

    // ------------------------------------------------------------- ingestion

    @Test
    void telemetryIsAcceptedAndPersisted() throws Exception {
        long before = readings.countForPatient("P001");

        ResponseEntity<String> res = rest.postForEntity(
                url("/api/v1/telemetry"), authed(telemetry("P001", 88)), String.class);

        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.ACCEPTED);
        JsonNode body = MAPPER.readTree(res.getBody());
        assertThat(body.get("status").asText()).isEqualTo("accepted");
        assertThat(body.get("readingId").asLong()).isPositive();

        assertThat(readings.countForPatient("P001")).isEqualTo(before + 1);

        var stored = readings.findById(body.get("readingId").asLong());
        assertThat(stored.heartRate()).isEqualTo(88.0);
        // Derived features are computed on write, not on read.
        assertThat(stored.shockIndex()).isCloseTo(88.0 / 118.0, org.assertj.core.data.Offset.offset(1e-9));
        assertThat(stored.pulsePressure()).isEqualTo(42.0);
    }

    @Test
    void malformedTelemetryIsRejectedWithFieldDetail() throws Exception {
        var bad = new java.util.HashMap<String, Object>(telemetry("P001", 88));
        bad.put("heartRate", 900); // outside the plausibility bound

        ResponseEntity<String> res = rest.postForEntity(
                url("/api/v1/telemetry"), authed(bad), String.class);

        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(MAPPER.readTree(res.getBody()).get("fieldErrors").has("heartRate")).isTrue();
    }

    @Test
    void missingRequiredFieldIsRejected() {
        var incomplete = Map.of("patientId", "P001", "heartRate", 88.0);
        ResponseEntity<String> res = rest.postForEntity(
                url("/api/v1/telemetry"), authed(incomplete), String.class);
        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
    }

    // ------------------------------------------------- THE DECOUPLING CLAIM

    /**
     * The central architectural test.
     *
     * <p>With the ML tier stalled well past the point where a synchronous
     * pipeline would block, ingestion must still return promptly. If this ever
     * fails, the "decoupled" claim in the paper is false.
     */
    @Test
    void ingestionDoesNotBlockOnASlowMlService() {
        // Authenticate and warm the request path first. Both cost real time on
        // first use (filter-chain init, JIT, connection-pool fill) and neither
        // is part of the claim being measured, so they are hoisted out of the
        // timed region rather than being allowed to inflate it.
        HttpEntity<Object> warmup = authed(telemetry("P002", 80));
        rest.postForEntity(url("/api/v1/telemetry"), warmup, String.class);

        HttpEntity<Object> request = authed(telemetry("P002", 92));
        ML.setDelayMs(3000);

        long start = System.nanoTime();
        ResponseEntity<String> res = rest.postForEntity(
                url("/api/v1/telemetry"), request, String.class);
        long elapsedMs = (System.nanoTime() - start) / 1_000_000;

        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.ACCEPTED);
        assertThat(elapsedMs)
                .as("ingestion returned in %dms; it must not wait for the 3000ms "
                        + "ML call, so the analysis path is not actually decoupled",
                        elapsedMs)
                .isLessThan(1000);
    }

    @Test
    void assessmentIsEventuallyWrittenByTheAsyncPath() {
        ML.setBand("HIGH");
        long before = assessments.count();

        rest.postForEntity(url("/api/v1/telemetry"), authed(telemetry("P003", 121)), String.class);

        await().atMost(Duration.ofSeconds(15))
                .pollInterval(Duration.ofMillis(200))
                .untilAsserted(() -> assertThat(assessments.count()).isGreaterThan(before));

        var latest = assessments.latestForPatient("P003").orElseThrow();
        assertThat(latest.riskBand()).isEqualTo("HIGH");
        assertThat(latest.mlAvailable()).isTrue();
        assertThat(latest.summaryProvider()).isNotBlank();
        assertThat(latest.summaryText()).isNotBlank();
        // No LLM is configured in tests, so the deterministic tier must answer.
        assertThat(latest.summaryProvider()).isEqualTo("rule-based");
    }

    /**
     * Degraded mode: with triage unreachable the reading is still accepted and
     * an assessment is still recorded, flagged as having no model output.
     */
    @Test
    void mlFailureDegradesGracefullyWithoutRejectingTelemetry() {
        ML.setStatus(500);

        ResponseEntity<String> res = rest.postForEntity(
                url("/api/v1/telemetry"), authed(telemetry("P004", 84)), String.class);
        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.ACCEPTED);

        await().atMost(Duration.ofSeconds(15))
                .pollInterval(Duration.ofMillis(200))
                .untilAsserted(() -> assertThat(
                        assessments.latestForPatient("P004")).isPresent());

        var latest = assessments.latestForPatient("P004").orElseThrow();
        assertThat(latest.mlAvailable()).isFalse();
        assertThat(latest.riskBand()).isEqualTo("UNKNOWN");
        // The deterministic tier still describes the numbers accurately.
        assertThat(latest.summaryText()).contains("- ");
        assertThat(latest.summaryProvider()).isEqualTo("rule-based");
    }

    @Test
    void mlTimeoutIsTreatedAsUnavailable() {
        ML.setDelayMs(4000); // read timeout is 1500ms in this test context

        rest.postForEntity(url("/api/v1/telemetry"), authed(telemetry("P002", 77)), String.class);

        await().atMost(Duration.ofSeconds(20))
                .pollInterval(Duration.ofMillis(250))
                .untilAsserted(() -> {
                    var latest = assessments.latestForPatient("P002");
                    assertThat(latest).isPresent();
                    assertThat(latest.get().mlAvailable()).isFalse();
                });
    }

    // ------------------------------------------------------------ read paths

    @Test
    void vitalsEndpointReturnsNewestFirst() throws Exception {
        for (int i = 0; i < 3; i++) {
            rest.postForEntity(url("/api/v1/telemetry"),
                    authed(telemetry("P001", 70 + i)), String.class);
        }

        ResponseEntity<String> res = rest.exchange(
                url("/api/v1/patients/P001/vitals?limit=3"),
                HttpMethod.GET, authed(null), String.class);

        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.OK);
        JsonNode readingsNode = MAPPER.readTree(res.getBody()).get("readings");
        assertThat(readingsNode.size()).isEqualTo(3);

        for (int i = 0; i < readingsNode.size() - 1; i++) {
            String a = readingsNode.get(i).get("observedAt").asText();
            String b = readingsNode.get(i + 1).get("observedAt").asText();
            assertThat(a.compareTo(b)).isGreaterThanOrEqualTo(0);
        }
    }

    @Test
    void unknownPatientReturns404() {
        ResponseEntity<String> res = rest.exchange(
                url("/api/v1/patients/NOPE/vitals"),
                HttpMethod.GET, authed(null), String.class);
        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
    }

    @Test
    void synchronousAnalyzeEndpointReturnsAnAssessment() throws Exception {
        rest.postForEntity(url("/api/v1/telemetry"), authed(telemetry("P001", 95)), String.class);

        ResponseEntity<String> res = rest.exchange(
                url("/api/v1/patients/P001/analyze"),
                HttpMethod.POST, authed(null), String.class);

        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.OK);
        JsonNode body = MAPPER.readTree(res.getBody());
        assertThat(body.get("riskBand").asText()).isNotBlank();
        assertThat(body.get("summary").asText()).contains("- ");
        assertThat(body.get("disclaimer").asText()).contains("Not a medical device");
    }

    @Test
    void news2BreakdownSurvivesTheRoundTripToPostgres() throws Exception {
        // The breakdown is what makes a score checkable by hand, so it has to
        // arrive intact through JSONB rather than being silently dropped.
        rest.postForEntity(url("/api/v1/telemetry"), authed(telemetry("P001", 104)),
                String.class);

        ResponseEntity<String> res = rest.exchange(
                url("/api/v1/patients/P001/analyze"),
                HttpMethod.POST, authed(null), String.class);

        JsonNode body = MAPPER.readTree(res.getBody());
        JsonNode breakdown = body.get("news2PerParameter");

        assertThat(breakdown).isNotNull();
        assertThat(breakdown.get("respiratory_rate").asInt()).isEqualTo(2);
        assertThat(breakdown.get("pulse").asInt()).isEqualTo(2);
        assertThat(breakdown.get("spo2").asInt()).isEqualTo(1);

        // The parts must sum to the reported total, or the UI would show a
        // breakdown that contradicts the headline number.
        int sum = 0;
        for (JsonNode v : breakdown) {
            sum += v.asInt();
        }
        assertThat(sum).isEqualTo(body.get("news2Total").asInt());
    }

    @Test
    void breakdownIsAbsentRatherThanInventedWhenTriageIsDown() {
        ML.setStatus(500);

        rest.postForEntity(url("/api/v1/telemetry"), authed(telemetry("P004", 88)),
                String.class);

        await().atMost(Duration.ofSeconds(15))
                .pollInterval(Duration.ofMillis(200))
                .untilAsserted(() -> assertThat(
                        assessments.latestForPatient("P004")).isPresent());

        var latest = assessments.latestForPatient("P004").orElseThrow();
        assertThat(latest.mlAvailable()).isFalse();
        assertThat(latest.news2PerParameterJson()).isNull();
    }

    @Test
    void patientListIncludesLatestRiskBand() throws Exception {
        ResponseEntity<String> res = rest.exchange(
                url("/api/v1/patients"), HttpMethod.GET, authed(null), String.class);

        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.OK);
        JsonNode patients = MAPPER.readTree(res.getBody()).get("patients");
        assertThat(patients.size()).isGreaterThanOrEqualTo(4);
    }

    @Test
    void providerEndpointReportsTheActiveCascade() throws Exception {
        ResponseEntity<String> res = rest.exchange(
                url("/api/v1/system/providers"), HttpMethod.GET, authed(null), String.class);

        JsonNode body = MAPPER.readTree(res.getBody());
        // With no LLM configured, only the deterministic tier is live.
        assertThat(body.get("active").toString()).contains("rule-based");
    }
}
