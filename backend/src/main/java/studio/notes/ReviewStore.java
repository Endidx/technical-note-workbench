package studio.notes;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.List;
import java.util.Set;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
public class ReviewStore {
    private final JdbcTemplate db;
    private final ObjectMapper json;

    public ReviewStore(JdbcTemplate db, ObjectMapper json) {
        this.db = db;
        this.json = json;
    }

    @Transactional
    public void initialize(JsonNode notes) {
        if (!notes.isArray() || notes.isEmpty()) throw new IllegalArgumentException("Missing analyzer notes");
        db.execute("""
            CREATE TABLE IF NOT EXISTS review_note (
                id VARCHAR(160) PRIMARY KEY, snapshot LONGTEXT NOT NULL,
                decision VARCHAR(10) NOT NULL, revision BIGINT NOT NULL, visible BOOLEAN NOT NULL, draft LONGTEXT
            )
            """);
        db.execute("""
            CREATE TABLE IF NOT EXISTS review_application (
                note_id VARCHAR(160) NOT NULL, revision BIGINT NOT NULL,
                content LONGTEXT NOT NULL, previous_revision BIGINT NOT NULL,
                previous_decision VARCHAR(10) NOT NULL, PRIMARY KEY (note_id, revision)
            )
            """);
        db.update("UPDATE review_note SET visible = false WHERE id NOT LIKE 'library-%'");
        for (var note : notes) {
            String id = note.required("id").textValue();
            String snapshot = note.toString();
            List<String> previous = db.queryForList("SELECT snapshot FROM review_note WHERE id = ?", String.class, id);
            if (previous.isEmpty()) {
                db.update("INSERT INTO review_note VALUES (?, ?, 'pending', 0, true, NULL)", id, snapshot);
            } else if (previous.get(0).equals(snapshot)) {
                db.update("UPDATE review_note SET visible = true WHERE id = ?", id);
            } else {
                db.update("UPDATE review_note SET snapshot = ?, decision = 'pending', revision = revision+1, visible = true WHERE id = ?", snapshot, id);
            }
        }
    }

    @Transactional
    public ObjectNode openImported(ObjectNode note) {
        String id = note.required("id").asText();
        try {
            db.update("INSERT INTO review_note VALUES (?, ?, 'pending', 0, true, NULL)", id, note.toString());
        } catch (org.springframework.dao.DuplicateKeyException alreadyOpen) {
            // Reopening the same immutable task preserves all reviews and revisions.
        }
        return read(id);
    }

    private static final String SELECT_NOTE = """
        SELECT n.snapshot, n.decision, n.revision, n.draft, a.content FROM review_note n
        LEFT JOIN review_application a ON a.note_id=n.id AND a.revision=n.revision
        """;

    public List<ObjectNode> list() {
        return db.query(SELECT_NOTE + "WHERE n.visible = true ORDER BY n.id",
            (rs, row) -> present(rs.getString(1), rs.getString(2), rs.getLong(3), rs.getString(4), rs.getString(5)));
    }

    public ObjectNode read(String id) {
        var rows = db.query(SELECT_NOTE + "WHERE n.id = ? AND n.visible = true",
            (rs, row) -> present(rs.getString(1), rs.getString(2), rs.getLong(3), rs.getString(4), rs.getString(5)), id);
        if (rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "找不到笔记");
        return rows.get(0);
    }

    private ObjectNode present(String snapshot, String decision, long revision, String draft, String approved) {
        ObjectNode note;
        try {
            note = (ObjectNode) json.readTree(snapshot);
        } catch (Exception ex) {
            throw new IllegalStateException("Invalid saved snapshot", ex);
        }
        note.put("decision", decision);
        note.put("revision", revision);
        String original = note.get("original").textValue();
        String working = draft == null ? original : draft;
        String candidate = note.hasNonNull("proposed")
            ? patch(original, note.get("proposed").textValue(), working) : null;
        note.put("patchConflict", note.hasNonNull("proposed") && candidate == null);
        String baseline = decision.equals("accept") ? candidate : working;
        note.put("current", approved == null ? baseline : approved);
        return note;
    }

