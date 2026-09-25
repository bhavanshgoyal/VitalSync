package com.vitalsync.service;

import com.vitalsync.service.summary.FaithfulnessChecker;
import com.vitalsync.service.summary.SummaryProvider;
import com.vitalsync.service.summary.SummaryRequest;
import java.util.Comparator;
import java.util.List;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * Runs the summarization cascade and reports which tier answered.
 *
 * <p>The cascade is the system's availability claim: generation is attempted
 * best-first, every tier may fail, and the terminal deterministic tier
 * guarantees a result. No tier failure is ever surfaced to the caller as an
 * error.
 */
@Service
public class SummarizationService {

    private static final Logger log = LoggerFactory.getLogger(SummarizationService.class);

    private final List<SummaryProvider> providers;

    public SummarizationService(List<SummaryProvider> providers) {
        this.providers = providers.stream()
                .sorted(Comparator.comparingInt(SummaryProvider::order))
                .toList();
        log.info("Summarization cascade: {}",
                this.providers.stream().map(SummaryProvider::name).toList());
    }

    public record Result(
            String text,
            String provider,
            double latencyMs,
            boolean faithful,
            List<String> faithfulnessProblems) {

        public static Result of(String text, String provider, double latencyMs) {
            return new Result(text, provider, latencyMs, true, List.of());
        }
    }

    public Result summarize(SummaryRequest request) {
        long start = System.nanoTime();

        for (SummaryProvider provider : providers) {
            if (!provider.available()) {
                log.debug("Tier {} unavailable, skipping", provider.name());
                continue;
            }
            long tierStart = System.nanoTime();
            Optional<String> text;
            try {
                text = provider.summarize(request);
            } catch (RuntimeException e) {
                // A provider that breaks its no-throw contract must still not
                // take down the cascade.
                log.warn("Tier {} threw, treating as failure: {}",
                        provider.name(), e.getMessage());
                text = Optional.empty();
            }
            if (text.isPresent()) {
                double ms = (System.nanoTime() - tierStart) / 1_000_000.0;

                // A generated summary is only useful if it describes the
                // numbers it was actually given. Fabricated values are treated
                // as a tier failure and the cascade falls through, because a
                // fluent wrong number is worse than a plain deterministic one.
                var faith = FaithfulnessChecker.check(text.get(), request);
                boolean terminal = provider.equals(providers.get(providers.size() - 1));

                if (!faith.faithful() && !terminal) {
                    log.warn("Tier {} produced an unfaithful summary ({}); "
                            + "falling through", provider.name(), faith.problems());
                    continue;
                }
                if (!faith.faithful()) {
                    // Terminal tier: return it rather than nothing, but the
                    // failure is recorded rather than silently accepted.
                    log.error("Terminal tier {} produced an unfaithful summary: {}",
                            provider.name(), faith.problems());
                }

                log.debug("Tier {} answered in {} ms", provider.name(), ms);
                return new Result(text.get(), provider.name(),
                        (System.nanoTime() - start) / 1_000_000.0,
                        faith.faithful(), faith.problems());
            }
        }

        // Unreachable while RuleBasedProvider is registered; kept so the method
        // is total even if the terminal tier is ever removed by mistake.
        log.error("Every summarization tier failed, including the deterministic one");
        return Result.of(
                "- Summary unavailable: all summarization tiers failed.\n"
                        + "- Raw telemetry has still been recorded.\n"
                        + "- A clinician must review the numeric values directly.",
                "none",
                (System.nanoTime() - start) / 1_000_000.0);
    }

    public List<String> activeProviders() {
        return providers.stream()
                .filter(SummaryProvider::available)
                .map(SummaryProvider::name)
                .toList();
    }
}
