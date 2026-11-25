package studio.notes;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.beans.factory.SmartInitializingSingleton;

@SpringBootApplication
public class ReviewApplication {
    public static void main(String[] args) {
        SpringApplication.run(ReviewApplication.class, args);
    }

    @Bean
    SmartInitializingSingleton initialize(ReviewStore store, ObjectMapper mapper,
            @Value("${review.analysis-file:analysis.json}") String file,
            @Value("${review.analyzer-url:}") String analyzerUrl) {
        return () -> {
            try {
                JsonNode notes;
                if (analyzerUrl.isBlank()) {
                    notes = mapper.readTree(Files.readAllBytes(Path.of(file)));
                } else {
                    var request = HttpRequest.newBuilder(URI.create(analyzerUrl))
                        .timeout(Duration.ofSeconds(20)).GET().build();
                    var response = HttpClient.newHttpClient().send(request, HttpResponse.BodyHandlers.ofByteArray());
                    if (response.statusCode() != 200) {
                        throw new IllegalStateException("Analyzer returned HTTP " + response.statusCode());
                    }
                    notes = mapper.readTree(response.body());
                }
                store.initialize(notes);
            } catch (Exception ex) {
                throw new IllegalStateException("Cannot initialize review snapshot", ex);
            }
        };
    }
}
