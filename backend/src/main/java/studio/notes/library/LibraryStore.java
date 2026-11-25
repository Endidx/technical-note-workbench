package studio.notes.library;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;

import jakarta.annotation.PostConstruct;

import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.*;

@Repository
public class LibraryStore {
    public record Doc(String filename, String content) {}

    public record Source(String name, String version, String filename, String content) {}

    public record Job(long id, long generation, String status, int done, int total, String error) {}

    public record Lease(long generation, String token) {}

    public record Pending(String filename, String content, String digest) {}

    public record StoredSource(Source source, String digest) {}

    public record Corpus(
            long generation, ArrayNode documents, StoredSource before, StoredSource after) {}

    private final JdbcTemplate db;
    private final ObjectMapper json;

    public LibraryStore(JdbcTemplate db, ObjectMapper json) {
        this.db = db;
        this.json = json;
    }

    @PostConstruct
    public void initialize() {
        db.execute(
                "CREATE TABLE IF NOT EXISTS library_state (slot INTEGER PRIMARY KEY, latest_gen"
                        + " BIGINT NOT NULL, active_gen BIGINT)");
        db.execute(
                "CREATE TABLE IF NOT EXISTS library_blob (digest CHAR(64) PRIMARY KEY, body"
                        + " LONGTEXT NOT NULL, size_bytes INTEGER NOT NULL)");
        db.execute(
                """
CREATE TABLE IF NOT EXISTS library_source (source_name VARCHAR(120) NOT NULL, version_name VARCHAR(120) NOT NULL,
    filename VARCHAR(180) NOT NULL, digest CHAR(64) NOT NULL, first_gen BIGINT NOT NULL, PRIMARY KEY(source_name, version_name))
""");
        db.execute(
                """
CREATE TABLE IF NOT EXISTS library_document (gen BIGINT NOT NULL, filename VARCHAR(180) NOT NULL,
    digest CHAR(64) NOT NULL, indexed_doc LONGTEXT, PRIMARY KEY(gen,filename))
""");
        db.execute(
                """
CREATE TABLE IF NOT EXISTS library_job (gen BIGINT PRIMARY KEY, status VARCHAR(16) NOT NULL, done_count INT NOT NULL,
    total_count INT NOT NULL, owner_token VARCHAR(40), lease_until BIGINT NOT NULL, last_error VARCHAR(512),
    enqueued BOOLEAN NOT NULL, notify_after BIGINT NOT NULL)
""");
        if (db.queryForObject("SELECT COUNT(*) FROM library_state WHERE slot=1", Integer.class)
                == 0) {
            try {
                db.update("INSERT INTO library_state VALUES (1,0,NULL)");
            } catch (DuplicateKeyException alreadyInitialized) {
                /* Another instance initialized the singleton. */
            }
        }
    }

