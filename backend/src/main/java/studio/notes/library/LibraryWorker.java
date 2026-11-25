package studio.notes.library;

import com.fasterxml.jackson.databind.ObjectMapper;

import org.slf4j.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.*;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

@Component
@EnableScheduling
public class LibraryWorker {
    private static final Logger log = LoggerFactory.getLogger(LibraryWorker.class);
    private final LibraryStore store;
    private final LibraryBridge bridge;
    private final ObjectMapper json;
    private final long leaseMs;
    private long rescueAt;

    public LibraryWorker(
            LibraryStore store,
            LibraryBridge bridge,
            ObjectMapper json,
            @Value("${review.library.lease-ms:120000}") long leaseMs) {
        this.store = store;
        this.bridge = bridge;
        this.json = json;
        this.leaseMs = leaseMs;
    }

    @Scheduled(
            fixedDelayString = "${review.library.poll-ms:700}",
            initialDelayString = "${review.library.poll-ms:700}")
    public void tick() {
        long now = System.currentTimeMillis();
        Long hint = null;
        if (bridge.brokerEnabled()) {
            Long pending = store.nextNotification(now);
            if (pending != null) {
                try {
                    bridge.enqueue(pending);
                    store.notified(pending, true, now);
                } catch (RuntimeException ex) {
                    store.notified(pending, false, now);
                    log.warn("Queue publish deferred for generation {}", pending);
                }
            }
            try {
                hint = bridge.dequeue();
            } catch (RuntimeException ex) {
                log.debug("Using DB queue recovery", ex);
            }
        }
        LibraryStore.Lease lease = hint == null ? null : store.claim(hint, now, leaseMs);
        if (lease == null && (!bridge.brokerEnabled() || now >= rescueAt)) {
            lease = store.claim(null, now, leaseMs);
            rescueAt = now + 4000;
        }
        if (lease == null) return;
        try {
            index(lease);
        } catch (RuntimeException ex) {
            String message =
                    ex instanceof ResponseStatusException e ? e.getReason() : "索引任务失败，可重试未完成部分";
            store.fail(lease, message);
            log.warn("Index generation {} failed: {}", lease.generation(), message);
        }
    }

    private void index(LibraryStore.Lease lease) {
        LibraryStore.Pending note;
        while ((note = store.next(lease.generation())) != null) {
            String text = bridge.restore(note.content(), note.digest());
            var indexed =
                    bridge.engine(
                            "index",
                            json.createObjectNode()
                                    .put("filename", note.filename())
                                    .put("content", text));
            if (indexed == null
                    || !indexed.path("chunks").isArray()
                    || !note.filename().equals(indexed.path("filename").asText())
                    || !note.digest().equals(indexed.path("contentSha256").asText()))
                throw new IllegalStateException("分析器索引响应与原件不一致");
            if (!store.save(lease, note.filename(), indexed, System.currentTimeMillis(), leaseMs))
                return;
        }
        var publish =
                bridge.engine(
                        "publish",
                        bridge.corpus(lease.generation(), store.documents(lease.generation())));
        if (publish == null
                || !Long.toString(lease.generation()).equals(publish.path("generation").asText()))
            throw new IllegalStateException("检索索引发布确认与当前 generation 不匹配");
        store.publish(lease, System.currentTimeMillis());
    }
}
