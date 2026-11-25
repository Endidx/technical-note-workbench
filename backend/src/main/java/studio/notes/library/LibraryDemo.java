package studio.notes.library;

import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

@RestController
@RequestMapping("/api/library/demo")
public class LibraryDemo {
    private static final String BATCH = "scikit-learn-upgrade-demo-v1";
    private static final List<String> FILENAMES = List.of("01-config.md", "02-clustering.md", "03-features.md",
            "04-ready.md", "05-stats.md");
    private static final List<String> VERSIONS = List.of("1.1.3", "1.4.2");
    private final JdbcTemplate db;
    private final LibraryStore library;
    private final LibraryBridge bridge;
    private final BatchStore batches;

    public LibraryDemo(JdbcTemplate db, LibraryStore library, LibraryBridge bridge, BatchStore batches) {
        this.db = db;
        this.library = library;
        this.bridge = bridge;
        this.batches = batches;
    }

    @PostMapping
    @Transactional(isolation = Isolation.READ_COMMITTED)
    public Map<String, Object> open() {
        long latest = library.lockState();
        if (db.queryForObject("SELECT COUNT(*) FROM library_batch WHERE id=?", Integer.class, BATCH) > 0) {
            db.update("UPDATE library_batch SET status='running',last_error=NULL,lease_until=0 WHERE id=? AND status='failed'", BATCH);
            return Map.of("id", BATCH);
        }

        var notes = new ArrayList<LibraryStore.Doc>();
        for (String filename : FILENAMES) {
            String content = read("notes/" + filename);
            String digest = LibraryStore.digest(content);
            String name = filename;
            for (int n = 1; ; n++) {
                var existing = db.query("SELECT filename,digest FROM library_document WHERE gen=? AND LOWER(filename)=LOWER(?)",
                        (r,i) -> List.of(r.getString(1), r.getString(2)), latest, name);
                if (existing.isEmpty() || existing.get(0).equals(List.of(name, digest))) break;
                name = (n == 1 ? "demo-" : "demo-" + n + "-") + filename;
            }
            notes.add(new LibraryStore.Doc(name, content));
        }
        var sources = sources();
        for (var note : notes) archiveIfNew(note.content());
        for (var source : sources) archiveIfNew(source.content());
        var job = library.createGeneration(notes, sources, false);
        if (job.status().equals("failed")) job = library.retry(job.generation());
        if (!job.status().equals("published")) return Map.of("generation", job.generation(), "job", job);

        var request = new BatchStore.Request("帮我更新到目标版本", sources.get(0).name(),
                VERSIONS.get(0), VERSIONS.get(1), job.generation());
        batches.insert(BATCH, request, job.generation(), notes.stream().map(LibraryStore.Doc::filename).toList());
        return Map.of("id", BATCH);
    }

    private List<LibraryStore.Source> sources() {
        var fixtures = new ArrayList<LibraryStore.Source>();
        for (String version : VERSIONS) {
            String filename = "sklearn-" + version + ".md";
            fixtures.add(new LibraryStore.Source("scikit-learn", version, filename, read("sources/" + filename)));
        }
        String name = "scikit-learn";
        for (int n = 1; ; n++) {
            boolean conflict = false;
            var sources = new ArrayList<LibraryStore.Source>();
            for (var fixture : fixtures) {
                var existing = db.query("SELECT source_name,filename,digest FROM library_source WHERE LOWER(source_name)=LOWER(?) AND version_name=?",
                        (r,i) -> List.of(r.getString(1), r.getString(2), r.getString(3)), name, fixture.version());
                if (!existing.isEmpty() && !existing.get(0).equals(List.of(name, fixture.filename(), LibraryStore.digest(fixture.content())))) {
                    conflict = true;
                    break;
                }
                sources.add(new LibraryStore.Source(name, fixture.version(), fixture.filename(), fixture.content()));
            }
            if (!conflict) return sources;
            name = n == 1 ? "scikit-learn (demo)" : "scikit-learn (demo " + n + ")";
        }
    }

    private void archiveIfNew(String content) {
        if (db.queryForObject("SELECT COUNT(*) FROM library_blob WHERE digest=?", Integer.class, LibraryStore.digest(content)) == 0)
            bridge.archive(content);
    }

    private static String read(String path) {
        try (var input = new ClassPathResource("batch-upgrade/" + path).getInputStream()) {
            return new String(input.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException ex) {
            throw new UncheckedIOException("无法读取随应用提供的演示资料", ex);
        }
    }
}
