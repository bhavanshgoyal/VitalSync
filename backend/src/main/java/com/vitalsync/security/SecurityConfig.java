package com.vitalsync.security;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpStatus;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.HttpStatusEntryPoint;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

@Configuration
public class SecurityConfig {

    private final JwtAuthFilter jwtAuthFilter;

    public SecurityConfig(JwtAuthFilter jwtAuthFilter) {
        this.jwtAuthFilter = jwtAuthFilter;
    }

    @Bean
    SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
                // Stateless bearer-token API: there is no session or cookie for
                // CSRF to protect, and the dashboard sends the token explicitly.
                .csrf(AbstractHttpConfigurer::disable)
                .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(auth -> auth
                        .requestMatchers(
                                "/api/v1/auth/**",
                                "/actuator/health",
                                "/actuator/health/**",
                                "/actuator/info",
                                "/",
                                "/index.html",
                                "/favicon.ico",
                                // Static assets live under css/ and js/. These
                                // must be anonymous: the login page itself
                                // cannot render without them, and a 401 on a
                                // stylesheet surfaces as an unstyled page with
                                // a confusing MIME-type error rather than as
                                // an auth problem.
                                "/css/**",
                                "/js/**")
                        .permitAll()
                        .anyRequest().authenticated())
                // Return 401 rather than a login redirect; this is an API.
                .exceptionHandling(e -> e.authenticationEntryPoint(
                        new HttpStatusEntryPoint(HttpStatus.UNAUTHORIZED)))
                .addFilterBefore(jwtAuthFilter, UsernamePasswordAuthenticationFilter.class);

        return http.build();
    }
}
