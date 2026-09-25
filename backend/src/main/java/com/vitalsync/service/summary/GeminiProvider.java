package com.vitalsync.service.summary;

import dev.langchain4j.model.chat.ChatModel;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;

/**
 * Tier 2: Google Gemini cloud fallback.
 *
 * <p>Second rather than first: it leaves the host, it is rate-limited, and it
 * costs money per call. It is genuinely useful as a fallback precisely because
 * its failure modes are uncorrelated with the local tier -- a machine without
 * enough RAM to run Ollama can still reach Gemini, and a network-isolated host
 * can still run Ollama.
 */
@Component
@Order(200)
public class GeminiProvider implements SummaryProvider {

    public static final String NAME = "gemini";

    private static final Logger log = LoggerFactory.getLogger(GeminiProvider.class);

    private final ObjectProvider<ChatModel> models;
    private final boolean enabled;

    public GeminiProvider(
            @Qualifier("geminiChatModel") ObjectProvider<ChatModel> models,
            @Value("${vitalsync.llm.gemini.enabled:false}") boolean enabled) {
        this.models = models;
        this.enabled = enabled;
    }

    @Override
    public String name() {
        return NAME;
    }

    @Override
    public int order() {
        return 200;
    }

    @Override
    public boolean available() {
        return enabled && models.getIfAvailable() != null;
    }

    @Override
    public Optional<String> summarize(SummaryRequest request) {
        ChatModel model = models.getIfAvailable();
        if (model == null) {
            return Optional.empty();
        }
        try {
            String answer = model.chat(Prompts.SYSTEM + "\n\n" + Prompts.user(request));
            return SummaryPostProcessor.normalise(answer);
        } catch (Exception e) {
            // Missing/invalid key, quota exhausted, timeout, safety block.
            log.warn("Gemini tier failed, falling through: {}", e.getMessage());
            return Optional.empty();
        }
    }
}
