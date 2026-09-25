package com.vitalsync;

import static org.assertj.core.api.Assertions.assertThat;

import com.vitalsync.domain.VitalReading;
import com.vitalsync.service.SummarizationService;
import com.vitalsync.service.summary.RuleBasedProvider;
import com.vitalsync.service.summary.SummaryPostProcessor;
import com.vitalsync.service.summary.SummaryProvider;
import com.vitalsync.service.summary.SummaryRequest;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.Test;

/**
 * Cascade behaviour under every combination of tier failure.
 *
 * <p>This is the system's availability claim expressed as tests: whatever fails,
 * a usable summary comes back, and the tier that produced it is reported
 * accurately.
 */
class SummaryCascadeTest {

    /** Configurable stand-in for an LLM tier. */
    private record StubProvider(String name, int order, boolean available, String answer)
            implements SummaryProvider {

        @Override
        public Optional<String> summarize(SummaryRequest request) {
            return Optional.ofNullable(answer);
        }
    }

    private static final class ThrowingProvider implements SummaryProvider {
        public String name() { return "throwing"; }
        public int order() { return 50; }
        public boolean available() { return true; }
        public Optional<String> summarize(SummaryRequest r) {
            throw new IllegalStateException("connection reset");
        }
    }

    private static VitalReading reading(double hr, double spo2, double sbp) {
        return new VitalReading(1L, "P001", Instant.now(), Instant.now(),
                hr, spo2, 36.9, 17, sbp, 78, null, false, true,
                VitalReading.shockIndex(hr, sbp),
                VitalReading.pulsePressure(sbp, 78),
                VitalReading.meanArterialPressure(sbp, 78));
    }

    private static SummaryRequest request() {
        VitalReading r = reading(118, 91, 96);
        return new SummaryRequest("P001", r, List.of(r), "HIGH", 0.88, 7, "HIGH");
    }

    private static final String THREE_BULLETS =
            "- Physiological status: tachycardic.\n"
            + "- Deviations: SpO2 below range.\n"
            + "- Suggested review priority: urgent.";

    @Test
    void firstAvailableTierWins() {
        var service = new SummarizationService(List.of(
                new RuleBasedProvider(),
                new StubProvider("ollama", 100, true, THREE_BULLETS),
                new StubProvider("gemini", 200, true, THREE_BULLETS)));

        assertThat(service.summarize(request()).provider()).isEqualTo("ollama");
    }

    @Test
    void fallsThroughToGeminiWhenOllamaIsUnavailable() {
        var service = new SummarizationService(List.of(
                new RuleBasedProvider(),
                new StubProvider("ollama", 100, false, THREE_BULLETS),
                new StubProvider("gemini", 200, true, THREE_BULLETS)));

        assertThat(service.summarize(request()).provider()).isEqualTo("gemini");
    }

    @Test
    void fallsThroughWhenAnAvailableTierReturnsNothing() {
        var service = new SummarizationService(List.of(
                new RuleBasedProvider(),
                new StubProvider("ollama", 100, true, null),
                new StubProvider("gemini", 200, true, THREE_BULLETS)));

        assertThat(service.summarize(request()).provider()).isEqualTo("gemini");
    }

    @Test
    void reachesTheDeterministicTierWhenBothModelsFail() {
        var service = new SummarizationService(List.of(
                new RuleBasedProvider(),
                new StubProvider("ollama", 100, true, null),
                new StubProvider("gemini", 200, true, null)));

        var result = service.summarize(request());
        assertThat(result.provider()).isEqualTo(RuleBasedProvider.NAME);
        assertThat(result.text().lines().count()).isEqualTo(3);
    }

    @Test
    void aTierThatThrowsDoesNotBreakTheCascade() {
        var service = new SummarizationService(List.of(
                new RuleBasedProvider(), new ThrowingProvider()));

        var result = service.summarize(request());
        assertThat(result.provider()).isEqualTo(RuleBasedProvider.NAME);
        assertThat(result.text()).isNotBlank();
    }

