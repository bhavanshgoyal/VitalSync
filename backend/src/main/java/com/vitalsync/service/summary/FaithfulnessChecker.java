package com.vitalsync.service.summary;

import com.vitalsync.domain.VitalReading;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Checks generated summaries against the numbers they were given.
 *
 * <p>The prompt tells the model not to invent findings. Prompts are not
 * enforcement. This verifies two properties that are mechanically checkable
 * and that cover the failure modes that actually matter here:
 *
 * <ol>
 *   <li><b>Numeric entailment.</b> Every number in the summary must correspond
 *       to a number the model was given, within a rounding tolerance. A summary
 *       that invents "SpO2 of 88%" for a patient at 94% is the single most
 *       dangerous output this system can produce.</li>
 *   <li><b>No diagnostic language.</b> The system is explicitly not a
 *       diagnostic device, so naming a condition is out of scope regardless of
 *       whether the guess is plausible.</li>
 * </ol>
 *
 * <p>This is a necessary-not-sufficient check. It cannot detect a fluent,
 * numerically-correct, clinically-wrong interpretation, and it is not a
 * substitute for clinician review. It catches fabrication, which is the class
 * of error a deterministic guard <em>can</em> catch.
 */
public final class FaithfulnessChecker {

    private FaithfulnessChecker() {}

    /** Numbers appearing in prose, including decimals. Ignores list markers. */
    private static final Pattern NUMBER = Pattern.compile("\\d+(?:\\.\\d+)?");

    /**
     * Measurement names that end in a digit.
     *
     * <p>"SpO2" and "NEWS2" would otherwise contribute a spurious "2" to the
     * numeric scan, which is not a value the model is claiming.
     */
    private static final Pattern NAME_WITH_TRAILING_DIGIT =
            Pattern.compile("(?i)\\b(spo|news)2\\b");

    /**
     * Terms that assert a condition rather than describe a measurement.
     *
     * <p>Deliberately conservative: it targets named conditions and explicit
     * diagnostic framing, not descriptive physiological vocabulary. Words like
     * "tachycardia" are descriptive of a measured rate and are allowed;
     * "sepsis" names a disease and is not.
     */
    private static final List<String> DIAGNOSTIC_TERMS = List.of(
            "sepsis", "septic", "pneumonia", "myocardial infarction", "heart attack",
            "stroke", "embolism", "covid", "influenza", "infection", "diagnosis",
            "diagnosed", "diagnose", "cancer", "copd", "asthma attack",
            "heart failure", "renal failure", "shock syndrome", "meningitis"
    );

    /**
     * Tolerance for matching a summary number to a source number.
     *
     * <p>Deliberately tiny. Legitimate restatements are handled by enumerating
     * the rounded forms of every source value in {@link #allowedValues}, so
     * this only needs to absorb floating-point representation error. A loose
     * tolerance here is actively dangerous: at +/-1.0 an invented lactate of
     * 4.7 matches a NEWS2 total of 5 and the fabrication passes unnoticed.
     */
    private static final double ABS_TOLERANCE = 0.05;

    public record Result(
            boolean faithful,
            List<String> unsupportedNumbers,
            List<String> diagnosticTerms,
            int numbersChecked) {

        public List<String> problems() {
            List<String> out = new ArrayList<>();
            if (!unsupportedNumbers.isEmpty()) {
                out.add("unsupported numbers: " + String.join(", ", unsupportedNumbers));
            }
            if (!diagnosticTerms.isEmpty()) {
                out.add("diagnostic language: " + String.join(", ", diagnosticTerms));
            }
            return out;
        }
    }

    /**
     * Builds the set of values a faithful summary is allowed to cite.
     *
     * <p>Includes the raw channels, the derived features, the NEWS2 score, and
     * the trend deltas the prompt supplied -- anything the model legitimately
     * saw. Integer truncations are added alongside rounded forms because models
     * routinely restate "96.5%" as "96%".
     */
    static Set<Double> allowedValues(SummaryRequest request) {
        Set<Double> allowed = new LinkedHashSet<>();
        VitalReading r = request.latest();

        addWithRoundings(allowed, r.heartRate());
        addWithRoundings(allowed, r.spo2());
        addWithRoundings(allowed, r.temperatureC());
        addWithRoundings(allowed, r.respiratoryRate());
        addWithRoundings(allowed, r.systolicBp());
        addWithRoundings(allowed, r.diastolicBp());
        if (r.glucoseMgdl() != null) {
            addWithRoundings(allowed, r.glucoseMgdl());
        }
        if (r.shockIndex() != null) {
            addWithRoundings(allowed, r.shockIndex());
        }
        if (r.pulsePressure() != null) {
            addWithRoundings(allowed, r.pulsePressure());
        }
        if (r.mapMmhg() != null) {
            addWithRoundings(allowed, r.mapMmhg());
        }
        if (request.news2Total() != null) {
            addWithRoundings(allowed, request.news2Total().doubleValue());
        }

        // Trend deltas and the window size are in the prompt, so they are fair
        // game for the model to restate.
        List<VitalReading> window = request.window();
        if (window != null && window.size() > 1) {
            VitalReading oldest = window.get(window.size() - 1);
            addWithRoundings(allowed, window.size());
            addWithRoundings(allowed, Math.abs(r.heartRate() - oldest.heartRate()));
            addWithRoundings(allowed, Math.abs(r.spo2() - oldest.spo2()));
            addWithRoundings(allowed, Math.abs(r.systolicBp() - oldest.systolicBp()));
            addWithRoundings(allowed,
                    Math.abs(r.respiratoryRate() - oldest.respiratoryRate()));
        }

        // Reference-range bounds the deterministic tier itself quotes, so a
        // model echoing "below 96%" is not flagged as fabricating.
        allowed.addAll(List.of(
                0.0, 1.0, 2.0, 3.0,
                36.0, 38.0, 39.0, 35.0,
                90.0, 91.0, 92.0, 94.0, 96.0, 100.0,
                110.0, 111.0, 12.0, 20.0, 21.0, 25.0, 50.0, 51.0, 130.0, 219.0, 220.0));
        return allowed;
    }

    private static void addWithRoundings(Set<Double> set, double value) {
        set.add(value);
        set.add((double) Math.round(value));
        set.add(Math.floor(value));
        set.add(Math.ceil(value));
        set.add(Math.round(value * 10.0) / 10.0);
        set.add(Math.round(value * 100.0) / 100.0);
    }

    public static Result check(String summary, SummaryRequest request) {
        if (summary == null || summary.isBlank()) {
            return new Result(false, List.of("<empty summary>"), List.of(), 0);
        }

        Set<Double> allowed = allowedValues(request);
        List<String> unsupported = new ArrayList<>();
        int checked = 0;

        String scannable = NAME_WITH_TRAILING_DIGIT.matcher(summary).replaceAll("$1");
        Matcher matcher = NUMBER.matcher(scannable);
        while (matcher.find()) {
            String token = matcher.group();
            double value;
            try {
                value = Double.parseDouble(token);
            } catch (NumberFormatException e) {
                continue;
            }
            checked++;
            boolean supported = allowed.stream()
                    .anyMatch(a -> Math.abs(a - value) <= ABS_TOLERANCE);
            if (!supported) {
                unsupported.add(token);
            }
        }

        String lower = summary.toLowerCase(Locale.ROOT);
        List<String> found = DIAGNOSTIC_TERMS.stream()
                .filter(lower::contains)
                .toList();

        return new Result(unsupported.isEmpty() && found.isEmpty(),
                unsupported, found, checked);
    }
}
