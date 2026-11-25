package studio.notes.library;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;
import java.util.concurrent.*;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = {
        "spring.datasource.url=jdbc:h2:mem:library-demo;MODE=MySQL;DB_CLOSE_DELAY=-1",
        "review.analysis-file=../analysis.json", "review.library.poll-ms=3600000", "review.batch.poll-ms=3600000"
})
@AutoConfigureMockMvc
class LibraryDemoTest {
    @Autowired MockMvc mvc;
    @Autowired ObjectMapper json;
    @Autowired LibraryStore library;
    @Autowired BatchStore batches;
    @Autowired JdbcTemplate db;

    private JsonNode openDemo() throws Exception {
        var response = mvc.perform(post("/api/library/demo")).andExpect(status().isOk()).andReturn().getResponse();
        return json.readTree(response.getContentAsByteArray());
    }

    @Test void addsOnlyMissingMaterialsAndReopensOnlyTheFiveDemoNotes() throws Exception {
        library.importFiles(List.of(new LibraryStore.Doc("01-config.md", "private draft")),
                new LibraryStore.Source("scikit-learn", "1.4.2", "private.md", "private source"));
        long generation = openDemo().required("generation").asLong();
        assertEquals(generation, openDemo().required("generation").asLong());
        assertEquals(2, generation);
        assertEquals("private draft", library.note(generation, "01-config.md").content());

        var lease = library.claim(generation, 1, 10000);
        while (library.next(generation) != null) {
            library.save(lease, library.next(generation).filename(), json.createObjectNode(), 2, 10000);
        }
        assertTrue(library.publish(lease, 3));
        var pool = Executors.newFixedThreadPool(2);
        String id;
        try {
            var first = pool.submit(this::openDemo);
            var second = pool.submit(this::openDemo);
            id = first.get(8, TimeUnit.SECONDS).required("id").asText();
            assertEquals(id, second.get(8, TimeUnit.SECONDS).required("id").asText());
        } finally {
            pool.shutdownNow();
        }
        assertEquals(5, batches.get(id).path("total").asInt());
        var files = batches.remaining(id).stream().map(BatchStore.Pending::filename).toList();
        assertFalse(files.contains("01-config.md"));
        assertTrue(files.contains("02-clustering.md"));
        var sourceName = batches.get(id).path("name").asText();
        assertNotEquals("scikit-learn", sourceName);
        assertTrue(library.searchSnapshot(generation, sourceName, "1.1.3", "1.4.2").after().source().content().contains("KMeans"));
        assertEquals("private.md", db.queryForObject("SELECT filename FROM library_source WHERE source_name='scikit-learn'", String.class));
        assertEquals(1, db.queryForObject("SELECT COUNT(*) FROM library_batch", Integer.class));
        library.importFiles(List.of(new LibraryStore.Doc("later.md", "user change")), null);
        assertEquals(id, openDemo().required("id").asText());
        assertEquals(3L, db.queryForObject("SELECT latest_gen FROM library_state WHERE slot=1", Long.class));
    }
}
