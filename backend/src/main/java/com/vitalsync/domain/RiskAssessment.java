package com.vitalsync.domain;

import java.time.Instant;

public record RiskAssessment(
        Long id,
        String patientId,
        Long readingId,
        String riskBand,
        Double confidence,
        Double probLow,
        Double probMedium,
        Double probHigh,
        Integer news2Total,
        String news2Band,
        String news2PerParameterJson,
        String modelVersion,
        Double mlLatencyMs,
        boolean mlAvailable,
        String summaryText,
        String summaryProvider,
        Double summaryLatencyMs,
        Boolean summaryFaithful,
        String summaryFaithfulnessProblems,
        Instant createdAt) {
}
