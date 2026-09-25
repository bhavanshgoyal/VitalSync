package com.vitalsync.api.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.time.Instant;
import java.util.List;
import java.util.Map;

/**
 * Wire types for the REST API.
 *
 * <p>Bounds on the telemetry request are plausibility limits, deliberately far
 * wider than clinical normal ranges: their job is to reject impossible sensor
 * output, not to decide what is healthy. Clinical interpretation happens in the
 * triage layer, never in bean validation.
 */
public final class Dtos {

    private Dtos() {}

    public record TokenRequest(
            @NotBlank String username,
            @NotBlank String password) {}

    public record TokenResponse(
            String token,
            String tokenType,
            long expiresInSeconds,
            String subject,
            String role) {}

    public record TelemetryRequest(
            @NotBlank String patientId,

            @NotNull @DecimalMin("20") @DecimalMax("300")
            Double heartRate,

            @NotNull @DecimalMin("50") @DecimalMax("100")
            Double spo2,

            @NotNull @DecimalMin("25") @DecimalMax("45")
            Double temperatureC,

            @NotNull @DecimalMin("3") @DecimalMax("70")
            Double respiratoryRate,

            @NotNull @DecimalMin("40") @DecimalMax("300")
            Double systolicBp,

            @NotNull @DecimalMin("20") @DecimalMax("200")
            Double diastolicBp,

            @DecimalMin("10") @DecimalMax("900")
            Double glucoseMgdl,

            Boolean onOxygen,
            Boolean alert,
            Instant observedAt) {

        public boolean onOxygenOrFalse() {
            return onOxygen != null && onOxygen;
        }

        public boolean alertOrTrue() {
            return alert == null || alert;
        }

        public Instant observedAtOrNow() {
            return observedAt == null ? Instant.now() : observedAt;
        }
    }

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record TelemetryAccepted(
            long readingId,
            String patientId,
            Instant observedAt,
            String status,
            String note) {}

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record ReadingView(
            long id,
            String patientId,
            Instant observedAt,
            double heartRate,
            double spo2,
            double temperatureC,
            double respiratoryRate,
            double systolicBp,
            double diastolicBp,
            Double glucoseMgdl,
            Double shockIndex,
            Double pulsePressure,
            Double mapMmhg) {}

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record RiskView(
            long id,
            String patientId,
            Long readingId,
            String riskBand,
            Double confidence,
            Map<String, Double> probabilities,
            Integer news2Total,
            String news2Band,
            String modelVersion,
            Double mlLatencyMs,
            boolean mlAvailable,
            String summary,
            String summaryProvider,
            Double summaryLatencyMs,
            Boolean summaryFaithful,
            Instant createdAt,
            String disclaimer) {}

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record PatientSummary(
            String patientId,
            String displayName,
            Integer age,
            String sex,
            long readingCount,
            String latestRiskBand,
            Integer latestNews2,
            Instant latestAssessmentAt) {}

    public record PatientListResponse(List<PatientSummary> patients) {}

    public record ReadingListResponse(String patientId, int count, List<ReadingView> readings) {}
}
