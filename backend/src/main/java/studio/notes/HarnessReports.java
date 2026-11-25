package studio.notes;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.annotation.PostConstruct;
import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Repository
public class HarnessReports {
    private final JdbcTemplate db;
    private final ObjectMapper json;
    private final ReviewStore notes;

    record Report(int round, ObjectNode result) {}
    record Checkpoint(int round, String fence, int steps, String answer, ObjectNode payload, ObjectNode facts) {}
    record Snapshot(ObjectNode note, Report report, Checkpoint checkpoint) {}
    record Owner(String id, long revision, int round, String fence, IntentMode mode) {}

    public HarnessReports(JdbcTemplate db, ObjectMapper json, ReviewStore notes) {
        this.db = db;
        this.json = json;
        this.notes = notes;
    }

    @PostConstruct
    public void initialize() {
        for (var mode : IntentMode.values()) initialize(mode);
    }

    private void initialize(IntentMode mode) {
        db.execute(mode.sql("""
            CREATE TABLE IF NOT EXISTS harness_report (
                note_id VARCHAR(160) NOT NULL, revision BIGINT NOT NULL, round_no INT NOT NULL,
                report LONGTEXT NOT NULL, PRIMARY KEY (note_id, revision, round_no)
            )
            """));
        db.execute(mode.sql("""
            CREATE TABLE IF NOT EXISTS harness_checkpoint (
                note_id VARCHAR(160) NOT NULL, revision BIGINT NOT NULL, round_no INT NOT NULL,
                fence VARCHAR(36) NOT NULL, steps INT NOT NULL, answer VARCHAR(16), payload LONGTEXT,
                PRIMARY KEY (note_id, revision)
            )
            """));
        db.execute(mode.sql("""
            CREATE TABLE IF NOT EXISTS harness_mapping_answer (
                note_id VARCHAR(160) NOT NULL, revision BIGINT NOT NULL, round_no INT NOT NULL,
                facts LONGTEXT NOT NULL, PRIMARY KEY(note_id,revision,round_no)
            )
            """));
    }

    private ObjectNode parse(String text) {
        if (text == null) return null;
        try { return (ObjectNode) json.readTree(text); }
        catch (java.io.IOException ex) { throw new IllegalStateException("Invalid saved JSON", ex); }
    }

    private Checkpoint checkpoint(String id, long revision, IntentMode mode) {
        var rows = db.query(mode.sql("SELECT c.round_no,c.fence,c.steps,c.answer,c.payload,a.facts FROM harness_checkpoint c LEFT JOIN harness_mapping_answer a ON a.note_id=c.note_id AND a.revision=c.revision AND a.round_no=c.round_no WHERE c.note_id=? AND c.revision=?"),
            (rs, row) -> new Checkpoint(rs.getInt(1), rs.getString(2), rs.getInt(3), rs.getString(4), parse(rs.getString(5)), parse(rs.getString(6))),
            id, revision);
        return rows.isEmpty() ? null : rows.get(0);
    }

    private Report latest(String id, long revision, IntentMode mode) {
        List<Report> reports = db.query(mode.sql("""
            SELECT round_no, report FROM harness_report
            WHERE note_id = ? AND revision = ? ORDER BY round_no DESC LIMIT 1
            """), (rs, row) -> {
                try {
                    return new Report(rs.getInt(1), (ObjectNode) json.readTree(rs.getString(2)));
                } catch (java.io.IOException ex) {
                    throw new IllegalStateException("Invalid stored report", ex);
                }
            }, id, revision);
        return reports.isEmpty() ? null : reports.get(0);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public Snapshot snapshot(String id, Long expected) {
        return snapshot(id, expected, IntentMode.RULE);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public Snapshot snapshot(String id, Long expected, IntentMode mode) {
        ObjectNode note = notes.read(id);
        long revision = note.get("revision").longValue();
        if (expected != null && expected != revision) throw changed();
        return new Snapshot(note, latest(id, revision, mode), checkpoint(id, revision, mode));
    }

    private void lockNote(String id, long revision) {
        var locked = db.queryForList("SELECT revision FROM review_note WHERE id = ? AND visible = true FOR UPDATE", Long.class, id);
        if (locked.isEmpty() || locked.get(0) != revision) throw changed();
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public Owner claim(String id, long revision, int expectedRound, Checkpoint expected, String answer) {
        return claim(id,revision,expectedRound,expected,answer,null);
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public Owner claim(String id, long revision, int expectedRound, Checkpoint expected, String answer, ObjectNode facts) {
        return claim(id, revision, expectedRound, expected, answer, facts, IntentMode.RULE);
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public Owner claim(String id, long revision, int expectedRound, Checkpoint expected, String answer, ObjectNode facts, IntentMode mode) {
        lockNote(id, revision);
        var latest = latest(id, revision, mode);
        if ((latest == null ? 0 : latest.round()) != expectedRound) throw conflict();
        var saved = checkpoint(id, revision, mode);
        if (expected == null ? saved != null
                : saved == null || !saved.fence().equals(expected.fence()) || saved.steps() != expected.steps())
            throw conflict();
        var owner = new Owner(id, revision, expectedRound + 1, UUID.randomUUID().toString(), mode);
        if (saved == null) {
            db.update(mode.sql("INSERT INTO harness_checkpoint (note_id,revision,round_no,fence,steps,answer,payload) VALUES (?,?,?,?,0,?,NULL)"),
                id, revision, owner.round(), owner.fence(), answer);
            if (facts != null)
                db.update(mode.sql("INSERT INTO harness_mapping_answer (note_id,revision,round_no,facts) VALUES (?,?,?,?)"),
                    id,revision,owner.round(),facts.toString());
        } else {
            if (saved.round() != owner.round()) throw conflict();
            db.update(mode.sql("UPDATE harness_checkpoint SET fence=? WHERE note_id=? AND revision=?"),owner.fence(),id,revision);
        }
        return owner;
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public void saveStep(Owner owner, int previousCount, ObjectNode payload) {
        IntentMode mode = owner.mode();
        lockNote(owner.id(), owner.revision());
        int changed = db.update(mode.sql("""
            UPDATE harness_checkpoint SET payload=?, steps=steps+1 WHERE note_id=? AND revision=?
                AND round_no=? AND fence=? AND steps=?
            """),payload.toString(),owner.id(),owner.revision(),owner.round(),owner.fence(),previousCount);
        if (changed != 1) throw conflict();
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public void finish(Owner owner, int expectedSteps, ObjectNode result) {
        IntentMode mode = owner.mode();
        lockNote(owner.id(), owner.revision());
        int deleted = db.update(mode.sql("""
            DELETE FROM harness_checkpoint WHERE note_id=? AND revision=? AND round_no=? AND fence=? AND steps=?
            """),owner.id(),owner.revision(),owner.round(),owner.fence(),expectedSteps);
        if (deleted != 1) throw conflict();
        db.update(mode.sql("INSERT INTO harness_report (note_id, revision, round_no, report) VALUES (?, ?, ?, ?)"),
            owner.id(), owner.revision(), owner.round(), result.toString());
    }

    private ResponseStatusException conflict() {
        return new ResponseStatusException(HttpStatus.CONFLICT, "调查已被另一请求接续或已完成，请重新读取");
    }

    private ResponseStatusException changed() {
        return new ResponseStatusException(HttpStatus.CONFLICT, "笔记版本已变更，请在当前版本重新调查");
    }
}
