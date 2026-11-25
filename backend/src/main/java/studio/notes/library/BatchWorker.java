package studio.notes.library;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

import java.util.Set;
import java.util.concurrent.*;

@Component
public class BatchWorker {
    private static final Logger log = LoggerFactory.getLogger(BatchWorker.class);
    private static final Set<String> STATUSES = Set.of("edit", "keep", "ask", "irrelevant");
    private final ScheduledExecutorService executor = Executors.newSingleThreadScheduledExecutor(r -> {
        var thread = new Thread(r, "batch-note-investigation");
        thread.setDaemon(true);
        return thread;
    });
    private final BatchStore batches;
    private final LibraryStore library;
    private final LibraryBridge bridge;
    private final ObjectMapper json;
    private final long pollMs;
    private final int parallelism;

    private record Completed(BatchStore.Pending item, ObjectNode result) {}

    public BatchWorker(BatchStore batches, LibraryStore library, LibraryBridge bridge, ObjectMapper json,
                       @Value("${review.batch.poll-ms:400}") long pollMs,
                       @Value("${review.batch.parallelism:4}") int parallelism) {
        if (parallelism < 1 || parallelism > 16) throw new IllegalArgumentException("review.batch.parallelism must be 1..16");
        this.parallelism = parallelism;
        this.batches = batches;
        this.library = library;
        this.bridge = bridge;
        this.json = json;
        this.pollMs = pollMs;
    }

    @PostConstruct
    public void start() {
        executor.scheduleWithFixedDelay(() -> {
            try {
                tick();
            } catch (RuntimeException ex) {
                log.warn("Batch worker will poll again", ex);
            }
        }, pollMs, pollMs, TimeUnit.MILLISECONDS);
    }

    @PreDestroy
    public void stop() {
        executor.shutdownNow();
    }

    public void tick() {
        var lease = batches.claim(System.currentTimeMillis());
        if (lease == null) return;
        var request = lease.request();
        try {
            var snapshot = library.searchSnapshot(request.generation(), request.name(), request.fromVersion(), request.toVersion());
            var before = bridge.sourceInput(snapshot.before());
            var after = bridge.sourceInput(snapshot.after());
            if (readRemaining(lease, before, after)) batches.finish(lease, System.currentTimeMillis());
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
        } catch (RuntimeException ex) {
            if (Thread.currentThread().isInterrupted()) return;
            batches.fail(lease, "批量调查中断：" + detail(ex), System.currentTimeMillis());
            log.warn("Batch {} failed", lease.id(), ex);
        }
    }

    private boolean readRemaining(BatchStore.Lease lease, ObjectNode before, ObjectNode after)
            throws InterruptedException {
        var remaining = batches.remaining(lease.id()).iterator();
        var pool = Executors.newFixedThreadPool(parallelism);
        var results = new ExecutorCompletionService<Completed>(pool);
        int inFlight = 0;
        try {
            while (remaining.hasNext() || inFlight > 0) {
                while (remaining.hasNext() && inFlight < parallelism) {
                    var item = remaining.next();
                    results.submit(() -> new Completed(item, investigate(lease.request(), item.filename(), before, after)));
                    inFlight++;
                }
                var completed = results.take().get();
                if (Thread.currentThread().isInterrupted()
                        || !batches.save(lease, completed.item(), completed.result(), System.currentTimeMillis())) return false;
                inFlight--;
            }
            return true;
        } catch (ExecutionException ex) {
            throw new IllegalStateException("批量调查线程意外退出", ex.getCause());
        } finally {
            // Pending readers have no write access. Only this lease holder commits their results.
            pool.shutdownNow();
        }
    }

    private ObjectNode investigate(BatchStore.Request request, String filename, ObjectNode before, ObjectNode after) {
        var trace = json.createArrayNode()
                .add("逐篇扫描已发布索引 G" + request.generation() + "，选中 " + filename + "。")
                .add("已校验来源 " + request.name() + " 的 " + request.fromVersion() + " 和 " + request.toVersion() + " 两份快照。");
        try {
            var note = library.note(request.generation(), filename);
            String original = bridge.restore(note.content(), note.digest());
            trace.add("已校验笔记原件，使用两版资料调查调用和上下文。");
            var input = json.createObjectNode().put("instruction", request.instruction())
                    .put("filename", filename).put("content", original);
            input.set("before", before);
            input.set("after", after);
            var result = validate(bridge.engine("investigate_batch_note", input), original);
            trace.addAll((com.fasterxml.jackson.databind.node.ArrayNode) result.get("trace"));
            result.set("trace", trace);
            return result;
        } catch (RuntimeException ex) {
            String reason = "此笔记的调查未完成：" + detail(ex);
            log.warn("Could not investigate {} in generation {}", filename, request.generation(), ex);
            var issue = json.createObjectNode().put("status", "ask").put("reason", reason)
                    .put("question", "请核对 " + filename + " 的原件和分析服务，然后重新运行调查。");
            issue.putArray("evidence");
            issue.set("trace", trace.add(reason));
            return issue;
        }
    }

    ObjectNode validate(JsonNode data, String original) {
        if (!(data instanceof ObjectNode obj) || !STATUSES.contains(obj.path("status").asText())
                || !nonblank(obj.path("reason")) || !stringArray(obj.path("trace")) || !stringArray(obj.path("evidence")))
            throw new IllegalStateException("分析器返回了无效的调查记录");
        String status = obj.path("status").asText();
        var result = json.createObjectNode().put("status", status).put("reason", obj.path("reason").textValue());
        result.set("evidence", obj.get("evidence"));
        result.set("trace", obj.get("trace"));
        if (status.equals("edit")) {
            if (!nonblank(obj.path("proposed")) || original.equals(obj.path("proposed").textValue()) || obj.path("evidence").isEmpty())
                throw new IllegalStateException("修改建议缺少有效的修改稿或证据");
            result.put("proposed", obj.path("proposed").textValue());
        } else if (status.equals("ask")) {
            if (!nonblank(obj.path("question"))) throw new IllegalStateException("分析器缺少澄清问题");
            result.put("question", obj.path("question").textValue());
        }
        return result;
    }

    private static boolean nonblank(JsonNode value) {
        return value.isTextual() && !value.textValue().isBlank();
    }

    private static boolean stringArray(JsonNode value) {
        if (!value.isArray()) return false;
        for (var item : value) if (!nonblank(item)) return false;
        return true;
    }

    private static String detail(RuntimeException ex) {
        if (ex instanceof ResponseStatusException status && status.getReason() != null) return status.getReason();
        if (ex instanceof IllegalStateException && ex.getMessage() != null) return ex.getMessage();
        return "无法读取调查所需的数据";
    }
}
