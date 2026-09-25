package com.vitalsync.service.summary;

import java.util.Optional;

/**
 * One tier of the summarization cascade.
 *
 * <p>Contract: {@link #summarize} never throws. A tier that cannot answer
 * returns {@link Optional#empty()} so the orchestrator can fall through to the
 * next one. Exactly one implementation -- the rule-based tier -- is required
 * always to succeed, which is what makes the cascade total.
 */
public interface SummaryProvider {

    /** Stable identifier persisted on the assessment row. */
    String name();

    /** Lower runs first. */
    int order();

    /** Whether this tier is configured and worth attempting. */
    boolean available();

    Optional<String> summarize(SummaryRequest request);
}
