package com.vitalsync.service.summary;

import java.util.Arrays;
import java.util.List;
import java.util.Optional;
import java.util.stream.Collectors;

/**
 * Normalises free-form model output into the three-bullet contract.
 *
 * <p>Instruction-following is not guaranteed: models add preambles, use varied
 * bullet glyphs, wrap output in markdown, or emit a different number of points.
 * Rather than trusting the prompt, output that cannot be coerced into the
 * expected shape is rejected, and the cascade falls through to the next tier.
 * A malformed summary is treated as a tier failure, not as a result.
 */
public final class SummaryPostProcessor {

    private SummaryPostProcessor() {}

    private static final int REQUIRED_BULLETS = 3;

    /** Characters models commonly use instead of a plain hyphen. */
    private static final List<String> BULLET_GLYPHS =
            List.of("- ", "* ", "• ", "– ", "— ");

    public static Optional<String> normalise(String raw) {
        if (raw == null || raw.isBlank()) {
            return Optional.empty();
        }

        List<String> bullets = Arrays.stream(raw.split("\\R"))
                .map(String::strip)
                .map(SummaryPostProcessor::stripNumbering)
                .filter(SummaryPostProcessor::isBullet)
                .map(SummaryPostProcessor::toPlainBullet)
                .filter(s -> s.length() > 4)
                .collect(Collectors.toList());

        if (bullets.size() < REQUIRED_BULLETS) {
            return Optional.empty();
        }
        // Extra bullets are truncated rather than rejected: the leading three
        // follow the requested structure, and trailing additions are usually
        // the model restating itself.
        return Optional.of(String.join("\n", bullets.subList(0, REQUIRED_BULLETS)));
    }

    private static String stripNumbering(String line) {
        return line.replaceFirst("^\\d+[.)]\\s*", "");
    }

    private static boolean isBullet(String line) {
        return BULLET_GLYPHS.stream().anyMatch(line::startsWith);
    }

    private static String toPlainBullet(String line) {
        for (String glyph : BULLET_GLYPHS) {
            if (line.startsWith(glyph)) {
                // Strip markdown emphasis so the dashboard renders plain text.
                String body = line.substring(glyph.length())
                        .replace("**", "")
                        .replace("__", "")
                        .strip();
                return "- " + body;
            }
        }
        return line;
    }
}
