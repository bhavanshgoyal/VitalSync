package com.vitalsync.repo;

import com.vitalsync.domain.RiskAssessment;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Collectors;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

@Repository
public class RiskAssessmentRepository {

    private final JdbcClient jdbc;

    public RiskAssessmentRepository(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    private static final RowMapper<RiskAssessment> MAPPER = (rs, n) -> new RiskAssessment(
            rs.getLong("id"),
            rs.getString("patient_id"),
            (Long) rs.getObject("reading_id"),
            rs.getString("risk_band"),
            (Double) rs.getObject("confidence"),
            (Double) rs.getObject("prob_low"),
            (Double) rs.getObject("prob_medium"),
            (Double) rs.getObject("prob_high"),
            (Integer) rs.getObject("news2_total"),
            rs.getString("news2_band"),
            rs.getString("model_version"),
            (Double) rs.getObject("ml_latency_ms"),
            rs.getBoolean("ml_available"),
            rs.getString("summary_text"),
            rs.getString("summary_provider"),
            (Double) rs.getObject("summary_latency_ms"),
            (Boolean) rs.getObject("summary_faithful"),
            rs.getString("summary_faithfulness_problems"),
            rs.getTimestamp("created_at").toInstant());

    public long insert(RiskAssessment a) {
        return jdbc.sql("""
                INSERT INTO risk_assessments (
                    patient_id, reading_id, risk_band, confidence,
                    prob_low, prob_medium, prob_high,
                    news2_total, news2_band, model_version,
                    ml_latency_ms, ml_available,
                    summary_text, summary_provider, summary_latency_ms,
                    summary_faithful, summary_faithfulness_problems)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                RETURNING id
                """)
                .params(
                        a.patientId(), a.readingId(), a.riskBand(), a.confidence(),
                        a.probLow(), a.probMedium(), a.probHigh(),
                        a.news2Total(), a.news2Band(), a.modelVersion(),
                        a.mlLatencyMs(), a.mlAvailable(),
                        a.summaryText(), a.summaryProvider(), a.summaryLatencyMs(),
                        a.summaryFaithful(), a.summaryFaithfulnessProblems())
                .query(Long.class)
                .single();
    }

    public Optional<RiskAssessment> latestForPatient(String patientId) {
        return jdbc.sql("""
                SELECT * FROM risk_assessments
                WHERE patient_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """)
                .param(patientId)
                .query(MAPPER)
                .optional();
    }

    public List<RiskAssessment> recentForPatient(String patientId, int limit) {
        return jdbc.sql("""
                SELECT * FROM risk_assessments
                WHERE patient_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """)
                .params(patientId, limit)
                .query(MAPPER)
                .list();
    }

    /**
     * Provider counts for the resilience experiment.
     *
     * <p>Which tier answered is a measured result, so it is read back out of the
     * table rather than scraped from application logs.
     */
    public Map<String, Long> providerCounts() {
        return jdbc.sql("""
                SELECT summary_provider, COUNT(*) AS n
                FROM risk_assessments
                WHERE summary_provider IS NOT NULL
                GROUP BY summary_provider
                """)
                .query((rs, n) -> Map.entry(rs.getString("summary_provider"), rs.getLong("n")))
                .list()
                .stream()
                .collect(Collectors.toMap(Map.Entry::getKey, Map.Entry::getValue));
    }

    /** Faithfulness pass-rate per provider, for the summarization experiment. */
    public Map<String, Map<String, Long>> faithfulnessByProvider() {
        return jdbc.sql("""
                SELECT summary_provider,
                       COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE summary_faithful IS TRUE) AS faithful
                FROM risk_assessments
                WHERE summary_provider IS NOT NULL
                GROUP BY summary_provider
                """)
                .query((rs, n) -> Map.entry(
                        rs.getString("summary_provider"),
                        (Map<String, Long>) new java.util.LinkedHashMap<>(Map.of(
                                "total", rs.getLong("total"),
                                "faithful", rs.getLong("faithful")))))
                .list()
                .stream()
                .collect(Collectors.toMap(Map.Entry::getKey, Map.Entry::getValue));
    }

    public long count() {
        return jdbc.sql("SELECT COUNT(*) FROM risk_assessments").query(Long.class).single();
    }
}
