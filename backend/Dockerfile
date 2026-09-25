# Multi-stage: build with Maven, ship only the JRE and the jar.
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /build

# Resolve dependencies first so a source-only change reuses this layer.
COPY pom.xml .
RUN mvn -B -q dependency:go-offline

COPY src ./src
RUN mvn -B -q -DskipTests package

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app

RUN addgroup -S vitalsync && adduser -S vitalsync -G vitalsync
COPY --from=build /build/target/vitalsync-backend-*.jar app.jar
USER vitalsync

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=45s --retries=6 \
  CMD wget -qO- http://localhost:8080/actuator/health | grep -q '"status":"UP"' || exit 1

ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-jar", "app.jar"]
