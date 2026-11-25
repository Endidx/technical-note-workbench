package studio.notes;

import static org.junit.jupiter.api.Assertions.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.*;
import java.util.function.Consumer;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.web.server.ResponseStatusException;

class CheckpointRecoveryTest {
    final ObjectMapper json = new ObjectMapper();
    final JdbcTemplate db = new JdbcTemplate(new DriverManagerDataSource("jdbc:h2:mem:" + UUID.randomUUID() + ";DB_CLOSE_DELAY=-1"));
    ReviewStore notes;
    final List<Integer> tools = new ArrayList<>();
    boolean simulateCrash;

    @BeforeEach void seed() throws Exception {
        notes = new ReviewStore(db, json);
        notes.initialize(json.readTree("[{\"id\":\"a\",\"filename\":\"a.md\",\"original\":\"content\",\"proposed\":null}]"));
    }

    HarnessService newServer() {
        var reports = new HarnessReports(db, json, notes);
        reports.initialize();
        var runner = new HarnessRunner(json, "") {
            @Override public ObjectNode investigate(ObjectNode input, Consumer<ObjectNode> checkpointEvent) {
                var trace = json.createArrayNode();
                if (input.has("checkpoint")) trace.addAll((com.fasterxml.jackson.databind.node.ArrayNode) input.get("checkpoint").get("trace"));
                for (int index = trace.size(); index < 3; index++) {
                    var step = json.createObjectNode().put("tool", "tool_" + index);
                    tools.add(index);
                    trace.add(step);
                    var cp = json.createObjectNode().put("version","kmeans-review-v18").put("planner", "offline");
                    cp.set("trace", trace.deepCopy());
                    var event = json.createObjectNode();
                    event.set("step", step);
                    event.set("checkpoint", cp);
                    checkpointEvent.accept(event);
                    if (simulateCrash) throw new IllegalStateException("injected crash");
                }
                var result = json.createObjectNode().put("decisionPolicy",HarnessService.POLICY).put("revision", 0).put("planner","offline").put("intentMode",input.path("intentMode").asText("rule"));
                result.set("trace", trace);
                if (input.has("answer")) return result.put("status","complete").put("proposed",input.get("answer").asText());
                return result.put("status","question").putNull("proposed").put("question","请选择").put("reason","缺少意图");
            }
        };
        return new HarnessService(reports,runner,notes,json);
    }

    @Test void oldCheckpointStartsOverWithoutCarryingItsPartialDecision() {
        var reports = new HarnessReports(db,json,notes);
        reports.initialize();
        var owner = reports.claim("a",0,0,null,"old");
        var cp=json.createObjectNode().put("version","kmeans-review-v17");
        cp.putArray("trace").addObject().put("tool","outdated");
        reports.saveStep(owner,0,cp);
        var service=newServer();
        assertEquals("blocked",service.current("a").path("status").asText());
        var fresh=service.run("a",0,null);
        assertEquals("question",fresh.path("status").asText());
        assertFalse(fresh.has("clarification"));
        assertTrue(fresh.path("replacesOldPolicy").asBoolean());
        assertEquals(List.of(0,1,2),tools);
    }

    @Test void restoresOnlyTheSelectedModesCheckpoint() {
        var service = newServer();
        service.run("a",0,null,2,step->{});
        assertNull(service.current("a",IntentMode.MODEL));
        service.run("a",0,null,null,1,step->{},IntentMode.MODEL);
        var restarted = newServer();
        assertEquals(1,restarted.run("a",0,null,null,null,step->{},IntentMode.MODEL).path("resumedSteps").asInt());
        assertEquals(2,restarted.current("a").path("checkpointSteps").asInt());
        assertEquals(2,restarted.run("a",0,null).path("resumedSteps").asInt());
    }

    @Test void restartsAtDurableBoundaryAndRecoversAnswerRound() {
        var first = newServer();
        simulateCrash = true;
        assertThrows(IllegalStateException.class, () -> first.run("a", 0, null));
        simulateCrash = false;
        var next = newServer();
        assertEquals(1, next.current("a").path("checkpointSteps").asInt());
        assertEquals("question", next.run("a", 0, null).path("status").asText());
        assertEquals(List.of(0,1,2), tools);
        assertEquals("paused", next.run("a", 0, "old", 2, step -> {}).path("status").asText());
        var resumed = newServer().run("a", 0, null);
        assertEquals("old", resumed.path("proposed").asText());
        assertEquals("old", resumed.path("clarification").path("answer").asText());
        assertEquals(List.of(0,1,2,0,1,2), tools);
    }

    @Test void newRevisionInvalidatesOldCheckpointAndApiCannotReplaceStoredAnswer() {
        var service = newServer();
        service.run("a",0,null);
        service.run("a",0,"old",1,step -> {});
        assertEquals(409, assertThrows(ResponseStatusException.class, () -> service.run("a",0,"default")).getStatusCode().value());
        notes.edit("a", "changed", 0);
        assertNull(service.current("a"));
        assertEquals(409, assertThrows(ResponseStatusException.class, () -> service.run("a",0,null)).getStatusCode().value());
    }

    @Test void replacementWorkerFencesOldWritesAndFinalization() {
        var reports = new HarnessReports(db, json, notes);
        reports.initialize();
        var original = reports.claim("a", 0, 0, null, null);
        var first = json.createObjectNode();
        first.putArray("trace").addObject().put("tool","first");
        reports.saveStep(original, 0, first);
        var saved = reports.snapshot("a", 0L).checkpoint();
        var recovery = reports.claim("a", 0, 0, saved, null);
        var next = first.deepCopy();
        next.withArray("trace").addObject().put("tool","second");
        assertEquals(409, assertThrows(ResponseStatusException.class,
            () -> reports.saveStep(original, 1, next)).getStatusCode().value());
        assertEquals(409, assertThrows(ResponseStatusException.class,
            () -> reports.finish(original, 1, json.createObjectNode())).getStatusCode().value());
        reports.saveStep(recovery, 1, next);
        var result = json.createObjectNode().put("status","complete");
        reports.finish(recovery, 2, result);
        assertNull(reports.snapshot("a", 0L).checkpoint());
        assertEquals(409, assertThrows(ResponseStatusException.class,
            () -> reports.claim("a", 0, 0, saved, null)).getStatusCode().value());
    }
}
