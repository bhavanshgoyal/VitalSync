package com.vitalsync.service;

import com.vitalsync.api.dto.Dtos;
import com.vitalsync.domain.RiskAssessment;
import com.vitalsync.domain.VitalReading;
import com.vitalsync.repo.PatientRepository;
import com.vitalsync.repo.RiskAssessmentRepository;
import com.vitalsync.repo.VitalReadingRepository;
import com.vitalsync.service.summary.SummaryRequest;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

/**
 * Ingestion and analysis.
 *
 * <p>The central architectural rule lives here: {@link #ingest} performs only
 * validation and a durable write, then hands analysis to a bounded executor.
 * Telemetry throughput is therefore bounded by the database, not by whichever
 * language model happens to be answering. Analysis is intentionally allowed to
 * lag behind ingestion.
 */
@Service
public class TelemetryService {

    private static final Logger log = LoggerFactory.getLogger(TelemetryService.class);

    private static final ObjectMapper JSON = new ObjectMapper();

    private final PatientRepository patients;
    private final VitalReadingRepository readings;
    private final RiskAssessmentRepository assessments;
    private final MlClient mlClient;
    private final SummarizationService summarizer;

    public TelemetryService(
            PatientRepository patients,
            VitalReadingRepository readings,
            RiskAssessmentRepository assessments,
            MlClient mlClient,
            SummarizationService summarizer) {
        this.patients = patients;
        this.readings = readings;
        this.assessments = assessments;
        this.mlClient = mlClient;
        this.summarizer = summarizer;
    }

    /** Synchronous portion: persist and return. Never calls the ML or LLM tiers. */
    public VitalReading ingest(Dtos.TelemetryRequest req) {
        patients.ensureExists(req.patientId());

        double sbp = req.systolicBp();
        double dbp = req.diastolicBp();
        VitalReading reading = new VitalReading(
                null,
                req.patientId(),
                req.observedAtOrNow(),
                Instant.now(),
                req.heartRate(),
                req.spo2(),
                req.temperatureC(),
                req.respiratoryRate(),
                sbp,
                dbp,
                req.glucoseMgdl(),
                req.onOxygenOrFalse(),
                req.alertOrTrue(),
                VitalReading.shockIndex(req.heartRate(), sbp),
                VitalReading.pulsePressure(sbp, dbp),
                VitalReading.meanArterialPressure(sbp, dbp));

        long id = readings.insert(reading);
        return readings.findById(id);
    }

    /**
     * Serialises the per-parameter breakdown for storage.
     *
     * <p>A serialisation failure must not lose the assessment: the breakdown
     * is explanatory detail, while the band and score are the result.
     */
    private static String toJson(java.util.Map<String, Integer> perParameter) {
        if (perParameter == null || perParameter.isEmpty()) {
            return null;
        }
        try {
            return JSON.writeValueAsString(perParameter);
        } catch (JsonProcessingException e) {
            log.warn("Could not serialise NEWS2 breakdown: {}", e.getMessage());
            return null;
        }
    }

    /** Asynchronous portion: triage, then summarize, then persist the assessment. */
    @Async("analysisExecutor")
    public void analyzeAsync(VitalReading reading) {
        try {
            analyze(reading);
        } catch (Exception e) {
            // An analysis failure must not affect the already-durable reading.
            log.error("Analysis failed for reading {}: {}", reading.id(), e.getMessage(), e);
        }
    }

    /** Blocking analysis, used by the async path and by the on-demand endpoint. */
    public RiskAssessment analyze(VitalReading reading) {
        long mlStart = System.nanoTime();
        Optional<MlClient.PredictResponse> prediction = mlClient.predict(reading);
        double mlMs = (System.nanoTime() - mlStart) / 1_000_000.0;

        String band;
        Double confidence;
        Map<String, Double> probs;
        Integer news2Total = null;
        String news2Band = null;
        String news2Breakdown = null;
        String modelVersion;
        boolean mlAvailable = prediction.isPresent();

        if (prediction.isPresent()) {
            var p = prediction.get();
            band = p.risk();
            confidence = p.confidence();
            probs = p.probabilities() == null ? Map.of() : p.probabilities();
            if (p.news2() != null) {
                news2Total = p.news2().total();
                news2Band = p.news2().band();
                news2Breakdown = toJson(p.news2().per_parameter());
            }
            modelVersion = p.model_version();
        } else {
            // Degraded mode: the triage service is down, so the band is marked
            // unknown rather than guessed. The reading is still summarised, and
            // the deterministic tier still describes the numbers accurately.
            band = "UNKNOWN";
            confidence = null;
            probs = Map.of();
            modelVersion = "unavailable";
        }

        List<VitalReading> window =
                readings.recentForPatient(reading.patientId(), SummaryRequest.MAX_WINDOW);

        SummaryRequest request = new SummaryRequest(
                reading.patientId(), reading, window, band, confidence, news2Total, news2Band);

        SummarizationService.Result summary = summarizer.summarize(request);

        RiskAssessment assessment = new RiskAssessment(
                null,
                reading.patientId(),
                reading.id(),
                band,
                confidence,
                probs.get("LOW"),
                probs.get("MEDIUM"),
                probs.get("HIGH"),
                news2Total,
                news2Band,
                news2Breakdown,
                modelVersion,
                mlMs,
                mlAvailable,
                summary.text(),
                summary.provider(),
                summary.latencyMs(),
                summary.faithful(),
                summary.faithfulnessProblems().isEmpty()
                        ? null : String.join("; ", summary.faithfulnessProblems()),
                Instant.now());

        long id = assessments.insert(assessment);
        log.debug("Assessment {} for patient {}: band={} provider={}",
                id, reading.patientId(), band, summary.provider());
        return assessments.latestForPatient(reading.patientId()).orElse(assessment);
    }
}
