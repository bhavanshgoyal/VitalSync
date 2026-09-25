package com.vitalsync.service.summary;

import com.vitalsync.domain.VitalReading;
import java.util.List;
import java.util.Locale;

/**
 * Bounded context handed to a summarization tier.
 *
 * <p>The window is deliberately small. Sending an unbounded history to an LLM
 * costs latency and tokens, and increases the chance the model narrates
 * something the numbers do not support. Trend deltas over a short window carry
 * most of the clinically relevant movement.
 */
public record SummaryRequest(
        String patientId,
        VitalReading latest,
        List<VitalReading> window,
        String riskBand,
        Double confidence,
        Integer news2Total,
        String news2Band) {

    /** Maximum readings a prompt may reference. */
    public static final int MAX_WINDOW = 10;

    public String promptContext() {
        StringBuilder sb = new StringBuilder();
        sb.append(String.format(Locale.ROOT,
                "Patient: %s%n"
                        + "Latest observation:%n"
                        + "- Heart rate: %.0f bpm%n"
                        + "- SpO2: %.1f %%%n"
                        + "- Blood pressure: %.0f/%.0f mmHg%n"
                        + "- Temperature: %.1f C%n"
                        + "- Respiratory rate: %.0f breaths/min%n"
                        + "- Shock index: %.2f%n",
                patientId,
                latest.heartRate(), latest.spo2(),
                latest.systolicBp(), latest.diastolicBp(),
                latest.temperatureC(), latest.respiratoryRate(),
                latest.shockIndex() == null ? Double.NaN : latest.shockIndex()));

        if (latest.glucoseMgdl() != null) {
            sb.append(String.format(Locale.ROOT, "- Glucose: %.0f mg/dL%n",
                    latest.glucoseMgdl()));
        }
        if (latest.onOxygen()) {
            sb.append("- Receiving supplemental oxygen%n".formatted());
        }
        if (!latest.alert()) {
            sb.append("- Not alert (CVPU on AVPU scale)\n");
        }

        sb.append(String.format(Locale.ROOT,
                "%nDeterministic NEWS2 score: %s (band %s)%n"
                        + "Model triage band: %s (confidence %.2f)%n",
                news2Total == null ? "unavailable" : news2Total.toString(),
                news2Band == null ? "unavailable" : news2Band,
                riskBand,
                confidence == null ? 0.0 : confidence));

        if (window != null && window.size() > 1) {
            VitalReading oldest = window.get(window.size() - 1);
            sb.append(String.format(Locale.ROOT,
                    "%nTrend over the last %d readings:%n"
                            + "- Heart rate %+.0f bpm%n"
                            + "- SpO2 %+.1f %%%n"
                            + "- Systolic BP %+.0f mmHg%n"
                            + "- Respiratory rate %+.0f breaths/min%n",
                    window.size(),
                    latest.heartRate() - oldest.heartRate(),
                    latest.spo2() - oldest.spo2(),
                    latest.systolicBp() - oldest.systolicBp(),
                    latest.respiratoryRate() - oldest.respiratoryRate()));
        }
        return sb.toString();
    }
}
