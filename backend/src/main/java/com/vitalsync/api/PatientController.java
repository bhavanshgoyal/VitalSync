package com.vitalsync.api;

import com.vitalsync.api.dto.Dtos;
import com.vitalsync.domain.RiskAssessment;
import com.vitalsync.domain.VitalReading;
import com.vitalsync.repo.PatientRepository;
import com.vitalsync.repo.RiskAssessmentRepository;
import com.vitalsync.repo.VitalReadingRepository;
import com.vitalsync.service.SummarizationService;
import com.vitalsync.service.TelemetryService;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/v1")
public class PatientController {

    private static final String DISCLAIMER =
            "Research prototype. Not a medical device. Not for clinical use.";

    private static final int MAX_LIMIT = 500;

    private final PatientRepository patients;
    private final VitalReadingRepository readings;
    private final RiskAssessmentRepository assessments;
    private final TelemetryService telemetryService;
    private final SummarizationService summarizer;

    public PatientController(
            PatientRepository patients,
            VitalReadingRepository readings,
            RiskAssessmentRepository assessments,
            TelemetryService telemetryService,
            SummarizationService summarizer) {
        this.patients = patients;
        this.readings = readings;
        this.assessments = assessments;
        this.telemetryService = telemetryService;
        this.summarizer = summarizer;
    }

    @GetMapping("/patients")
    public Dtos.PatientListResponse list() {
        List<Dtos.PatientSummary> out = new ArrayList<>();
        for (var p : patients.findAll()) {
            Optional<RiskAssessment> latest = assessments.latestForPatient(p.patientId());
            out.add(new Dtos.PatientSummary(
                    p.patientId(),
                    p.displayName(),
                    p.age(),
                    p.sex(),
                    readings.countForPatient(p.patientId()),
                    latest.map(RiskAssessment::riskBand).orElse(null),
                    latest.map(RiskAssessment::news2Total).orElse(null),
                    latest.map(RiskAssessment::createdAt).orElse(null)));
        }
        return new Dtos.PatientListResponse(out);
    }

    @GetMapping("/patients/{patientId}/vitals")
    public Dtos.ReadingListResponse vitals(
            @PathVariable String patientId,
            @RequestParam(defaultValue = "50") int limit) {

        requirePatient(patientId);
        int bounded = Math.clamp(limit, 1, MAX_LIMIT);
        List<Dtos.ReadingView> views = readings.recentForPatient(patientId, bounded)
                .stream()
                .map(PatientController::toView)
                .toList();
        return new Dtos.ReadingListResponse(patientId, views.size(), views);
    }

    @GetMapping("/patients/{patientId}/risk/latest")
    public ResponseEntity<Dtos.RiskView> latestRisk(@PathVariable String patientId) {
        requirePatient(patientId);
        return assessments.latestForPatient(patientId)
                .map(a -> ResponseEntity.ok(toView(a)))
                .orElseGet(() -> ResponseEntity.noContent().build());
    }

    /**
     * Forces a synchronous analysis of the most recent reading.
     *
     * <p>Exists for the demo and the benchmarks. The normal path is the
     * asynchronous one triggered by ingestion; this endpoint deliberately waits
     * so a caller can measure end-to-end analysis latency.
     */
    @PostMapping("/patients/{patientId}/analyze")
    public ResponseEntity<Dtos.RiskView> analyze(@PathVariable String patientId) {
        requirePatient(patientId);
        List<VitalReading> recent = readings.recentForPatient(patientId, 1);
        if (recent.isEmpty()) {
            throw new ResponseStatusException(
                    HttpStatus.NOT_FOUND, "No readings for patient " + patientId);
        }
        return ResponseEntity.ok(toView(telemetryService.analyze(recent.get(0))));
    }

    /** Which summarization tiers are currently live. */
    @GetMapping("/system/providers")
    public Map<String, Object> providers() {
        return Map.of(
                "active", summarizer.activeProviders(),
                "counts", assessments.providerCounts(),
                "faithfulness", assessments.faithfulnessByProvider(),
                "totalAssessments", assessments.count());
    }

    private void requirePatient(String patientId) {
        if (!patients.exists(patientId)) {
            throw new ResponseStatusException(
                    HttpStatus.NOT_FOUND, "Unknown patient " + patientId);
        }
    }

    private static Dtos.ReadingView toView(VitalReading r) {
        return new Dtos.ReadingView(
                r.id(), r.patientId(), r.observedAt(),
                r.heartRate(), r.spo2(), r.temperatureC(), r.respiratoryRate(),
                r.systolicBp(), r.diastolicBp(), r.glucoseMgdl(),
                r.shockIndex(), r.pulsePressure(), r.mapMmhg());
    }

    private static Dtos.RiskView toView(RiskAssessment a) {
        Map<String, Double> probs = new LinkedHashMap<>();
        if (a.probLow() != null) probs.put("LOW", a.probLow());
        if (a.probMedium() != null) probs.put("MEDIUM", a.probMedium());
        if (a.probHigh() != null) probs.put("HIGH", a.probHigh());

        return new Dtos.RiskView(
                a.id(), a.patientId(), a.readingId(), a.riskBand(), a.confidence(),
                probs.isEmpty() ? null : probs,
                a.news2Total(), a.news2Band(), a.modelVersion(),
                a.mlLatencyMs(), a.mlAvailable(),
                a.summaryText(), a.summaryProvider(), a.summaryLatencyMs(),
                a.summaryFaithful(),
                a.createdAt(), DISCLAIMER);
    }
}
