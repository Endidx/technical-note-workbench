package studio.notes;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.*;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestExecutionListeners;
import org.springframework.test.context.support.DependencyInjectionTestExecutionListener;
import org.springframework.web.server.ResponseStatusException;
import static org.junit.jupiter.api.Assertions.*;

@TestExecutionListeners(DependencyInjectionTestExecutionListener.class)
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.NONE, properties = {
    "spring.datasource.url=jdbc:h2:mem:receipts;MODE=MySQL;DB_CLOSE_DELAY=-1",
    "review.analysis-file=../analysis.json"
})
class IdempotentApprovalsTest {
    @Autowired IdempotentApprovals approvals;
    @Autowired ReviewStore notes;
    @Autowired JdbcTemplate db;
    @Autowired ObjectMapper json;

    private String seed() {
        String id = UUID.randomUUID().toString();
        var note = json.createObjectNode().put("id", id).put("original", "before").put("proposed","after");
        db.update("INSERT INTO review_note (id,snapshot,decision,revision,visible) VALUES (?,?, 'pending',0,true)",
            id, note.toString());
        var result = json.createObjectNode().put("decisionPolicy",HarnessService.POLICY).put("status","complete").put("proposed","after").put("revision",0);
        db.update("INSERT INTO harness_report (note_id,revision,round_no,report) VALUES (?,0,1,?)",id,result.toString());
        return id;
    }

    @Test void concurrentApplyAndReplayAfterUndoWriteOnlyOnce() throws Exception {
        String id = seed();
        var pool = Executors.newFixedThreadPool(2);
        var ready = new CountDownLatch(2);
        var go = new CountDownLatch(1);
        Callable<ObjectNode> apply = () -> {
            ready.countDown();
            assertTrue(go.await(5, TimeUnit.SECONDS));
            return approvals.apply(id,0);
        };
        try {
            var first = pool.submit(apply);
            var second = pool.submit(apply);
            assertTrue(ready.await(5,TimeUnit.SECONDS));
            go.countDown();
            var responses = List.of(first.get(10,TimeUnit.SECONDS), second.get(10,TimeUnit.SECONDS));
            assertEquals(1, responses.stream().filter(n->n.at("/approvalReceipt/replayed").booleanValue()).count());
            assertEquals(responses.get(0).at("/approvalReceipt/key"),responses.get(1).at("/approvalReceipt/key"));
            assertEquals(1,notes.read(id).get("revision").asInt());
            assertEquals(1,db.queryForObject("SELECT COUNT(*) FROM review_application WHERE note_id=?",Integer.class,id));
            notes.decide(id,"pending",1);
            var lateRetry=approvals.apply(id,0);
            assertEquals(1,lateRetry.at("/approvalReceipt/toRevision").asInt());
            assertEquals("before",notes.read(id).get("current").asText());
            assertEquals(2,notes.read(id).get("revision").asInt());
        } finally {pool.shutdownNow();}
    }

    @Test void receiptCannotBeReplayedByADifferentMode() {
        String id = seed();
        approvals.apply(id,0,IntentMode.RULE);
        assertTrue(approvals.apply(id,0).at("/approvalReceipt/replayed").asBoolean());
        assertEquals(409,assertThrows(ResponseStatusException.class,
            ()->approvals.apply(id,0,IntentMode.MODEL)).getStatusCode().value());
    }

    @Test void fixedWorkflowSharesRetryGuaranteeAndRejectsDifferentStaleDecision() {
        String id=seed();
        approvals.decide(id,"accept",0);
        assertTrue(approvals.decide(id,"accept",0).at("/approvalReceipt/replayed").asBoolean());
        assertEquals(409,assertThrows(ResponseStatusException.class,()->approvals.decide(id,"keep",0)).getStatusCode().value());
        assertEquals(409,assertThrows(ResponseStatusException.class,()->approvals.apply(id,0)).getStatusCode().value());
        assertEquals(1,notes.read(id).get("revision").asInt());
    }
}
