package com.vitalsync.repo;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

/**
 * Read model for the ward board.
 *
 * <p>The board polls, so it is built from two set-based queries rather than the
 * per-patient loop the original roster endpoint used. That loop issued
 * 2N queries for N patients, which is invisible at four patients and the wrong
 * shape for anything larger.
 */
@Repository
public class WardRepository {

    private final JdbcClient jdbc;

    public WardRepository(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    public record WardRow(
            String patientId,
            String displayName,
            Integer age,
            String sex,
            long readingCount,
            Instant lastObservedAt,
            Double heartRate,
            Double spo2,
            Double temperatureC,
            Double respiratoryRate,
            Double systolicBp,
            Double diastolicBp,
            String riskBand,
            Double confidence,
            Integer news2Total,
            String news2Band,
            Boolean mlAvailable,
            String summaryProvider,
            Instant assessedAt,
            List<Double> heartRateSeries) {}

    /**
     * One row per patient with their latest reading and latest assessment.
     *
     * <p>Uses {@code DISTINCT ON}, the PostgreSQL-idiomatic "latest row per
     * group": cheaper and clearer here than a window function with an outer
     * filter, and it keeps the ordering explicit.
     */
    public List<WardRow> board(int sparklinePoints) {
        var latest = jdbc.sql("""
                WITH latest_reading AS (
                    SELECT DISTINCT ON (patient_id)
                           patient_id, observed_at, heart_rate, spo2, temperature_c,
                           respiratory_rate, systolic_bp, diastolic_bp
                    FROM vital_readings
                    ORDER BY patient_id, observed_at DESC
                ),
                latest_assessment AS (
                    SELECT DISTINCT ON (patient_id)
                           patient_id, risk_band, confidence, news2_total, news2_band,
                           ml_available, summary_provider, created_at
                    FROM risk_assessments
                    ORDER BY patient_id, created_at DESC, id DESC
                ),
                counts AS (
                    SELECT patient_id, COUNT(*) AS n
                    FROM vital_readings
                    GROUP BY patient_id
                )
                SELECT p.patient_id, p.display_name, p.age, p.sex,
                       COALESCE(c.n, 0)        AS reading_count,
                       r.observed_at, r.heart_rate, r.spo2, r.temperature_c,
                       r.respiratory_rate, r.systolic_bp, r.diastolic_bp,
                       a.risk_band, a.confidence, a.news2_total, a.news2_band,
                       a.ml_available, a.summary_provider, a.created_at AS assessed_at
                FROM patients p
                LEFT JOIN latest_reading   r ON r.patient_id = p.patient_id
                LEFT JOIN latest_assessment a ON a.patient_id = p.patient_id
                LEFT JOIN counts           c ON c.patient_id = p.patient_id
                ORDER BY p.patient_id
                """)
                .query((rs, n) -> {
                    Timestamp observed = rs.getTimestamp("observed_at");
                    Timestamp assessed = rs.getTimestamp("assessed_at");
                    return new WardRow(
                            rs.getString("patient_id"),
                            rs.getString("display_name"),
                            (Integer) rs.getObject("age"),
                            rs.getString("sex"),
                            rs.getLong("reading_count"),
                            observed == null ? null : observed.toInstant(),
                            (Double) rs.getObject("heart_rate"),
                            (Double) rs.getObject("spo2"),
                            (Double) rs.getObject("temperature_c"),
                            (Double) rs.getObject("respiratory_rate"),
                            (Double) rs.getObject("systolic_bp"),
                            (Double) rs.getObject("diastolic_bp"),
                            rs.getString("risk_band"),
                            (Double) rs.getObject("confidence"),
                            (Integer) rs.getObject("news2_total"),
                            rs.getString("news2_band"),
                            (Boolean) rs.getObject("ml_available"),
                            rs.getString("summary_provider"),
                            assessed == null ? null : assessed.toInstant(),
                            List.of());
                })
                .list();

        Map<String, List<Double>> series = heartRateSeries(sparklinePoints);

        List<WardRow> out = new ArrayList<>(latest.size());
        for (WardRow row : latest) {
            out.add(new WardRow(
                    row.patientId(), row.displayName(), row.age(), row.sex(),
                    row.readingCount(), row.lastObservedAt(), row.heartRate(),
                    row.spo2(), row.temperatureC(), row.respiratoryRate(),
                    row.systolicBp(), row.diastolicBp(), row.riskBand(),
                    row.confidence(), row.news2Total(), row.news2Band(),
                    row.mlAvailable(), row.summaryProvider(), row.assessedAt(),
                    series.getOrDefault(row.patientId(), List.of())));
        }
        return out;
    }

    /** Recent heart-rate points per patient, oldest first, in one query. */
    private Map<String, List<Double>> heartRateSeries(int points) {
        int bounded = Math.clamp(points, 2, 100);
        var rows = jdbc.sql("""
                SELECT patient_id, heart_rate, observed_at
                FROM (
                    SELECT patient_id, heart_rate, observed_at,
                           ROW_NUMBER() OVER (
                               PARTITION BY patient_id ORDER BY observed_at DESC
                           ) AS rn
                    FROM vital_readings
                ) ranked
                WHERE rn <= ?
                ORDER BY patient_id, observed_at ASC
                """)
                .param(bounded)
                .query((rs, n) -> Map.entry(
                        rs.getString("patient_id"), rs.getDouble("heart_rate")))
                .list();

        Map<String, List<Double>> out = new LinkedHashMap<>();
        for (var e : rows) {
            out.computeIfAbsent(e.getKey(), k -> new ArrayList<>()).add(e.getValue());
        }
        return out;
    }
}
