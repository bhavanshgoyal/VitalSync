package com.vitalsync.service.summary;

import com.vitalsync.domain.VitalReading;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;

/**
 * Terminal tier: deterministic template summarization.
 *
 * <p>This is what makes the cascade total. It has no network dependency, no
 * model, and no failure mode beyond a JVM error, so a summary is always
 * produced even with every LLM tier down. It is also the reason the system can
 * claim availability independent of any generative provider.
 */
@Component
@Order(300)
public class RuleBasedProvider implements SummaryProvider {

    public static final String NAME = "rule-based";

    @Override
    public String name() {
        return NAME;
    }

    @Override
    public int order() {
        return 300;
    }

    @Override
    public boolean available() {
        return true;
    }

    @Override
    public Optional<String> summarize(SummaryRequest req) {
        VitalReading r = req.latest();
        List<String> bullets = new ArrayList<>(3);

        String trend = "";
        if (req.window() != null && req.window().size() > 1) {
            VitalReading oldest = req.window().get(req.window().size() - 1);
            double dHr = r.heartRate() - oldest.heartRate();
            double dSpo2 = r.spo2() - oldest.spo2();
            trend = String.format(Locale.ROOT,
                    " Across the last %d readings heart rate moved %+.0f bpm and "
                            + "SpO2 %+.1f%%.",
                    req.window().size(), dHr, dSpo2);
        }

        bullets.add(String.format(Locale.ROOT,
                "- Physiological status: heart rate %.0f bpm, blood pressure "
                        + "%.0f/%.0f mmHg, SpO2 %.1f%%, respiratory rate %.0f "
                        + "breaths/min, temperature %.1f C.%s",
                r.heartRate(), r.systolicBp(), r.diastolicBp(), r.spo2(),
                r.respiratoryRate(), r.temperatureC(), trend));

        List<String> deviations = new ArrayList<>();
        if (r.heartRate() > 90) {
            deviations.add(String.format(Locale.ROOT, "heart rate %.0f bpm above 90", r.heartRate()));
        } else if (r.heartRate() < 51) {
            deviations.add(String.format(Locale.ROOT, "heart rate %.0f bpm below 51", r.heartRate()));
        }
        if (r.spo2() < 96) {
            deviations.add(String.format(Locale.ROOT, "SpO2 %.1f%% below 96%%", r.spo2()));
        }
        if (r.systolicBp() < 111) {
            deviations.add(String.format(Locale.ROOT, "systolic BP %.0f mmHg below 111", r.systolicBp()));
        } else if (r.systolicBp() > 219) {
            deviations.add(String.format(Locale.ROOT, "systolic BP %.0f mmHg above 219", r.systolicBp()));
        }
        if (r.respiratoryRate() > 20) {
            deviations.add(String.format(Locale.ROOT, "respiratory rate %.0f above 20", r.respiratoryRate()));
        } else if (r.respiratoryRate() < 12) {
            deviations.add(String.format(Locale.ROOT, "respiratory rate %.0f below 12", r.respiratoryRate()));
        }
        if (r.temperatureC() > 38.0) {
            deviations.add(String.format(Locale.ROOT, "temperature %.1f C above 38.0", r.temperatureC()));
        } else if (r.temperatureC() <= 36.0) {
            deviations.add(String.format(Locale.ROOT, "temperature %.1f C at or below 36.0", r.temperatureC()));
        }
        if (!r.alert()) {
            deviations.add("not alert on the AVPU scale");
        }
        if (r.onOxygen()) {
            deviations.add("receiving supplemental oxygen");
        }

        bullets.add(deviations.isEmpty()
                ? "- Deviations: no parameter falls outside the usual adult reference ranges."
                : "- Deviations: " + String.join("; ", deviations) + ".");

        bullets.add(String.format(Locale.ROOT,
                "- Suggested review priority: %s (NEWS2 %s, model band %s). "
                        + "Generated deterministically without a language model; "
                        + "a qualified clinician must confirm.",
                priority(req.news2Band(), req.riskBand()),
                req.news2Total() == null ? "unavailable" : req.news2Total().toString(),
                req.riskBand() == null ? "unavailable" : req.riskBand()));

        return Optional.of(String.join("\n", bullets));
    }

    private static String priority(String news2Band, String modelBand) {
        String band = news2Band != null ? news2Band : modelBand;
        if (band == null) {
            return "routine monitoring";
        }
        return switch (band) {
            case "HIGH" -> "urgent clinical review";
            case "MEDIUM" -> "prompt clinical review";
            default -> "routine monitoring";
        };
    }
}