    // The first analyzer changes exactly one code line. A unique unchanged line
    // is a stable anchor even if the user has edited surrounding paragraphs.
    private static String patch(String original, String proposed, String working) {
        if (working.equals(original)) return proposed;
        String[] oldLines = original.split("\\n", -1);
        String[] newLines = proposed.split("\\n", -1);
        if (oldLines.length != newLines.length) return null;
        int changed = -1;
        for (int i = 0; i < oldLines.length; i++) {
            if (!oldLines[i].equals(newLines[i])) {
                if (changed >= 0) return null;
                changed = i;
            }
        }
        if (changed < 0) return working;
        String[] currentLines = working.split("\\n", -1);
        int anchor = -1;
        for (int i = 0; i < currentLines.length; i++) {
            if (currentLines[i].equals(oldLines[changed])) {
                if (anchor >= 0) return null;
                anchor = i;
            }
        }
        if (anchor < 0) return null;
        currentLines[anchor] = newLines[changed];
        return String.join("\n", currentLines);
    }

    @Transactional
    public ObjectNode edit(String id, String content, long revision) {
        if (content == null || content.length() > 500_000 || revision < 0)
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "无效的笔记内容或版本");
        read(id);
        int updated = db.update("UPDATE review_note SET draft = ?, decision = 'pending', revision = revision+1 WHERE id = ? AND revision = ? AND visible = true",
            content, id, revision);
        if (updated == 0) throw new ResponseStatusException(HttpStatus.CONFLICT, "笔记已更新，请核对最新版本");
        return read(id);
    }

    @Transactional
    public ObjectNode decide(String id, String decision, long revision) {
        if (decision == null || !Set.of("accept", "keep", "pending").contains(decision) || revision < 0)
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "审阅决定或版本无效");
        ObjectNode note = read(id);
        if (decision.equals("accept") && !note.hasNonNull("proposed"))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "该笔记没有可应用的修改");
        if (decision.equals("accept") && note.get("patchConflict").asBoolean())
            throw new ResponseStatusException(HttpStatus.CONFLICT, "建议的目标行已被手动修改或不再唯一，请核对当前笔记");
        var priorDecisions = db.queryForList("SELECT previous_decision FROM review_application WHERE note_id = ? AND revision = ?",
            String.class, id, revision);
        boolean undoInvestigation = decision.equals("pending") && !priorDecisions.isEmpty();
        String next = undoInvestigation ? priorDecisions.get(0) : decision;
        int updated = db.update("UPDATE review_note SET decision = ?, revision = revision+1 WHERE id = ? AND revision = ? AND visible = true",
            next, id, revision);
        if (updated == 1 && undoInvestigation) {
            // Reattach the earlier application when two approvals were made in succession.
            db.update("""
                INSERT INTO review_application (note_id, revision, content, previous_revision, previous_decision)
                SELECT older.note_id, ?, older.content, older.previous_revision, older.previous_decision
                FROM review_application recent JOIN review_application older
                  ON older.note_id=recent.note_id AND older.revision=recent.previous_revision
                WHERE recent.note_id=? AND recent.revision=?
                """, revision + 1, id, revision);
        }
        if (updated == 0)
            throw new ResponseStatusException(HttpStatus.CONFLICT, "这篇笔记的版本已变更，请刷新并重新核对");
        return read(id);
    }
    @Transactional
    public ObjectNode applyInvestigation(String id, long revision, String proposed) {
        var note = read(id);
        String approved = proposed == null ? note.path("current").asText() : proposed;
        if (approved.length() > 500_000)
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "建议超出内容长度上限");
        String decision = proposed == null ? "keep" : "accept";
        int updated = db.update("UPDATE review_note SET decision=?, revision=revision+1 WHERE id=? AND revision=? AND visible=true",
            decision, id, revision);
        if (updated == 0)
            throw new ResponseStatusException(HttpStatus.CONFLICT, "笔记已变化，请在当前版本重新调查");
        db.update("INSERT INTO review_application (note_id, revision, content, previous_revision, previous_decision) VALUES (?,?,?,?,?)",
            id, revision + 1, approved, revision, note.path("decision").asText());
        return read(id);
    }
}
