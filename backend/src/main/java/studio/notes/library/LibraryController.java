package studio.notes.library;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;

import java.nio.charset.StandardCharsets;
import java.util.*;
import studio.notes.ReviewStore;

@RestController
@RequestMapping("/api/library")
public class LibraryController {
    public record Import(List<LibraryStore.Doc> notes, LibraryStore.Source source) {}

    public record Search(
            String name, String fromVersion, String toVersion, String changeId, Long generation) {}

    private final LibraryStore store;
    private final LibraryBridge bridge;
    private final ObjectMapper json;
    private final ReviewStore reviews;

    public LibraryController(LibraryStore store, LibraryBridge bridge, ObjectMapper json, ReviewStore reviews) {
        this.reviews = reviews;
        this.store = store;
        this.bridge = bridge;
        this.json = json;
    }

    @GetMapping
    public Map<String, Object> overview() {
        return store.overview();
    }

    @PostMapping(value = "/import", consumes = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<LibraryStore.Job> upload(@RequestBody Import request) {
        List<LibraryStore.Doc> notes = request.notes() == null ? List.of() : request.notes();
        if (notes.size() > 32)
            throw LibraryStore.error(HttpStatus.PAYLOAD_TOO_LARGE, "每次最多导入 32 篇笔记");
        if (notes.isEmpty() && request.source() == null) throw bad("请选择至少一个 Markdown 文件");
        Set<String> names = new HashSet<>();
        for (var doc : notes) {
            if (doc == null) throw bad("笔记不能为空");
            checkDoc(doc.filename(), doc.content());
            if (!names.add(doc.filename().toLowerCase(Locale.ROOT))) throw bad("本次导入包含同名笔记，请先重命名");
        }
        var source = request.source();
        if (source != null) {
            label(source.name());
            label(source.version());
            checkDoc(source.filename(), source.content());
        }
        for (var doc : notes) bridge.archive(doc.content());
        if (source != null) bridge.archive(source.content());
        return ResponseEntity.accepted().body(store.importFiles(notes, source));
    }

    @PostMapping("/reindex")
    public ResponseEntity<LibraryStore.Job> reindex() {
        return ResponseEntity.accepted().body(store.reindex());
    }

    @PostMapping("/jobs/{id}/retry")
    public ResponseEntity<LibraryStore.Job> retry(@PathVariable long id) {
        return ResponseEntity.accepted().body(store.retry(id));
    }

    @PostMapping(value = "/search", consumes = MediaType.APPLICATION_JSON_VALUE)
    public ObjectNode search(@RequestBody Search request) {
        label(request.name());
        label(request.fromVersion());
        label(request.toVersion());
        if (request.fromVersion().equals(request.toVersion())) throw bad("请选择两个不同版本");
        if (request.changeId() != null && request.changeId().length() > 256) throw bad("变更编号过长");
        var snapshot =
                store.searchSnapshot(
                        request.generation(),
                        request.name(),
                        request.fromVersion(),
                        request.toVersion());
        var payload = bridge.corpus(snapshot.generation(), snapshot.documents());
        payload.set("before", bridge.sourceInput(snapshot.before()));
        payload.set("after", bridge.sourceInput(snapshot.after()));
        if (request.changeId() != null) payload.put("changeId", request.changeId());
        var result = bridge.engine("search", payload);
        if (!(result instanceof ObjectNode page)
                || !result.path("changes").isArray()
                || !result.path("hits").isArray())
            throw LibraryStore.error(HttpStatus.BAD_GATEWAY, "检索响应格式错误");
        return page.put("generation", snapshot.generation());
    }

    public record OpenReview(Search search, String filename) {}

    @PostMapping("/reviews")
    public ObjectNode openReview(@RequestBody OpenReview request) {
        var query = request.search();
        if (query == null || query.generation() == null || query.changeId() == null)
            throw bad("请从已发布的检索结果中选择变更");
        var page = search(query);
        if (!query.changeId().equals(page.path("selectedChangeId").asText()))
            throw bad("找不到所选变更");
        var hit = java.util.stream.StreamSupport.stream(page.path("hits").spliterator(), false)
                .filter(h -> h.path("filename").asText().equals(request.filename())).findFirst()
                .orElseThrow(() -> bad("该笔记未命中所选变更"));
        var corpus = store.searchSnapshot(query.generation(), query.name(), query.fromVersion(), query.toVersion());
        var doc = store.note(corpus.generation(), request.filename());
        var sources = json.createObjectNode();
        sources.set("before", bridge.sourceInput(corpus.before()));
        sources.set("after", bridge.sourceInput(corpus.after()));
        var note = json.createObjectNode();
        String key = json.valueToTree(request).toString();
        note.put("id", "library-" + LibraryStore.digest(key)).put("filename", doc.filename())
            .put("title", doc.filename()).put("original", bridge.restore(doc.content(), doc.digest()))
            .putNull("proposed").put("kind", "imported").put("reason", "根据导入的版本资料运行 Agent 调查。")
            .put("evidence", hit.path("text").asText()).put("generation", corpus.generation());
        note.set("librarySources", sources);
        return reviews.openImported(note);
    }

    static void label(String text) {
        if (text == null
                || text.isBlank()
                || !text.equals(text.strip())
                || text.length() > 120
                || text.chars().anyMatch(Character::isISOControl))
            throw bad("来源名和版本须为非空文本，最多 120 个字符");
    }

    private static void checkDoc(String name, String text) {
        if (name == null
                || name.length() > 180
                || !name.equals(name.strip())
                || name.contains("/")
                || name.contains("\\")
                || name.chars().anyMatch(Character::isISOControl)
                || !name.toLowerCase(Locale.ROOT).matches(".+\\.(md|markdown)"))
            throw bad("文件名须为 Markdown 文件的名称，不能包含路径");
        if (text == null || text.isBlank() || text.indexOf(0) >= 0)
            throw bad("文件内容须为非空 Markdown 文本");
        if (text.getBytes(StandardCharsets.UTF_8).length > 100_000)
            throw LibraryStore.error(HttpStatus.PAYLOAD_TOO_LARGE, "单篇 Markdown 内容上限为 100 KB");
    }

    private static org.springframework.web.server.ResponseStatusException bad(String message) {
        return LibraryStore.error(HttpStatus.BAD_REQUEST, message);
    }
}