    public static String digest(String content) {
        try {
            return HexFormat.of()
                    .formatHex(
                            MessageDigest.getInstance("SHA-256")
                                    .digest(content.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException unavailable) {
            throw new IllegalStateException(unavailable);
        }
    }

    private void addBlob(String key, String text) {
        if (db.queryForObject(
                        "SELECT COUNT(*) FROM library_blob WHERE digest=?", Integer.class, key)
                == 0)
            db.update(
                    "INSERT INTO library_blob VALUES (?,?,?)",
                    key,
                    text,
                    text.getBytes(StandardCharsets.UTF_8).length);
    }

    long lockState() {
        return db.queryForObject(
                "SELECT latest_gen FROM library_state WHERE slot=1 FOR UPDATE", Long.class);
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public Job importFiles(List<Doc> input, Source source) {
        return createGeneration(input, source == null ? List.of() : List.of(source), false);
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public Job reindex() {
        return createGeneration(List.of(), List.of(), true);
    }

    Job createGeneration(List<Doc> input, List<Source> sources, boolean rebuild) {
        long latest = lockState();
        if (rebuild && latest == 0) throw error(HttpStatus.CONFLICT, "请先导入资料");
        long gen = latest + 1;
        boolean newSource = false;
        for (Source source : sources) {
            var existing =
                    db.query(
                            "SELECT digest,filename FROM library_source WHERE source_name=? AND"
                                    + " version_name=?",
                            (r, i) -> List.of(r.getString(1), r.getString(2)),
                            source.name(),
                            source.version());
            String sha = digest(source.content());
            if (existing.isEmpty()) {
                newSource = true;
                addBlob(sha, source.content());
                db.update(
                        "INSERT INTO library_source VALUES (?,?,?,?,?)",
                        source.name(),
                        source.version(),
                        source.filename(),
                        sha,
                        gen);
            } else if (!existing.get(0).equals(List.of(sha, source.filename()))) {
                throw error(HttpStatus.CONFLICT, "这个来源版本已有另一份快照，请使用新的版本名");
            }
        }
        var previous = new LinkedHashMap<String, String>();
        db.query(
                "SELECT filename,digest FROM library_document WHERE gen=?",
                (org.springframework.jdbc.core.RowCallbackHandler)
                        r -> previous.put(r.getString(1), r.getString(2)),
                latest);
        var files = new LinkedHashMap<>(previous);
        var names = new TreeMap<String, String>(String.CASE_INSENSITIVE_ORDER);
        for (String filename : previous.keySet()) names.put(filename, filename);
        for (Doc note : input) {
            String canonical = names.put(note.filename(), note.filename());
            if (canonical != null && !canonical.equals(note.filename()))
                throw error(HttpStatus.CONFLICT, "文件名大小写与已有笔记冲突，请沿用已有拼写");
            files.put(note.filename(), digest(note.content()));
        }
        if (!rebuild && !newSource && files.equals(previous) && latest != 0) return job(latest);
        if (files.size() > 128
                || db.queryForObject("SELECT COUNT(*) FROM library_source", Integer.class) > 128)
            throw error(HttpStatus.PAYLOAD_TOO_LARGE, "资料库最多保存 128 篇笔记和 128 个来源版本");
        for (Doc note : input) addBlob(files.get(note.filename()), note.content());
        for (var item : files.entrySet())
            db.update(
                    "INSERT INTO library_document (gen,filename,digest) VALUES (?,?,?)",
                    gen,
                    item.getKey(),
                    item.getValue());
        long totalBytes =
                db.queryForObject(
                        """
SELECT (SELECT COALESCE(SUM(b.size_bytes),0) FROM library_document d JOIN library_blob b ON d.digest=b.digest WHERE d.gen=?)
     + (SELECT COALESCE(SUM(b.size_bytes),0) FROM library_source s JOIN library_blob b ON s.digest=b.digest)
""",
                        Long.class,
                        gen);
        if (totalBytes > 2_000_000) throw error(HttpStatus.PAYLOAD_TOO_LARGE, "资料库当前批次超过 2 MB");
        db.update(
                "UPDATE library_job SET status='superseded',owner_token=NULL WHERE status IN"
                        + " ('queued','running')");
        db.update(
                "INSERT INTO library_job VALUES (?,'queued',0,?,NULL,0,NULL,false,0)",
                gen,
                files.size());
        db.update("UPDATE library_state SET latest_gen=? WHERE slot=1", gen);
        return job(gen);
    }

    private Job mapJob(java.sql.ResultSet r, int row) throws java.sql.SQLException {
        return new Job(
                r.getLong("gen"),
                r.getLong("gen"),
                r.getString("status"),
                r.getInt("done_count"),
                r.getInt("total_count"),
                r.getString("last_error"));
    }

    private Job job(long gen) {
        var rows = db.query("SELECT * FROM library_job WHERE gen=?", this::mapJob, gen);
        if (rows.isEmpty()) throw error(HttpStatus.NOT_FOUND, "未找到索引任务");
        return rows.get(0);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public Map<String, Object> overview() {
        Long gen =
                db.queryForObject("SELECT active_gen FROM library_state WHERE slot=1", Long.class);
        var output = new LinkedHashMap<String, Object>();
        output.put("activeGeneration", gen);
        output.put(
                "notes",
                db.query(
                        "SELECT filename FROM library_document WHERE gen=? ORDER BY filename",
                        (r, i) -> Map.of("filename", r.getString(1)),
                        gen));
        output.put(
                "sources",
                db.query(
                        "SELECT source_name,version_name,filename FROM library_source WHERE"
                                + " first_gen<=? ORDER BY first_gen,source_name,version_name",
                        (r, i) ->
                                Map.of(
                                        "name",
                                        r.getString(1),
                                        "version",
                                        r.getString(2),
                                        "filename",
                                        r.getString(3)),
                        gen));
        output.put(
                "jobs",
                db.query("SELECT * FROM library_job ORDER BY gen DESC LIMIT 30", this::mapJob));
        return output;
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public Job retry(long gen) {
        if (lockState() != gen) throw error(HttpStatus.CONFLICT, "已有更新的导入，请重试最新任务");
        job(gen);
        int n =
                db.update(
                        """
UPDATE library_job SET status='queued',owner_token=NULL,lease_until=0,last_error=NULL,enqueued=false,notify_after=0
WHERE gen=? AND status='failed'
""",
                        gen);
        if (n == 0) throw error(HttpStatus.CONFLICT, "仅失败的任务可以重试");
        return job(gen);
    }

    public Lease claim(Long hint, long now, long ttl) {
        Long gen = hint;
        if (gen == null) {
            var eligible =
                    db.queryForList(
                            "SELECT gen FROM library_job WHERE status='queued' OR (status='running'"
                                    + " AND lease_until<=?) ORDER BY gen DESC LIMIT 1",
                            Long.class,
                            now);
            if (eligible.isEmpty()) return null;
            gen = eligible.get(0);
        }
        String token = UUID.randomUUID().toString();
        int n =
                db.update(
                        """
                        UPDATE library_job SET status='running',owner_token=?,lease_until=?
                        WHERE gen=? AND (status='queued' OR (status='running' AND lease_until<=?))
                        """,
                        token,
                        now + ttl,
                        gen,
                        now);
        return n == 1 ? new Lease(gen, token) : null;
    }

    public Pending next(long gen) {
        var remaining =
                db.query(
                        """
SELECT d.filename,b.body,b.digest FROM library_document d JOIN library_blob b ON d.digest=b.digest
WHERE d.gen=? AND d.indexed_doc IS NULL ORDER BY d.filename LIMIT 1
""",
                        (r, i) -> new Pending(r.getString(1), r.getString(2), r.getString(3)),
                        gen);
        return remaining.isEmpty() ? null : remaining.get(0);
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public boolean save(Lease lease, String filename, JsonNode index, long now, long ttl) {
        int owned =
                db.update(
                        "UPDATE library_job SET lease_until=? WHERE gen=? AND owner_token=? AND"
                                + " status='running' AND lease_until>?",
                        now + ttl,
                        lease.generation(),
                        lease.token(),
                        now);
        if (owned == 0) return false;
        int changed =
                db.update(
                        "UPDATE library_document SET indexed_doc=? WHERE gen=? AND filename=? AND"
                                + " indexed_doc IS NULL",
                        index.toString(),
                        lease.generation(),
                        filename);
        if (changed == 1)
            db.update(
                    "UPDATE library_job SET done_count=done_count+1 WHERE gen=?",
                    lease.generation());
        return true;
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public boolean publish(Lease lease, long now) {
        if (lockState() != lease.generation()) return false;
        int owned =
                db.update(
                        """
UPDATE library_job SET status='published',owner_token=NULL,last_error=NULL WHERE gen=? AND status='running'
AND owner_token=? AND lease_until>? AND done_count=total_count
""",
                        lease.generation(),
                        lease.token(),
                        now);
        if (owned == 1)
            db.update("UPDATE library_state SET active_gen=? WHERE slot=1", lease.generation());
        return owned == 1;
    }

    public void fail(Lease lease, String message) {
        db.update(
                "UPDATE library_job SET status='failed',last_error=?,owner_token=NULL WHERE gen=?"
                        + " AND status='running' AND owner_token=? AND lease_until>?",
                message,
                lease.generation(),
                lease.token(),
                System.currentTimeMillis());
    }

    public Long nextNotification(long now) {
        var rows =
                db.queryForList(
                        "SELECT gen FROM library_job WHERE status='queued' AND enqueued=false AND"
                                + " notify_after<=? ORDER BY gen LIMIT 1",
                        Long.class,
                        now);
        return rows.isEmpty() ? null : rows.get(0);
    }

    public void notified(long generation, boolean sent, long now) {
        db.update(
                "UPDATE library_job SET enqueued=?,notify_after=? WHERE gen=? AND enqueued=false",
                sent,
                now + 5000,
                generation);
    }

    public ArrayNode documents(long gen) {
        var docs = json.createArrayNode();
        db.query(
                "SELECT filename,indexed_doc FROM library_document WHERE gen=? ORDER BY filename",
                (org.springframework.jdbc.core.RowCallbackHandler)
                        r -> {
                            String payload = r.getString(2);
                            if (payload == null) throw new IllegalStateException("索引尚未完整");
                            try {
                                docs.addObject()
                                        .put("filename", r.getString(1))
                                        .set("index", json.readTree(payload));
                            } catch (java.io.IOException ex) {
                                throw new IllegalStateException("索引记录损坏", ex);
                            }
                        },
                gen);
        return docs;
    }

    public Pending note(long generation, String filename) {
        var rows = db.query("""
                SELECT d.filename,b.body,b.digest FROM library_document d
                JOIN library_blob b ON d.digest=b.digest WHERE d.gen=? AND d.filename=?
                """, (r,i) -> new Pending(r.getString(1), r.getString(2), r.getString(3)), generation, filename);
        if (rows.isEmpty()) throw error(HttpStatus.NOT_FOUND, "该索引中没有这篇笔记");
        return rows.get(0);
    }

    private StoredSource source(long gen, String name, String version) {
        var rows =
                db.query(
                        """
SELECT s.source_name,s.version_name,s.filename,b.body,b.digest FROM library_source s JOIN library_blob b ON s.digest=b.digest
WHERE s.first_gen<=? AND s.source_name=? AND s.version_name=?
""",
                        (r, i) ->
                                new StoredSource(
                                        new Source(
                                                r.getString(1),
                                                r.getString(2),
                                                r.getString(3),
                                                r.getString(4)),
                                        r.getString(5)),
                        gen,
                        name,
                        version);
        if (rows.isEmpty()) throw error(HttpStatus.NOT_FOUND, "该已发布索引内没有指定来源版本");
        return rows.get(0);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public Corpus searchSnapshot(Long requested, String name, String before, String after) {
        Long gen =
                requested != null
                        ? requested
                        : db.queryForObject(
                                "SELECT active_gen FROM library_state WHERE slot=1", Long.class);
        if (gen == null || !job(gen).status().equals("published"))
            throw error(HttpStatus.CONFLICT, "索引尚未发布");
        return new Corpus(gen, documents(gen), source(gen, name, before), source(gen, name, after));
    }

    static ResponseStatusException error(HttpStatus status, String message) {
        return new ResponseStatusException(status, message);
    }
}
