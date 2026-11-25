package studio.notes;

import static org.junit.jupiter.api.Assertions.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.web.server.ResponseStatusException;

class ReviewStoreTest {
    @Test void decisionsAreVersionedAndOriginalsAreRecoverable() throws Exception {
        var db = new JdbcTemplate(new DriverManagerDataSource("jdbc:h2:mem:reviews;DB_CLOSE_DELAY=-1"));
        var json = new ObjectMapper();
        var store = new ReviewStore(db, json);
        store.initialize(json.readTree("[{\"id\":\"a\",\"original\":\"before\",\"proposed\":\"after\"}]"));
        assertEquals("pending", store.list().get(0).path("decision").asText());
        assertEquals("after", store.decide("a", "accept", 0).path("current").asText());
        assertEquals(409, assertThrows(ResponseStatusException.class,
            () -> store.decide("a", "keep", 0)).getStatusCode().value());
        assertEquals("before", store.decide("a", "pending", 1).path("current").asText());
    }
    @Test void userEditsAreRetainedAndStaleTargetsAreRejected() throws Exception {
        var db = new JdbcTemplate(new DriverManagerDataSource("jdbc:h2:mem:edits;DB_CLOSE_DELAY=-1"));
        var json = new ObjectMapper();
        var store = new ReviewStore(db, json);
        store.initialize(json.readTree("[{\"id\":\"a\",\"original\":\"header\\nbefore\",\"proposed\":\"header\\nafter\"}]"));
        store.edit("a", "edited header\nbefore", 0);
        assertEquals("edited header\nafter", store.decide("a", "accept", 1).path("current").asText());
        assertEquals("edited header\nbefore", store.decide("a", "pending", 2).path("current").asText());
        store.edit("a", "edited header\nmanual", 3);
        assertEquals(409, assertThrows(ResponseStatusException.class,
            () -> store.decide("a", "accept", 4)).getStatusCode().value());
    }
}
