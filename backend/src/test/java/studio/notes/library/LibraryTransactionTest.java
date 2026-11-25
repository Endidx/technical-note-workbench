package studio.notes.library;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.concurrent.*;

@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.NONE,
        properties = {
            "spring.datasource.url=jdbc:h2:mem:library-transactions;MODE=MySQL;DB_CLOSE_DELAY=-1",
            "review.analysis-file=../analysis.json",
            "review.library.poll-ms=3600000"
        })
class LibraryTransactionTest {
    @Autowired LibraryStore store;
    @Autowired JdbcTemplate db;

    @Test
    void identicalConcurrentImportsShareGenerationAndRejectedImportRollsBackItsSource()
            throws Exception {
        assertThrows(ResponseStatusException.class, store::reindex);
        var notes = List.of(new LibraryStore.Doc("a.md", "A"));
        var source = new LibraryStore.Source("guide", "1", "guide.md", "before");
        var start = new CountDownLatch(1);
        Callable<Long> request =
                () -> {
                    start.await(5, TimeUnit.SECONDS);
                    return store.importFiles(notes, source).generation();
                };
        var pool = Executors.newFixedThreadPool(2);
        try {
            var first = pool.submit(request);
            var second = pool.submit(request);
            start.countDown();
            assertEquals(first.get(5, TimeUnit.SECONDS), second.get(5, TimeUnit.SECONDS));
        } finally {
            pool.shutdownNow();
        }
        assertEquals(1, db.queryForObject("SELECT COUNT(*) FROM library_job", Integer.class));
        var conflicting = List.of(new LibraryStore.Doc("A.md", "different"));
        var another = new LibraryStore.Source("guide", "2", "guide.md", "after");
        assertThrows(ResponseStatusException.class, () -> store.importFiles(conflicting, another));
        assertEquals(1, db.queryForObject("SELECT COUNT(*) FROM library_source", Integer.class));
        assertEquals(
                1,
                db.queryForObject(
                        "SELECT latest_gen FROM library_state WHERE slot=1", Integer.class));
        var rebuilt = store.reindex();
        assertEquals(2, rebuilt.generation());
        assertEquals(1, rebuilt.total());
        assertEquals(LibraryStore.digest("A"), store.next(rebuilt.generation()).digest());
        assertEquals(2, store.importFiles(notes, source).generation());
    }
}
