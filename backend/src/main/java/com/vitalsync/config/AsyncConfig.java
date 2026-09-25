package com.vitalsync.config;

import java.util.concurrent.Executor;
import java.util.concurrent.ThreadPoolExecutor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

/**
 * Executor for asynchronous risk analysis.
 *
 * <p>Bounded on purpose. An unbounded queue would let a telemetry burst build an
 * ever-growing backlog of pending LLM calls and eventually exhaust heap, which
 * would turn a load spike into an outage. With a bounded queue and a
 * caller-runs policy, sustained overload instead pushes back on the ingestion
 * thread -- ingestion slows, but nothing is silently dropped and nothing grows
 * without limit.
 */
@Configuration
public class AsyncConfig {

    @Bean("analysisExecutor")
    public Executor analysisExecutor(
            @Value("${vitalsync.async.core-pool-size:4}") int corePoolSize,
            @Value("${vitalsync.async.max-pool-size:8}") int maxPoolSize,
            @Value("${vitalsync.async.queue-capacity:500}") int queueCapacity) {

        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(corePoolSize);
        executor.setMaxPoolSize(maxPoolSize);
        executor.setQueueCapacity(queueCapacity);
        executor.setThreadNamePrefix("analysis-");
        executor.setRejectedExecutionHandler(new ThreadPoolExecutor.CallerRunsPolicy());
        executor.setWaitForTasksToCompleteOnShutdown(true);
        executor.setAwaitTerminationSeconds(30);
        executor.initialize();
        return executor;
    }
}
