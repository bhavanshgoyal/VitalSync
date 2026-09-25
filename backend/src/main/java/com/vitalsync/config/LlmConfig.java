package com.vitalsync.config;

import dev.langchain4j.model.chat.ChatModel;
import dev.langchain4j.model.googleai.GoogleAiGeminiChatModel;
import dev.langchain4j.model.ollama.OllamaChatModel;
import java.time.Duration;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Optional LLM beans.
 *
 * <p>Both tiers are conditional. A missing Gemini key or an absent Ollama host
 * must not prevent startup -- the system is designed to run with zero language
 * models available, and the deterministic tier still produces summaries. Making
 * these beans mandatory would contradict the resilience claim the architecture
 * is built around.
 *
 * <p>Timeouts are short by design. A summarization tier that hangs is worse
 * than one that fails, because the cascade cannot fall through until it returns.
 */
@Configuration
public class LlmConfig {

    private static final Logger log = LoggerFactory.getLogger(LlmConfig.class);

    @Bean("ollamaChatModel")
    @ConditionalOnProperty(name = "vitalsync.llm.ollama.enabled", havingValue = "true")
    public ChatModel ollamaChatModel(
            @Value("${vitalsync.llm.ollama.base-url:http://localhost:11434}") String baseUrl,
            @Value("${vitalsync.llm.ollama.model:llama3.1:8b}") String model,
            @Value("${vitalsync.llm.ollama.timeout-seconds:20}") long timeoutSeconds,
            @Value("${vitalsync.llm.ollama.temperature:0.2}") double temperature) {

        log.info("Ollama tier enabled: {} at {}", model, baseUrl);
        return OllamaChatModel.builder()
                .baseUrl(baseUrl)
                .modelName(model)
                .timeout(Duration.ofSeconds(timeoutSeconds))
                // Low temperature: this is clinical documentation, and
                // variability between runs is a liability, not a feature.
                .temperature(temperature)
                .build();
    }

    @Bean("geminiChatModel")
    @ConditionalOnProperty(name = "vitalsync.llm.gemini.enabled", havingValue = "true")
    public ChatModel geminiChatModel(
            @Value("${vitalsync.llm.gemini.api-key:}") String apiKey,
            @Value("${vitalsync.llm.gemini.model:gemini-2.0-flash}") String model,
            @Value("${vitalsync.llm.gemini.timeout-seconds:20}") long timeoutSeconds,
            @Value("${vitalsync.llm.gemini.temperature:0.2}") double temperature) {

        if (apiKey == null || apiKey.isBlank()) {
            log.warn("Gemini tier enabled but no API key supplied; tier will be skipped.");
            return null;
        }
        log.info("Gemini tier enabled: {}", model);
        return GoogleAiGeminiChatModel.builder()
                .apiKey(apiKey)
                .modelName(model)
                .timeout(Duration.ofSeconds(timeoutSeconds))
                .temperature(temperature)
                .build();
    }
}
