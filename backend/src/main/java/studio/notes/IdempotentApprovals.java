package studio.notes;

import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.annotation.PostConstruct;
import java.util.function.Supplier;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
public class IdempotentApprovals {
    private final JdbcTemplate db;
    private final ReviewStore notes;
    private final HarnessService harness;

    public IdempotentApprovals(JdbcTemplate db, ReviewStore notes, HarnessService harness) {
        this.db = db;
        this.notes = notes;
        this.harness = harness;
    }

    @PostConstruct
    public void initialize() {
        db.execute("""
            CREATE TABLE IF NOT EXISTS approval_receipt (
                note_id VARCHAR(160) NOT NULL, source_revision BIGINT NOT NULL,
                action_name VARCHAR(20) NOT NULL, applied_revision BIGINT NOT NULL,
                PRIMARY KEY (note_id, source_revision, action_name)
            )
            """);
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public ObjectNode apply(String id, long revision) {
        return apply(id,revision,IntentMode.RULE);
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public ObjectNode apply(String id, long revision, IntentMode mode) {
        return apply(id,revision,mode,null);
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public ObjectNode apply(String id, long revision, IntentMode mode, String reviewedPolicy) {
        String action = mode == IntentMode.RULE ? "harness-apply" : "harness-model-apply";
        var note = writeOnce(id, revision, action, () -> harness.apply(id,revision,mode,reviewedPolicy));
        note.withObject("/approvalReceipt").put("intentMode",mode.wire);
        return note;
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public ObjectNode decide(String id, String decision, long revision) {
        if (!"accept".equals(decision) && !"keep".equals(decision)) {
            return notes.decide(id,decision,revision);
        }
        return writeOnce(id, revision, "fixed-" + decision, () -> notes.decide(id,decision,revision));
    }

    private ObjectNode writeOnce(String id, long revision, String action, Supplier<ObjectNode> write) {
        // The same row lock serializes competing approvals, edits and undo operations.
        var locked = db.queryForList("SELECT revision FROM review_note WHERE id=? AND visible=true FOR UPDATE",
            Long.class, id);
        if (locked.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "找不到笔记");
        var receipts = db.queryForList("""
            SELECT applied_revision FROM approval_receipt WHERE note_id=? AND source_revision=? AND action_name=?
            """, Long.class, id, revision, action);
        boolean replay = !receipts.isEmpty();
        ObjectNode current;
        long applied;
        if (replay) {
            current = notes.read(id);
            applied = receipts.get(0);
        } else {
            if (locked.get(0) != revision)
                throw new ResponseStatusException(HttpStatus.CONFLICT, "笔记已更新，请核对当前版本");
            current = write.get();
            applied = current.required("revision").longValue();
            db.update("INSERT INTO approval_receipt (note_id,source_revision,action_name,applied_revision) VALUES (?,?,?,?)",
                id, revision, action, applied);
        }
        current.putObject("approvalReceipt").put("key", id + ":" + revision + ":" + action)
            .put("fromRevision", revision).put("toRevision", applied).put("replayed", replay);
        return current;
    }
}
