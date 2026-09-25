package com.vitalsync.domain;

import java.time.Instant;

/**
 * A persisted vital-sign observation.
 *
 * <p>Derived features are stored alongside the raw channels so that the read
 * path never recomputes them.
 */
public record VitalReading(
        Long id,
        String patientId,
        Instant observedAt,
        Instant recordedAt,
        double heartRate,
        double spo2,
        double temperatureC,
        double respiratoryRate,
        double systolicBp,
        double diastolicBp,
        Double glucoseMgdl,
        boolean onOxygen,
        boolean alert,
        Double shockIndex,
        Double pulsePressure,
        Double mapMmhg) {

    /** Shock index, guarded against a cuff reporting zero. */
    public static Double shockIndex(double heartRate, double systolicBp) {
        return systolicBp > 0 ? heartRate / systolicBp : null;
    }

    public static double pulsePressure(double systolicBp, double diastolicBp) {
        return systolicBp - diastolicBp;
    }

    public static double meanArterialPressure(double systolicBp, double diastolicBp) {
        return (systolicBp + 2.0 * diastolicBp) / 3.0;
    }
}
