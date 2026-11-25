package studio.notes.library;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.charset.StandardCharsets;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/library/batches/{batch}/items/{item}/clarify")
public class BatchClarifications {
    public record Answer(int revision, String draft) {}
    private record Task(long generation, String source, String from, String to,
                        String instruction, String filename, ObjectNode result) {}

    private final JdbcTemplate db;
    private final LibraryStore library;
    private final LibraryBridge bridge;
    private final BatchWorker worker;
    private final TransactionTemplate tx;
    private final ObjectMapper json;

    public BatchClarifications(JdbcTemplate db, LibraryStore library, LibraryBridge bridge,
                               BatchWorker worker, TransactionTemplate tx, ObjectMapper json) {
        this.db = db;
        this.library = library;
        this.bridge = bridge;
        this.worker = worker;
        this.tx = tx;
        this.json = json;
    }

    private Task read(String batch, int item, boolean lock) {
        var rows = db.query("""
            SELECT b.gen,b.source_name,b.from_version,b.to_version,b.instruction,i.filename,i.result_doc
            FROM library_batch b JOIN library_batch_item i ON i.batch_id=b.id
            WHERE b.id=? AND i.item_no=? AND b.status='complete'
            """ + (lock ? " FOR UPDATE" : ""), (rs, n) -> {
                try {
                    return new Task(rs.getLong(1), rs.getString(2), rs.getString(3), rs.getString(4),
                            rs.getString(5), rs.getString(6), (ObjectNode) json.readTree(rs.getString(7)));
                } catch (java.io.IOException e) {
                    throw new IllegalStateException("无法读取上次调查记录", e);
                }
            }, batch, item);
        if (rows.isEmpty()) throw LibraryStore.error(HttpStatus.NOT_FOUND, "未找到已完成批次中的笔记");
        return rows.get(0);
    }

    private void checkRevision(Task task, int revision) {
        if (!task.result().path("status").asText().equals("ask") ||
                task.result().path("clarificationRevision").asInt(0) != revision)
            throw LibraryStore.error(HttpStatus.CONFLICT, "此问题已更新，请刷新后查看最新调查");
    }

    @PostMapping
    public ObjectNode clarify(@PathVariable String batch, @PathVariable int item, @RequestBody Answer answer) {
        String draft = answer.draft();
        if (draft == null || draft.isBlank() || draft.indexOf(0) >= 0 ||
                draft.getBytes(StandardCharsets.UTF_8).length > 100_000)
            throw LibraryStore.error(HttpStatus.BAD_REQUEST, "补证后的笔记须为非空 Markdown，最多 100 KB");
        var task = read(batch, item, false);
        checkRevision(task, answer.revision());
        var note = library.note(task.generation(), task.filename());
        String original = bridge.restore(note.content(), note.digest());
        if (draft.equals(task.result().path("clarificationDraft").asText(original)))
            throw LibraryStore.error(HttpStatus.BAD_REQUEST, "请先在草稿中补充缺少的依据");
        var corpus = library.searchSnapshot(task.generation(), task.source(), task.from(), task.to());
        var input = json.createObjectNode().put("content", draft).put("filename", task.filename())
                .put("instruction", task.instruction());
        input.set("before", bridge.sourceInput(corpus.before()));
        input.set("after", bridge.sourceInput(corpus.after()));
        var result = worker.validate(bridge.engine("investigate_batch_note", input), draft);
        String status = result.path("status").asText();
        if (status.equals("irrelevant"))
            throw LibraryStore.error(HttpStatus.UNPROCESSABLE_ENTITY, "草稿中未找到迁移对象，请保留原调用并补充依据");
        if (status.equals("keep") && !original.equals(draft)) {
            result.put("status", "edit").put("proposed", draft)
                    .put("reason", "补证后的草稿已兼容。接受差异可将你的草稿写入导出文件。");
        }
        result.put("clarificationRevision", answer.revision()+1);
        result.put("clarificationDraft", draft);
        result.withArray("trace").insert(0, "按索引 G" + task.generation() + " 重新调查；上次待确认：" +
                task.result().path("question").asText());
        tx.executeWithoutResult(txStatus -> {
            checkRevision(read(batch, item, true), answer.revision());
            db.update("UPDATE library_batch_item SET result_doc=? WHERE batch_id=? AND item_no=?",
                    result.toString(), batch, item);
        });
        return result;
    }
}
