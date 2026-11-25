package studio.notes.library;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.web.server.ResponseStatusException;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.zip.ZipInputStream;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;

class BatchReviewTest {
    static final long LEASE_MS = 120_000;
    final ObjectMapper json = new ObjectMapper();
    final JdbcTemplate db = new JdbcTemplate(new DriverManagerDataSource(
            "jdbc:h2:mem:" + UUID.randomUUID() + ";MODE=MySQL;DB_CLOSE_DELAY=-1"));
    final LibraryStore library = new LibraryStore(db, json);
    final BatchStore batches = new BatchStore(db, library, json, LEASE_MS);
    final List<String> visited = new ArrayList<>();
    final LibraryBridge bridge = new LibraryBridge(json, "", "", "", "", "", "") {
        @Override public JsonNode engine(String operation, JsonNode input) {
            assertEquals("investigate_batch_note", operation);
            assertEquals("old", input.path("before").path("content").asText());
            assertEquals("new", input.path("after").path("content").asText());
            var name = input.path("filename").asText();
            visited.add(name);
            if (name.equals("b.md")) throw new IllegalStateException("analysis failed");
            var result = json.createObjectNode().put("status", "edit").put("proposed", "fixed " + name)
                    .put("reason", "Changed setting");
            result.putArray("trace").add("Check code");
            result.putArray("evidence").add("New source specifies replacement");
            return result;
        }
    };

    BatchReviewTest() {
        library.initialize();
        batches.initialize();
        library.importFiles(List.of(new LibraryStore.Doc("a.md", "A"), new LibraryStore.Doc("b.md", "B"),
                new LibraryStore.Doc("c.md", "C")), new LibraryStore.Source("guide", "v1", "source.md", "old"));
        var job = library.importFiles(List.of(), new LibraryStore.Source("guide", "v2", "source.md", "new"));
        var lease = library.claim(job.generation(), 10, 100);
        for (String name : List.of("a.md", "b.md", "c.md")) library.save(lease, name, json.createObjectNode(), 11, 100);
        assertTrue(library.publish(lease, 12));
    }

    @Test void scansPublishedSnapshotAndExportsOnlyAcceptedEdits() throws Exception {
        var id = batches.create(new BatchStore.Request("帮我更新到目标版本", "guide", "v1", "v2", 2L));
        assertThrows(ResponseStatusException.class, () -> batches.export(id));
        library.importFiles(List.of(new LibraryStore.Doc("a.md", "different")), null);
        new BatchWorker(batches, library, bridge, json, 700, 1).tick();
        var found = new BatchStore(db, library, json, LEASE_MS).get(id);
        assertEquals("complete", found.path("status").asText());
        assertEquals(3, found.path("done").asInt());
        assertEquals(3, found.path("total").asInt());
        assertEquals(2, found.path("generation").asInt());
        assertEquals(List.of("a.md", "b.md", "c.md"), visited);
        var first = found.path("items").get(0);
        var problem = found.path("items").get(1);
        assertEquals("ask", problem.path("status").asText());
        assertFalse(problem.path("question").asText().isBlank());
        assertThrows(ResponseStatusException.class, () -> batches.accept(id, problem.path("id").asText()));
        assertEquals("A", first.path("original").asText());
        assertTrue(first.path("trace").size() >= 2);
        batches.accept(id, first.path("id").asText());
        batches.accept(id, first.path("id").asText());
        var files = new HashMap<String, String>();
        try (var zip = new ZipInputStream(new ByteArrayInputStream(batches.export(id)))) {
            for (var entry = zip.getNextEntry(); entry != null; entry = zip.getNextEntry()) {
                files.put(entry.getName(), new String(zip.readAllBytes(), StandardCharsets.UTF_8));
            }
        }
        assertEquals(Map.of("a.md", "fixed a.md", "b.md", "B", "c.md", "C"), files);
    }

