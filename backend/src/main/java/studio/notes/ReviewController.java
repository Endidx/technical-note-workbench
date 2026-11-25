package studio.notes;

import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/notes")
public class ReviewController {
    private final ReviewStore store;
    private final IdempotentApprovals approvals;
    public ReviewController(ReviewStore store, IdempotentApprovals approvals) {
        this.store = store;
        this.approvals = approvals;
    }
    public record ReviewDecision(String decision, Long revision) {}

    public record ManualEdit(String current, Long revision) {}

    @GetMapping
    public List<ObjectNode> list() { return store.list(); }

    @PostMapping(value = "/{id}", consumes = MediaType.APPLICATION_JSON_VALUE)
    public ObjectNode decide(@PathVariable String id, @RequestBody ReviewDecision request) {
        if (request.revision() == null) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "缺少版本号");
        return approvals.decide(id, request.decision(), request.revision());
    }
    @PostMapping(value = "/{id}/edit", consumes = MediaType.APPLICATION_JSON_VALUE)
    public ObjectNode edit(@PathVariable String id, @RequestBody ManualEdit edit) {
        if (edit.revision() == null) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "缺少版本号");
        return store.edit(id, edit.current(), edit.revision());
    }
}
