package com.vitalsync.service;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.vitalsync.domain.VitalReading;
import java.util.Map;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

/**
 * Client for the Python triage service.
 *
 * <p>Failure here must never propagate as an error to the ingestion path. A
 * telemetry write has already been durably persisted by the time this is
 * called; if triage is unavailable the assessment is recorded as degraded, and
 * the reading can be re-analysed later.
 */
@Component
public class MlClient {

    private static final Logger log = LoggerFactory.getLogger(MlClient.class);

    private final RestClient restClient;

    public MlClient(RestClient.Builder builder,
                    @Value("${vitalsync.ml.base-url}") String baseUrl) {
        this.restClient = builder.baseUrl(baseUrl).build();
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record News2Block(
            int total,
            String band,
            Integer max_single,
            Map<String, Integer> per_parameter) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record PredictResponse(
            String risk,
            Map<String, Double> probabilities,
            Double confidence,
            News2Block news2,
            Map<String, Double> derived,
            String model_version,
            Double inference_ms) {}

    /** Returns empty when the ML service is unreachable or returns an error. */
    public Optional<PredictResponse> predict(VitalReading r) {
        var body = Map.of(
                "heart_rate", r.heartRate(),
                "spo2", r.spo2(),
                "temperature_c", r.temperatureC(),
                "respiratory_rate", r.respiratoryRate(),
                "systolic_bp", r.systolicBp(),
                "diastolic_bp", r.diastolicBp(),
                "on_oxygen", r.onOxygen(),
                "alert", r.alert());
        try {
            PredictResponse response = restClient.post()
                    .uri("/predict")
                    .body(body)
                    .retrieve()
                    .body(PredictResponse.class);
            return Optional.ofNullable(response);
        } catch (Exception e) {
            log.warn("ML service unavailable for patient {}: {}",
                    r.patientId(), e.getMessage());
            return Optional.empty();
        }
    }

    public boolean healthy() {
        try {
            restClient.get().uri("/health").retrieve().toBodilessEntity();
            return true;
        } catch (Exception e) {
            return false;
        }
    }
}