    @Test void boundedReadersOverlapAndKeepStableItemOrder() {
        var id = batches.create(new BatchStore.Request("帮我更新到目标版本", "guide", "v1", "v2", 2L));
        var entered = new CountDownLatch(2);
        var active = new AtomicInteger();
        var peak = new AtomicInteger();
        var checkingBridge = new LibraryBridge(json, "", "", "", "", "", "") {
            @Override public JsonNode engine(String operation, JsonNode input) {
                peak.accumulateAndGet(active.incrementAndGet(), Math::max);
                entered.countDown();
                try {
                    if (!entered.await(2, TimeUnit.SECONDS)) throw new IllegalStateException("reads did not overlap");
                } catch (InterruptedException e) {
                    throw new AssertionError(e);
                } finally {
                    active.decrementAndGet();
                }
                var row = json.createObjectNode().put("status", "keep").put("reason", "Checked");
                row.putArray("trace").add("Read");
                row.putArray("evidence");
                return row;
            }
        };
        new BatchWorker(batches, library, checkingBridge, json, 700, 2).tick();
        assertEquals(2, peak.get());
        var items = batches.get(id).path("items");
        assertEquals(3, items.size());
        for (int i = 0; i < items.size(); i++) {
            assertEquals(List.of("a.md", "b.md", "c.md").get(i), items.get(i).path("filename").asText());
            assertEquals("keep", items.get(i).path("status").asText());
        }
    }

    @Test void validatesRequestedMigrationAgainstBothSelectedVersions() {
        for (String invalid : List.of("删除全部笔记", "请更新到 v1", "帮我把这批笔记从 v2 升级到 v1",
                "只更新 a.md 到 v2", "帮我更新到 v2，但跳过配置")) {
            assertThrows(ResponseStatusException.class,
                    () -> batches.create(new BatchStore.Request(invalid, "guide", "v1", "v2", 2L)), invalid);
        }
        for (String instruction : List.of("帮我把这批笔记从 v1 升级到 v2",
                "帮我把这组 scikit-learn 学习笔记更新到目标版本。需要改的列出差异，已经兼容的告诉我原因，缺信息的集中问我。",
                "请将资料库里的所有笔记升级至目标版本，列出差异", "Migrate all notes from v1 to v2")) {
            assertNotNull(batches.create(new BatchStore.Request(instruction, "guide", "v1", "v2", 2L)));
        }
        assertThrows(ResponseStatusException.class,
                () -> batches.create(new BatchStore.Request("帮我更新到目标版本", "guide", "v1", "v2", 1L)));
    }

    @Test void expiredWorkerCannotChangeRecoveredResults() {
        String id = batches.create(new BatchStore.Request("帮我更新到目标版本", "guide", "v1", "v2", 2L));
        var first = batches.claim(1);
        var row = batches.remaining(id).get(0);
        var checked = json.createObjectNode().put("status", "keep").put("reason", "OK");
        checked.putArray("evidence");
        checked.putArray("trace");
        assertTrue(batches.save(first, row, checked, 2));
        var duplicate = checked.deepCopy().put("reason", "should never replace the first result");
        assertTrue(batches.save(first, row, duplicate, 2));
        assertEquals("OK", batches.get(id).path("items").get(0).path("reason").asText());
        assertNull(batches.claim(3));
        batches.fail(first, "expired before takeover", 2 + LEASE_MS);
        assertEquals("running", batches.get(id).path("status").asText());
        var another = new BatchStore(db, library, json, LEASE_MS);
        var rescued = another.claim(2 + LEASE_MS);
        assertNotNull(rescued);
        assertEquals(2, another.remaining(id).size());
        assertFalse(batches.save(first, another.remaining(id).get(0), checked, 4 + LEASE_MS));
        batches.finish(first, 4 + LEASE_MS);
        batches.fail(first, "stale failure", 4 + LEASE_MS);
        assertEquals("running", another.get(id).path("status").asText());
        for (var next : another.remaining(id)) assertTrue(another.save(rescued, next, checked, 5 + LEASE_MS));
        another.finish(rescued, 6 + LEASE_MS);
        assertEquals("complete", batches.get(id).path("status").asText());
    }
}
