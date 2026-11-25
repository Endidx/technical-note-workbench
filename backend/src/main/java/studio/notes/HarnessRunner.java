package studio.notes;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.annotation.PreDestroy;
import java.io.*;
import java.net.URI;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.concurrent.*;
import java.util.function.Consumer;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

@Component
public class HarnessRunner {
    private static final Duration DEADLINE = Duration.ofSeconds(180);
    private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    private final ScheduledExecutorService timers = Executors.newSingleThreadScheduledExecutor();
    private final Semaphore slots = new Semaphore(4);
    private final String remote;
    private final ObjectMapper json;

    public HarnessRunner(ObjectMapper json, @Value("${review.harness-url:}") String remote) {
        this.json = json;
        this.remote = remote;
    }

    @PreDestroy
    public void close() {
        timers.shutdownNow();
    }

    public ObjectNode investigate(ObjectNode input, Consumer<ObjectNode> onStep) {
        if (!slots.tryAcquire())
            throw new ResponseStatusException(HttpStatus.TOO_MANY_REQUESTS, "调查运行数已达上限，请稍后重试");
        try {
            byte[] bytes = json.writeValueAsBytes(input);
            return remote.isBlank() ? local(bytes, onStep) : remote(bytes, onStep);
        } catch (IOException ex) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "调查服务未完成，请重试", ex);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "调查被中断", ex);
        } finally {
            slots.release();
        }
    }

    private ObjectNode local(byte[] payload, Consumer<ObjectNode> onStep) throws IOException, InterruptedException {
        var process = new ProcessBuilder("python3", "-m", "analyzer.harness", "--stream")
            .redirectError(ProcessBuilder.Redirect.INHERIT).start();
        var timeout = timers.schedule(process::destroyForcibly, DEADLINE.toMillis(), TimeUnit.MILLISECONDS);
        try {
            try (var stdin = process.getOutputStream()) { stdin.write(payload); }
            ObjectNode result = consume(process.getInputStream(), onStep);
            if (process.waitFor() != 0) throw new IOException("Analyzer exited unsuccessfully");
            return result;
        } finally {
            timeout.cancel(false);
            if (process.isAlive()) process.destroyForcibly();
        }
    }

    private ObjectNode remote(byte[] payload, Consumer<ObjectNode> onStep) throws IOException, InterruptedException {
        var request = HttpRequest.newBuilder(URI.create(remote)).timeout(DEADLINE)
            .header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofByteArray(payload)).build();
        var response = http.send(request, HttpResponse.BodyHandlers.ofInputStream());
        try (var stream = response.body()) {
            if (response.statusCode() != 200) throw new IOException("Investigation HTTP " + response.statusCode());
            var timeout = timers.schedule(() -> {
                try { stream.close(); } catch (IOException ignored) { }
            }, DEADLINE.toMillis(), TimeUnit.MILLISECONDS);
            try { return consume(stream, onStep); }
            finally { timeout.cancel(false); }
        }
    }

    private ObjectNode consume(InputStream stream, Consumer<ObjectNode> onStep) throws IOException {
        try (var reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            String line;
            ObjectNode result = null;
            while ((line = reader.readLine()) != null) {
                if (line.isBlank()) continue;
                var event = json.readTree(line);
                if (result != null) throw new IOException("Unexpected data after result");
                switch (event.path("type").asText()) {
                    case "step" -> {
                        if (!(event instanceof ObjectNode frame) || !event.path("step").isObject() || !event.path("checkpoint").isObject())
                            throw new IOException("Missing tool step or checkpoint");
                        onStep.accept(frame);
                    }
                    case "result" -> {
                        if (!(event.get("result") instanceof ObjectNode report)) throw new IOException("Invalid report");
                        result = report;
                    }
                    default -> throw new IOException("Invalid investigation event");
                }
            }
            if (result == null) throw new IOException("Investigation ended without a report");
            return result;
        }
    }
}
