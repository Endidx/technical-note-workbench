package studio.notes.library;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

import java.io.IOException;
import java.net.URI;
import java.net.http.*;
import java.nio.file.*;
import java.time.Duration;
import java.util.concurrent.TimeUnit;

@Component
public class LibraryBridge {
    private final ObjectMapper json;
    private final HttpClient http =
            HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build();
    private final String engine, archive, restore, enqueue, dequeue, python;

    public LibraryBridge(
            ObjectMapper json,
            @Value("${review.library-url:}") String engine,
            @Value("${review.archive-url:}") String archive,
            @Value("${review.restore-url:}") String restore,
            @Value("${review.enqueue-url:}") String enqueue,
            @Value("${review.dequeue-url:}") String dequeue,
            @Value("${review.library-python:python3}") String python) {
        this.json = json;
        this.engine = engine;
        this.archive = archive;
        this.restore = restore;
        this.enqueue = enqueue;
        this.dequeue = dequeue;
        this.python = python;
    }

    public JsonNode engine(String operation, JsonNode input) {
        if (!engine.isBlank()) return post(engine + "/" + operation, input, 50);
        try {
            // Both streams can exceed the OS pipe buffer for a full generation.
            Path in = Files.createTempFile("library-input-", ".json");
            try {
                Path out = Files.createTempFile("library-output-", ".json");
                try {
                    Files.write(in, json.writeValueAsBytes(input));
                    Path errors = Files.createTempFile("library-error-", ".txt");
                    try {
                        Process process =
                                new ProcessBuilder(python, "-m", "analyzer.library", operation)
                                        .redirectInput(in.toFile())
                                        .redirectOutput(out.toFile())
                                        .redirectError(errors.toFile())
                                        .start();
                        try {
                            if (!process.waitFor(55, TimeUnit.SECONDS))
                                throw new IOException("分析器超时");
                            if (process.exitValue() == 2) {
                                String detail;
                                try (var stream = Files.newInputStream(errors)) {
                                    detail =
                                            new String(
                                                    stream.readNBytes(1200),
                                                    java.nio.charset.StandardCharsets.UTF_8);
                                }
                                throw invalid(detail);
                            }
                            if (process.exitValue() != 0) throw new IOException("分析器未完成操作");
                            return json.readTree(out.toFile());
                        } finally {
                            if (process.isAlive()) process.destroyForcibly();
                        }
                    } finally {
                        Files.deleteIfExists(errors);
                    }
                } finally {
                    Files.deleteIfExists(out);
                }
            } finally {
                Files.deleteIfExists(in);
            }
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw unavailable("分析任务被中断", ex);
        } catch (IOException ex) {
            throw unavailable("无法完成本地资料分析", ex);
        }
    }

    private JsonNode post(String url, JsonNode input, int seconds) {
        try {
            var req =
                    HttpRequest.newBuilder(URI.create(url))
                            .timeout(Duration.ofSeconds(seconds))
                            .header("Content-Type", "application/json")
                            .POST(
                                    HttpRequest.BodyPublishers.ofByteArray(
                                            json.writeValueAsBytes(input)))
                            .build();
            var response = http.send(req, HttpResponse.BodyHandlers.ofByteArray());
            if (response.statusCode() == 422)
                throw invalid(json.readTree(response.body()).path("detail").asText());
            if (response.statusCode() < 200 || response.statusCode() >= 300)
                throw new IOException("上游 HTTP " + response.statusCode());
            return json.readTree(response.body());
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw unavailable("资料服务请求中断", ex);
        } catch (IOException ex) {
            throw unavailable("资料服务暂时不可用", ex);
        }
    }

    private ResponseStatusException invalid(String detail) {
        String message = detail.isBlank() ? "资料分析请求无效" : detail.strip();
        return LibraryStore.error(
                HttpStatus.UNPROCESSABLE_ENTITY,
                message.substring(0, Math.min(240, message.length())));
    }

    private ResponseStatusException unavailable(String m, Exception ex) {
        return new ResponseStatusException(HttpStatus.BAD_GATEWAY, m, ex);
    }

    public void archive(String content) {
        if (archive.isBlank()) return;
        String actual =
                post(archive, json.createObjectNode().put("content", content), 15)
                        .path("sha256")
                        .asText();
        if (!LibraryStore.digest(content).equals(actual))
            throw LibraryStore.error(HttpStatus.BAD_GATEWAY, "原件归档摘要不一致");
    }

    public String restore(String copy, String expected) {
        String content = copy;
        if (!restore.isBlank()) {
            JsonNode data =
                    post(restore, json.createObjectNode().put("sha256", expected), 15)
                            .path("content");
            if (!data.isTextual()) throw LibraryStore.error(HttpStatus.BAD_GATEWAY, "原件存储缺少指定内容");
            content = data.textValue();
        }
        if (!LibraryStore.digest(content).equals(expected))
            throw LibraryStore.error(HttpStatus.BAD_GATEWAY, "原件校验失败");
        return content;
    }

    public ObjectNode sourceInput(LibraryStore.StoredSource stored) {
        var source = stored.source();
        var node = json.<ObjectNode>valueToTree(source);
        return node.put("content", restore(source.content(), stored.digest()));
    }

    public boolean brokerEnabled() {
        return !enqueue.isBlank() && !dequeue.isBlank();
    }

    public void enqueue(long gen) {
        post(enqueue, json.createObjectNode().put("jobId", gen).put("generation", gen), 2);
    }

    public Long dequeue() {
        var hint = post(dequeue, json.createObjectNode(), 2).path("jobId");
        return hint.isIntegralNumber() ? hint.longValue() : null;
    }

    public ObjectNode corpus(long gen, JsonNode docs) {
        return json.createObjectNode()
                .put("workspaceId", "local")
                .put("generation", Long.toString(gen))
                .set("documents", docs);
    }
}
