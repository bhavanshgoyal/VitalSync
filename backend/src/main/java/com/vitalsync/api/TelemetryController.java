package com.vitalsync.api;

import com.vitalsync.api.dto.Dtos;
import com.vitalsync.domain.VitalReading;
import com.vitalsync.service.TelemetryService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Telemetry ingestion.
 *
 * <p>Returns 202 Accepted, not 200: the reading is durably stored, but the
 * risk assessment it triggers has not run yet. Returning 200 would imply the
 * analysis was complete and would make the response a lie under load.
 */
@RestController
@RequestMapping("/api/v1/telemetry")
public class TelemetryController {

    private final TelemetryService telemetryService;

    public TelemetryController(TelemetryService telemetryService) {
        this.telemetryService = telemetryService;
    }

    @PostMapping
    public ResponseEntity<Dtos.TelemetryAccepted> ingest(
            @Valid @RequestBody Dtos.TelemetryRequest request) {

        VitalReading reading = telemetryService.ingest(request);

        // Handed to the bounded executor; this call does not wait for triage or
        // for any language model.
        telemetryService.analyzeAsync(reading);

        return ResponseEntity.status(HttpStatus.ACCEPTED).body(
                new Dtos.TelemetryAccepted(
                        reading.id(),
                        reading.patientId(),
                        reading.observedAt(),
                        "accepted",
                        "Reading persisted. Risk analysis is running asynchronously."));
    }
}