    @Test
    void ruleBasedTierAlwaysProducesExactlyThreeBullets() {
        var provider = new RuleBasedProvider();
        for (VitalReading r : List.of(
                reading(72, 98, 120),     // entirely normal
                reading(140, 85, 78),     // severely deranged
                reading(45, 100, 200))) { // bradycardic and hypertensive
            var out = provider.summarize(
                    new SummaryRequest("P001", r, List.of(r), "LOW", 0.5, 0, "LOW"));
            assertThat(out).isPresent();
            assertThat(out.get().lines().count()).isEqualTo(3);
            assertThat(out.get().lines()).allMatch(l -> l.startsWith("- "));
        }
    }

    @Test
    void ruleBasedTierReportsNoDeviationsForANormalPatient() {
        var out = new RuleBasedProvider().summarize(new SummaryRequest(
                "P001", reading(72, 98, 120), List.of(reading(72, 98, 120)),
                "LOW", 0.99, 0, "LOW"));

        assertThat(out.orElseThrow()).contains("no parameter falls outside");
    }

    @Test
    void ruleBasedTierNamesTheActualDeviations() {
        var r = reading(118, 91, 96);
        var out = new RuleBasedProvider().summarize(
                new SummaryRequest("P001", r, List.of(r), "HIGH", 0.9, 7, "HIGH"))
                .orElseThrow();

        assertThat(out).contains("heart rate 118 bpm above 90");
        assertThat(out).contains("SpO2 91.0% below 96%");
        assertThat(out).contains("systolic BP 96 mmHg below 111");
        assertThat(out).contains("urgent clinical review");
    }

    // ------------------------------------------------------------- post-processing

    @Test
    void postProcessorNormalisesVariedBulletGlyphs() {
        var out = SummaryPostProcessor.normalise(
                "• first point here\n* second point here\n- third point here");
        assertThat(out).isPresent();
        assertThat(out.get().lines()).allMatch(l -> l.startsWith("- "));
    }

    @Test
    void postProcessorStripsPreambleAndNumbering() {
        var out = SummaryPostProcessor.normalise(
                "Here is the summary you asked for:\n"
                + "1. - first point here\n2. - second point here\n3. - third point here");
        assertThat(out).isPresent();
        assertThat(out.get().lines().count()).isEqualTo(3);
        assertThat(out.get()).doesNotContain("Here is the summary");
    }

    @Test
    void postProcessorStripsMarkdownEmphasis() {
        var out = SummaryPostProcessor.normalise(
                "- **Status**: stable\n- **Deviations**: none\n- **Priority**: routine");
        assertThat(out.orElseThrow()).doesNotContain("**");
    }

    @Test
    void postProcessorRejectsTooFewBullets() {
        // Treated as a tier failure so the cascade falls through, rather than
        // surfacing a malformed two-line summary as a result.
        assertThat(SummaryPostProcessor.normalise("- only one point")).isEmpty();
        assertThat(SummaryPostProcessor.normalise("no bullets at all")).isEmpty();
        assertThat(SummaryPostProcessor.normalise("")).isEmpty();
        assertThat(SummaryPostProcessor.normalise(null)).isEmpty();
    }

    @Test
    void postProcessorTruncatesExtraBullets() {
        var out = SummaryPostProcessor.normalise(
                "- one point here\n- two point here\n- three point here\n- four point here");
        assertThat(out.orElseThrow().lines().count()).isEqualTo(3);
    }

    @Test
    void promptContextCarriesTheNumbersAndForbidsNothingElse() {
        String context = request().promptContext();
        assertThat(context).contains("118 bpm");
        assertThat(context).contains("91.0 %");
        assertThat(context).contains("Deterministic NEWS2 score: 7");
        assertThat(context).contains("Model triage band: HIGH");
    }
}
