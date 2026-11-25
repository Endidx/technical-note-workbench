package studio.notes.library;

import com.fasterxml.jackson.databind.node.ObjectNode;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequestMapping("/api/library/batches")
public class BatchController {
    private final BatchStore store;

    public BatchController(BatchStore store) {
        this.store = store;
    }

    @PostMapping
    public ResponseEntity<Map<String, String>> create(@RequestBody BatchStore.Request request) {
        return ResponseEntity.accepted().body(Map.of("id", store.create(request)));
    }

    @GetMapping("/{id}")
    public ObjectNode status(@PathVariable String id) {
        return store.get(id);
    }

    @PostMapping("/{id}/items/{itemId}/accept")
    public Map<String, Boolean> accept(@PathVariable String id, @PathVariable String itemId) {
        store.accept(id, itemId);
        return Map.of("accepted", true);
    }

    @GetMapping(value = "/{id}/export", produces = "application/zip")
    public ResponseEntity<byte[]> export(@PathVariable String id) {
        return ResponseEntity.ok().header(HttpHeaders.CONTENT_DISPOSITION,
                ContentDisposition.attachment().filename("notes-" + id + ".zip").build().toString())
                .body(store.export(id));
    }
}
