package com.vitalsync.domain;

import java.time.Instant;

public record Patient(
        String patientId,
        String displayName,
        Integer age,
        String sex,
        Instant createdAt) {
}
