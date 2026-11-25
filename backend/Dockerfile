FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /workspace/backend
COPY analysis.json /workspace/analysis.json
COPY examples/batch-upgrade /workspace/examples/batch-upgrade
COPY backend/pom.xml .
COPY backend/src src
RUN mvn -B package

FROM eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /workspace/backend/target/review-0.1.0.jar app.jar
COPY web web
ENTRYPOINT ["java","-jar","app.jar"]
