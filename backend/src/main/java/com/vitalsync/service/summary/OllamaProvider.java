package com.vitalsync.service.summary;

import dev.langchain4j.model.chat.ChatModel;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;

/**
 * Tier 1: local Ollama model.
 *
 * <p>Preferred when present because it keeps telemetry on the local host, which
 * matters for a system whose production form would carry patient data. The bean
 * is optional: with no Ollama configured the tier reports itself unavailable
 * and the cascade moves on without an error.
 */
@Component
@Order(100)
public class OllamaProvider implements SummaryProvider {

    public static final String NAME = "ollama";

    private static final Logger log = LoggerFactory.getLogger(OllamaProvider.class);

    private final ObjectProvider<ChatModel> models;
    private final boolean enabled;

    public OllamaProvider(
            @org.springframework.beans.factory.annotation.Qualifier("ollamaChatModel")
            ObjectProvider<ChatModel> models,
            @org.springframework.beans.factory.annotation.Value("${vitalsync.llm.ollama.enabled:false}")
            boolean enabled) {
        this.models = models;
        this.enabled = enabled;
    }

    @Override
    public String name() {
        return NAME;
    }

    @Override
    public int order() {
        return 100;
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
            // Timeout, connection refused, model not pulled, OOM on the host.
            log.warn("Ollama tier failed, falling through: {}", e.getMessage());
            return Optional.empty();
        }
    }
}
