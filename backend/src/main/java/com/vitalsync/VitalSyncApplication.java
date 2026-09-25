package com.vitalsync;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableAsync;

@SpringBootApplication
@EnableAsync
public class VitalSyncApplication {

    public static void main(String[] args) {
        SpringApplication.run(VitalSyncApplication.class, args);
    }
}
