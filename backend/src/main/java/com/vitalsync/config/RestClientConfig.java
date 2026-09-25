package com.vitalsync.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.client.RestClientCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;

/**
 * Timeouts for outbound HTTP.
 *
 * <p>Without explicit timeouts a stalled ML service would hold an analysis
 * thread indefinitely and eventually exhaust the bounded executor, turning a
 * dependency slowdown into a full stop. These values cap that blast radius.
 *
 * <p>The read timeout is also what makes the degraded path testable: stall the
 * ML service past it and the backend records an assessment with
 * {@code ml_available = false} instead of hanging.
 */
@Configuration
public class RestClientConfig {

    @Bean
    RestClientCustomizer restClientCustomizer(
            @Value("${vitalsync.ml.connect-timeout-ms:2000}") int connectTimeoutMs,
            @Value("${vitalsync.ml.read-timeout-ms:5000}") int readTimeoutMs) {

        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(connectTimeoutMs);
        factory.setReadTimeout(readTimeoutMs);

        return builder -> builder.requestFactory(factory);
    }
}
