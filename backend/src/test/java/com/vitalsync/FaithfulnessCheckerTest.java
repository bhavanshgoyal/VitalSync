package com.vitalsync;

import static org.assertj.core.api.Assertions.assertThat;

import com.vitalsync.domain.VitalReading;
import com.vitalsync.service.SummarizationService;
import com.vitalsync.service.summary.FaithfulnessChecker;
import com.vitalsync.service.summary.RuleBasedProvider;
import com.vitalsync.service.summary.SummaryProvider;
import com.vitalsync.service.summary.SummaryRequest;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.Test;

/**
 * The faithfulness guard: a generated summary must describe the numbers it was
 * given, and must not name a condition.
 */
class FaithfulnessCheckerTest {

    private static VitalReading reading(double hr, double spo2, double sbp) {
        return new VitalReading(1L, "P001", Instant.now(), Instant.now(),
                hr, spo2, 38.4, 22, sbp, 70, null, false, true,
                VitalReading.shockIndex(hr, sbp),
                VitalReading.pulsePressure(sbp, 70),
                VitalReading.meanArterialPressure(sbp, 70));
    }

    private static SummaryRequest request() {
        VitalReading r = reading(118, 94, 104);
        return new SummaryRequest("P001", r, List.of(r), "MEDIUM", 0.81, 5, "MEDIUM");
    }

    // ------------------------------------------------------------- numerics

    @Test
    void acceptsASummaryThatOnlyCitesGivenNumbers() {
        String good = """
                - Physiological status: heart rate 118 bpm, SpO2 94%, blood pressure 104/70 mmHg.
                - Deviations: heart rate above 90, SpO2 below 96.
                - Suggested review priority: NEWS2 5 indicates prompt review; clinician must confirm.""";

        var result = FaithfulnessChecker.check(good, request());
        assertThat(result.faithful()).isTrue();
        assertThat(result.unsupportedNumbers()).isEmpty();
        assertThat(result.numbersChecked()).isGreaterThan(0);
    }

    @Test
    void rejectsAFabricatedVitalSign() {
        // The patient is at SpO2 94; the summary invents 88.
        String bad = """
                - Physiological status: heart rate 118 bpm, SpO2 88%, blood pressure 104/70 mmHg.
                - Deviations: severe desaturation.
                - Suggested review priority: urgent.""";

        var result = FaithfulnessChecker.check(bad, request());
        assertThat(result.faithful()).isFalse();
        assertThat(result.unsupportedNumbers()).contains("88");
    }

    @Test
    void toleratesRoundingOfASuppliedValue() {
        VitalReading r = reading(118.4, 94.6, 104.2);
        var req = new SummaryRequest("P001", r, List.of(r), "MEDIUM", 0.81, 5, "MEDIUM");

        String rounded = """
                - Physiological status: heart rate 118 bpm, SpO2 95%, blood pressure 104/70 mmHg.
                - Deviations: heart rate above 90.
                - Suggested review priority: prompt review.""";

        assertThat(FaithfulnessChecker.check(rounded, req).faithful()).isTrue();
    }

    @Test
    void rejectsAnInventedLabValueNeverSupplied() {
        String bad = """
                - Physiological status: heart rate 118 bpm, SpO2 94%.
                - Deviations: lactate 4.7 mmol/L is markedly elevated.
                - Suggested review priority: urgent.""";

        var result = FaithfulnessChecker.check(bad, request());
        assertThat(result.faithful()).isFalse();
        assertThat(result.unsupportedNumbers()).contains("4.7");
    }

    // ----------------------------------------------------------- diagnosis

    @Test
    void rejectsNamedConditions() {
        String bad = """
                - Physiological status: heart rate 118 bpm, SpO2 94%.
                - Deviations: findings are consistent with sepsis.
                - Suggested review priority: urgent.""";

        var result = FaithfulnessChecker.check(bad, request());
        assertThat(result.faithful()).isFalse();
        assertThat(result.diagnosticTerms()).contains("sepsis");
    }

    @Test
    void allowsDescriptivePhysiologicalVocabulary() {
        // "Tachycardia" describes a measured rate; it does not name a disease.
        String ok = """
                - Physiological status: heart rate 118 bpm with tachycardia, SpO2 94%.
                - Deviations: heart rate above 90, SpO2 below 96.
                - Suggested review priority: prompt review.""";

        assertThat(FaithfulnessChecker.check(ok, request()).faithful()).isTrue();
    }

    @Test
    void rejectsEmptyOutput() {
        assertThat(FaithfulnessChecker.check("", request()).faithful()).isFalse();
        assertThat(FaithfulnessChecker.check(null, request()).faithful()).isFalse();
    }

    // ------------------------------------------------- deterministic tier

    @Test
    void theDeterministicTierIsAlwaysFaithful() {
        // It builds text from the source numbers, so it must never trip the
        // guard. If this fails, the rule-based generator has a formatting bug.
        var provider = new RuleBasedProvider();
        for (VitalReading r : List.of(
                reading(72, 98, 120),
                reading(140, 85, 78),
                reading(45, 100, 200),
                reading(118, 94, 104))) {
            var req = new SummaryRequest("P001", r, List.of(r), "LOW", 0.5, 3, "LOW");
            String text = provider.summarize(req).orElseThrow();
            var result = FaithfulnessChecker.check(text, req);
            assertThat(result.faithful())
                    .as("rule-based output must be faithful, got %s", result.problems())
                    .isTrue();
        }
    }

    // ---------------------------------------------------- cascade integration

    private record StubProvider(String name, int order, boolean available, String answer)
            implements SummaryProvider {
        @Override
        public Optional<String> summarize(SummaryRequest request) {
            return Optional.ofNullable(answer);
        }
    }

    @Test
    void anUnfaithfulTierIsSkippedAndTheCascadeFallsThrough() {
        String fabricated = """
                - Physiological status: SpO2 has fallen to 71%.
                - Deviations: lactate 9.2 and a diagnosis of septic shock.
                - Suggested review priority: immediate.""";

        var service = new SummarizationService(List.of(
                new RuleBasedProvider(),
                new StubProvider("ollama", 100, true, fabricated)));

        var result = service.summarize(request());

        // The hallucinating tier must not win.
        assertThat(result.provider()).isEqualTo(RuleBasedProvider.NAME);
        assertThat(result.faithful()).isTrue();
        assertThat(result.text()).doesNotContain("71%");
        assertThat(result.text()).doesNotContain("septic");
    }

    @Test
    void aFaithfulTierIsStillPreferredOverTheFallback() {
        String good = """
                - Physiological status: heart rate 118 bpm, SpO2 94%, BP 104/70 mmHg.
                - Deviations: heart rate above 90, SpO2 below 96.
                - Suggested review priority: NEWS2 5, prompt clinician review.""";

        var service = new SummarizationService(List.of(
                new RuleBasedProvider(),
                new StubProvider("ollama", 100, true, good)));

        var result = service.summarize(request());
        assertThat(result.provider()).isEqualTo("ollama");
        assertThat(result.faithful()).isTrue();
    }
}
