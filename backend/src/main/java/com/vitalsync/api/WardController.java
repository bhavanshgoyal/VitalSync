package com.vitalsync.api;

import com.vitalsync.repo.RiskAssessmentRepository;
import com.vitalsync.repo.WardRepository;
import com.vitalsync.service.MlClient;
import com.vitalsync.service.SummarizationService;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Read endpoints backing the ward board and the system view.
 */
@RestController
@RequestMapping("/api/v1")
public class WardController {

    private static final String DISCLAIMER =
            "Research prototype. Not a medical device. Not for clinical use.";

    /** Beyond this, a reading is presented as stale rather than current. */
    private static final Duration STALE_AFTER = Duration.ofSeconds(90);

    /** Ordering for triage: worst first. */
    private static final Map<String, Integer> BAND_ORDER =
            Map.of("HIGH", 0, "MEDIUM", 1, "UNKNOWN", 2, "LOW", 3);

    private final WardRepository ward;
    private final RiskAssessmentRepository assessments;
    private final SummarizationService summarizer;
    private final MlClient mlClient;
    private final String modelVersionHint;

    public WardController(
            WardRepository ward,
            RiskAssessmentRepository assessments,
            SummarizationService summarizer,
            MlClient mlClient,
            @Value("${vitalsync.ml.base-url}") String mlBaseUrl) {
        this.ward = ward;
        this.assessments = assessments;
        this.summarizer = summarizer;
        this.mlClient = mlClient;
        this.modelVersionHint = mlBaseUrl;
    }

    public record WardPatient(
            String patientId,
            String displayName,
            Integer age,
            String sex,
            long readingCount,
            Instant lastObservedAt,
            Long secondsSinceReading,
            boolean stale,
            Map<String, Double> vitals,
            String riskBand,
            Double confidence,
            Integer news2Total,
            String news2Band,
            Boolean mlAvailable,
            String summaryProvider,
            Instant assessedAt,
            List<Double> heartRateSeries) {}

    public record WardResponse(
            int count,
            Instant generatedAt,
            List<WardPatient> patients,
            String disclaimer) {}

    /**
     * The ward board.
     *
     * <p>Sorted by acuity, never alphabetically: a board ordered by name is how
     * a deteriorating patient ends up below the fold. Patients with no
     * assessment yet sort after the graded ones rather than being hidden.
     */
    @GetMapping("/ward")
    public WardResponse board(@RequestParam(defaultValue = "20") int sparkline) {
        Instant now = Instant.now();

        List<WardPatient> patients = new ArrayList<>();
        for (var r : ward.board(sparkline)) {
            Long age = r.lastObservedAt() == null
                    ? null
                    : Duration.between(r.lastObservedAt(), now).toSeconds();

            Map<String, Double> vitals = new LinkedHashMap<>();
            putIfPresent(vitals, "heartRate", r.heartRate());
            putIfPresent(vitals, "spo2", r.spo2());
            putIfPresent(vitals, "temperatureC", r.temperatureC());
            putIfPresent(vitals, "respiratoryRate", r.respiratoryRate());
            putIfPresent(vitals, "systolicBp", r.systolicBp());
            putIfPresent(vitals, "diastolicBp", r.diastolicBp());

            patients.add(new WardPatient(
                    r.patientId(), r.displayName(), r.age(), r.sex(),
                    r.readingCount(), r.lastObservedAt(), age,
                    age != null && age > STALE_AFTER.toSeconds(),
                    vitals,
                    r.riskBand(), r.confidence(), r.news2Total(), r.news2Band(),
                    r.mlAvailable(), r.summaryProvider(), r.assessedAt(),
                    r.heartRateSeries()));
        }

        patients.sort(Comparator
                .comparingInt((WardPatient p) ->
                        BAND_ORDER.getOrDefault(
                                p.riskBand() == null ? "UNKNOWN" : p.riskBand(), 2))
                .thenComparing(p -> p.news2Total() == null ? -1 : p.news2Total(),
                        Comparator.reverseOrder())
                .thenComparing(WardPatient::patientId));

        return new WardResponse(patients.size(), now, patients, DISCLAIMER);
    }

    public record SystemHealth(
            Instant generatedAt,
            boolean mlReachable,
            List<String> activeProviders,
            Map<String, Long> providerCounts,
            Map<String, Map<String, Long>> faithfulness,
            long totalAssessments,
            long degradedAssessments,
            String mlBaseUrl,
            String disclaimer) {}

    /**
     * Aggregate health for the system view.
     *
     * <p>{@code degradedAssessments} is the count recorded while triage was
     * unreachable. It is surfaced because a system that hides its degraded
     * history looks more reliable than it is.
     */
    @GetMapping("/system/health")
    public SystemHealth health() {
        return new SystemHealth(
                Instant.now(),
                mlClient.healthy(),
                summarizer.activeProviders(),
                assessments.providerCounts(),
                assessments.faithfulnessByProvider(),
                assessments.count(),
                assessments.countDegraded(),
                modelVersionHint,
                DISCLAIMER);
    }

    private static void putIfPresent(Map<String, Double> map, String key, Double value) {
        if (value != null) {
            map.put(key, value);
        }
    }
}
