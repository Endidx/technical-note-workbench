package studio.notes.library;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.annotation.PostConstruct;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowCallbackHandler;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.*;
import java.util.regex.Pattern;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

import static studio.notes.library.LibraryStore.error;

@Repository
public class BatchStore {
    public record Request(String instruction, String name, String fromVersion, String toVersion, Long generation) {}
    public record Lease(String id, String token, Request request) {}
    public record Pending(int number, String filename) {}

    private final JdbcTemplate db;
    private final LibraryStore library;
    private final ObjectMapper json;
    // Covers both source restores, one note restore, and the analyzer subprocess timeout.
    private final long leaseMs;

    public BatchStore(JdbcTemplate db, LibraryStore library, ObjectMapper json,
                      @Value("${review.batch.lease-ms:120000}") long leaseMs) {
        if (leaseMs <= 0) throw new IllegalArgumentException("review.batch.lease-ms must be positive");
        this.leaseMs = leaseMs;
        this.db = db;
        this.library = library;
        this.json = json;
    }

    @PostConstruct
    public void initialize() {
        db.execute("""
                CREATE TABLE IF NOT EXISTS library_batch (
                    id VARCHAR(36) PRIMARY KEY, gen BIGINT NOT NULL, instruction VARCHAR(1024) NOT NULL,
                    source_name VARCHAR(120) NOT NULL, from_version VARCHAR(120) NOT NULL, to_version VARCHAR(120) NOT NULL,
                    created_at BIGINT NOT NULL, status VARCHAR(16) NOT NULL, last_error VARCHAR(512),
                    owner_token VARCHAR(36), lease_until BIGINT NOT NULL)
                """);
        db.execute("""
                CREATE TABLE IF NOT EXISTS library_batch_item (
                    batch_id VARCHAR(36) NOT NULL, item_no INT NOT NULL, filename VARCHAR(180) NOT NULL,
                    result_doc LONGTEXT, accepted BOOLEAN NOT NULL, PRIMARY KEY(batch_id,item_no))
                """);
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public String create(Request request) {
        LibraryController.label(request.name());
        LibraryController.label(request.fromVersion());
        LibraryController.label(request.toVersion());
        if (request.fromVersion().equals(request.toVersion()))
            throw error(HttpStatus.BAD_REQUEST, "请选择两个不同版本");
        requireMigration(request);
        var corpus = library.searchSnapshot(request.generation(), request.name(), request.fromVersion(), request.toVersion());
        List<String> filenames = new ArrayList<>();
        corpus.documents().forEach(doc -> filenames.add(doc.path("filename").textValue()));
        return insert(UUID.randomUUID().toString(), request, corpus.generation(), filenames);
    }

    String insert(String id, Request request, long generation, List<String> filenames) {
        db.update("""
                INSERT INTO library_batch (id,gen,instruction,source_name,from_version,to_version,created_at,status,lease_until)
                VALUES (?,?,?,?,?,?,?,'running',0)
                """, id, generation, request.instruction(), request.name(), request.fromVersion(),
                request.toVersion(), System.currentTimeMillis());
        int number = 0;
        for (String filename : filenames) {
            db.update("INSERT INTO library_batch_item (batch_id,item_no,filename,accepted) VALUES (?,?,?,false)",
                    id, ++number, filename);
        }
        return id;
    }

    // Only recognize commands whose complete scope and direction can be honored.
    private static void requireMigration(Request r) {
        if (r.instruction() == null || r.instruction().isBlank() || r.instruction().length() > 1024)
            throw error(HttpStatus.BAD_REQUEST, "请输入批量更新指令，最多 1024 个字符");
        String text = r.instruction().strip().replaceAll("[。.!！]+$", "").strip();
        String[] clauses = text.split("[。！；，,;]+\\s*");
        String source = "(?:(?:" + Pattern.quote(r.name()) + "|scikit-learn)\\s*)?";
        String before = source + Pattern.quote(r.fromVersion());
        String after = "(?:目标版本|所选(?:的)?(?:目标)?版本|新版(?:本)?|" + source + Pattern.quote(r.toVersion()) + ")";
        String action = "(?:更新|升级|迁移|适配)";
        String notes = "(?:(?:资料库(?:中|里)?的?|库中的?)?(?:这批|这组|这几篇|这些|全部|所有)?"
                + source + "(?:学习|技术|Markdown)?笔记)";
        String zh = "(?:请)?(?:帮我|帮忙)?(?:把|将)?(?:" + notes + ")?(?:从\\s*" + before + "\\s*)?"
                + action + "(?:" + notes + ")?(?:到|至|为)\\s*" + after;
        String en = "(?i:(?:please\\s+)?(?:update|upgrade|migrate)\\s+(?:(?:all |these |the )?notes\\s+)?"
                + "(?:from\\s+" + before + "\\s+)?to\\s+(?:(?:the )?(?:selected |target |new )version|"
                + source + Pattern.quote(r.toVersion()) + "))";
        boolean migration = clauses.length > 0 && (clauses[0].replaceAll("\\s+", "").matches(zh) || clauses[0].matches(en));
        boolean supportedOutput = Arrays.stream(clauses).skip(1).map(String::strip).allMatch(BatchStore::reportInstruction);
        if (!migration || !supportedOutput)
            throw error(HttpStatus.UNPROCESSABLE_ENTITY,
                    "请明确要求将这批笔记更新到所选目标版本，例如“帮我把这批笔记升级到 " + r.toVersion() + "”。");
    }

    private static boolean reportInstruction(String clause) {
        return clause.matches("(?:请)?(?:对|把|将)?(?:(?:需要修改|需要改|需修改|要改)(?:的)?(?:笔记)?)?"
                        + "(?:逐篇|分别)?(?:列出|展示|显示|给出)(?:修改)?(?:差异|建议|补丁)")
                || clause.matches("(?:请)?(?:对|把|将)?(?:已经|已)?兼容的(?:笔记)?(?:告诉我|说明|解释|给出)(?:保留)?原因")
                || clause.matches("(?:请)?(?:对|把|将)?(?:缺(?:少)?(?:信息|资料|证据)|信息不足|不确定)的?"
                        + "(?:笔记|问题)?(?:集中|统一|汇总)?(?:问我|提问|向我提问|询问)");
    }

    public Lease claim(long now) {
        var eligible = db.queryForList("""
                SELECT id FROM library_batch WHERE status='running' AND lease_until<=?
                ORDER BY created_at,id LIMIT 1
                """, String.class, now);
        if (eligible.isEmpty()) return null;
        String id = eligible.get(0);
        String token = UUID.randomUUID().toString();
        int changed = db.update("""
                UPDATE library_batch SET owner_token=?,lease_until=?
                WHERE id=? AND status='running' AND lease_until<=?
                """, token, now + leaseMs, id, now);
        if (changed == 0) return null;
        return db.queryForObject("SELECT * FROM library_batch WHERE id=?",
                (r, i) -> new Lease(id, token, request(r)), id);
    }

    private Request request(ResultSet r) throws SQLException {
        return new Request(r.getString("instruction"), r.getString("source_name"),
                r.getString("from_version"), r.getString("to_version"), r.getLong("gen"));
    }

    public List<Pending> remaining(String id) {
        return db.query("""
                SELECT item_no,filename FROM library_batch_item WHERE batch_id=? AND result_doc IS NULL ORDER BY item_no
                """, (r,i) -> new Pending(r.getInt(1), r.getString(2)), id);
    }

    @Transactional
    public boolean save(Lease lease, Pending item, ObjectNode result, long now) {
        int owned = db.update("""
                UPDATE library_batch SET lease_until=? WHERE id=? AND owner_token=? AND status='running' AND lease_until>?
                """, now + leaseMs, lease.id(), lease.token(), now);
        if (owned == 0) return false;
        db.update("UPDATE library_batch_item SET result_doc=? WHERE batch_id=? AND item_no=? AND result_doc IS NULL",
                result.toString(), lease.id(), item.number());
        return true;
    }

    public void finish(Lease lease, long now) {
        db.update("""
                UPDATE library_batch SET status='complete',owner_token=NULL WHERE id=? AND owner_token=? AND status='running' AND lease_until>?
                AND NOT EXISTS (SELECT 1 FROM library_batch_item WHERE batch_id=? AND result_doc IS NULL)
                """, lease.id(), lease.token(), now, lease.id());
    }

    public void fail(Lease lease, String message, long now) {
        db.update("UPDATE library_batch SET status='failed',last_error=?,owner_token=NULL WHERE id=? AND owner_token=? AND status='running' AND lease_until>?",
                message.substring(0, Math.min(message.length(), 512)), lease.id(), lease.token(), now);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public ObjectNode get(String id) {
        var rows = db.query("SELECT * FROM library_batch WHERE id=?", (r, i) -> {
            var header = json.<ObjectNode>valueToTree(request(r));
            header.put("id", id).put("status", r.getString("status"));
            if (r.getString("last_error") != null) header.put("error", r.getString("last_error"));
            return header;
        }, id);
        if (rows.isEmpty()) throw error(HttpStatus.NOT_FOUND, "找不到批量任务");
        var header = rows.get(0);
        var items = header.putArray("items");
        int total = db.queryForObject("SELECT COUNT(*) FROM library_batch_item WHERE batch_id=?", Integer.class, id);
        db.query("""
                SELECT i.item_no,i.filename,i.result_doc,i.accepted,b.body,b.digest FROM library_batch_item i
                JOIN library_document d ON d.gen=? AND d.filename=i.filename JOIN library_blob b ON b.digest=d.digest
                WHERE i.batch_id=? AND i.result_doc IS NOT NULL ORDER BY i.item_no
                """, (RowCallbackHandler) r -> {
            String original = r.getString("body");
            if (!LibraryStore.digest(original).equals(r.getString("digest")))
                throw error(HttpStatus.INTERNAL_SERVER_ERROR, "笔记原件摘要不匹配");
            var item = decode(r.getString("result_doc"));
            item.put("id", Integer.toString(r.getInt("item_no"))).put("filename", r.getString("filename"))
                    .put("original", original).put("accepted", r.getBoolean("accepted"));
            if (!item.hasNonNull("proposed")) item.put("proposed", original);
            items.add(item);
        }, header.path("generation").asLong(), id);
        if (header.path("status").asText().equals("complete") && items.size() != total)
            throw error(HttpStatus.INTERNAL_SERVER_ERROR, "批量任务缺少原件");
        return header.put("done", items.size()).put("total", total);
    }

    private ObjectNode decode(String result) {
        try {
            return (ObjectNode) json.readTree(result);
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException("批量调查记录损坏", ex);
        }
    }

    @Transactional
    public void accept(String id, String key) {
        int number;
        try {
            number = Integer.parseInt(key);
        } catch (NumberFormatException invalid) {
            throw error(HttpStatus.NOT_FOUND, "找不到此笔记");
        }
        var items = db.query("""
                SELECT i.result_doc FROM library_batch_item i JOIN library_batch b ON b.id=i.batch_id
                WHERE i.batch_id=? AND i.item_no=? FOR UPDATE
                """, (r,i) -> r.getString(1), id, number);
        if (items.isEmpty()) throw error(HttpStatus.NOT_FOUND, "找不到此笔记");
        if (items.get(0) == null || !decode(items.get(0)).path("status").asText().equals("edit"))
            throw error(HttpStatus.CONFLICT, "仅可接受有补丁的调查结果");
        db.update("UPDATE library_batch_item SET accepted=true WHERE batch_id=? AND item_no=? AND accepted=false", id, number);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public byte[] export(String id) {
        var batch = get(id);
        if (!batch.path("status").asText().equals("complete"))
            throw error(HttpStatus.CONFLICT, "请等待批量调查完成后导出");
        var out = new ByteArrayOutputStream();
        try (var zip = new ZipOutputStream(out, StandardCharsets.UTF_8)) {
            for (var item : batch.path("items")) {
                zip.putNextEntry(new ZipEntry(item.path("filename").asText()));
                var text = item.path(item.path("accepted").asBoolean() ? "proposed" : "original").textValue();
                zip.write(text.getBytes(StandardCharsets.UTF_8));
                zip.closeEntry();
            }
        } catch (IOException ex) {
            throw new UncheckedIOException(ex);
        }
        return out.toByteArray();
    }
}
