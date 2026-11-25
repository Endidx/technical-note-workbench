package studio.notes.library;

import static org.junit.jupiter.api.Assertions.*;

import com.fasterxml.jackson.databind.ObjectMapper;

import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.web.server.ResponseStatusException;

import java.util.*;

class LibraryStoreTest {
    final ObjectMapper json = new ObjectMapper();
    final JdbcTemplate db =
            new JdbcTemplate(
                    new DriverManagerDataSource(
                            "jdbc:h2:mem:" + UUID.randomUUID() + ";MODE=MySQL;DB_CLOSE_DELAY=-1"));
    final LibraryStore store = new LibraryStore(db, json);

    {
        store.initialize();
    }

    @Test
    void importsAreIsolatedUntilPublishedAndChangedSourcesAreRejected() {
        var n = new LibraryStore.Doc("note.md", "original");
        var older = new LibraryStore.Source("guide", "v1", "guide.md", "old docs");
        assertEquals(1, store.importFiles(List.of(n), older).generation());
        assertNull(store.overview().get("activeGeneration"));
        var first = store.claim(1L, 10, 50);
        assertEquals("note.md", store.next(first.generation()).filename());
        store.save(
                first, "note.md", json.createObjectNode().putArray("chunks").add("first"), 15, 50);
        store.publish(first, 20);
        assertEquals(1L, store.overview().get("activeGeneration"));
        assertEquals(1, store.importFiles(List.of(n), older).generation());
        assertEquals(
                409,
                assertThrows(
                                ResponseStatusException.class,
                                () ->
                                        store.importFiles(
                                                List.of(),
                                                new LibraryStore.Source(
                                                        "guide", "v1", "guide.md", "changed")))
                        .getStatusCode()
                        .value());
        store.importFiles(List.of(new LibraryStore.Doc("note.md", "updated")), null);
        var abandoned = store.claim(2L, 100, 10);
        var resumed = store.claim(2L, 111, 10);
        assertNotNull(resumed);
        assertFalse(store.save(abandoned, "note.md", json.createObjectNode(), 112, 10));
        store.importFiles(List.of(), new LibraryStore.Source("guide", "v2", "new.md", "new docs"));
        assertFalse(store.publish(resumed, 113));
        assertEquals(1L, store.overview().get("activeGeneration"));
        assertEquals(1L, store.searchSnapshot(1L, "guide", "v1", "v1").generation());
    }

    @Test
    void failedJobResumesRemainingNotesAndBecomesSearchableOnceComplete() {
        long gen =
                store.importFiles(
                                List.of(
                                        new LibraryStore.Doc("a.md", "A"),
                                        new LibraryStore.Doc("b.md", "B")),
                                null)
                        .generation();
        long now = System.currentTimeMillis();
        var lease = store.claim(gen, now, 120_000);
        store.save(lease, "a.md", json.createObjectNode(), now, 120_000);
        store.fail(lease, "test failure");
        var retry = store.retry(gen);
        assertEquals("queued", retry.status());
        assertEquals(1, retry.done());
        assertEquals("b.md", store.next(gen).filename());
        var recovered = store.claim(null, now, 120_000);
        assertFalse(store.publish(recovered, now));
        store.save(recovered, "b.md", json.createObjectNode(), now, 120_000);
        assertTrue(store.publish(recovered, now));
        assertEquals(2, store.documents(gen).size());
        assertNull(store.nextNotification(now));
        assertEquals(
                409,
                assertThrows(ResponseStatusException.class, () -> store.retry(gen))
                        .getStatusCode()
                        .value());
        assertEquals(
                409,
                assertThrows(
                                ResponseStatusException.class,
                                () ->
                                        store.importFiles(
                                                List.of(
                                                        new LibraryStore.Doc(
                                                                "A.md", "different name casing")),
                                                null))
                        .getStatusCode()
                        .value());
    }

    @Test
    void publishesSourcesWithoutNotesAndRetainsThePriorSources() {
        var first =
                store.importFiles(
                        List.of(), new LibraryStore.Source("guide", "1", "guide.md", "before"));
        long now = System.currentTimeMillis();
        assertTrue(store.publish(store.claim(first.generation(), now, 2000), now));
        var next =
                store.importFiles(
                        List.of(), new LibraryStore.Source("guide", "2", "guide.md", "after"));
        assertEquals(next.generation(), store.nextNotification(now));
        store.notified(next.generation(), true, now);
        assertNull(store.nextNotification(now));
        assertThrows(
                ResponseStatusException.class, () -> store.searchSnapshot(null, "guide", "1", "2"));
        assertTrue(store.publish(store.claim(next.generation(), now, 2000), now));
        var pair = store.searchSnapshot(null, "guide", "1", "2");
        assertEquals(LibraryStore.digest("before"), pair.before().digest());
        assertEquals("after", pair.after().source().content());
        assertEquals(
                first.generation(),
                store.searchSnapshot(first.generation(), "guide", "1", "1").generation());
    }
}
