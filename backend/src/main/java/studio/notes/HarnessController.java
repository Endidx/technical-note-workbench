package studio.notes;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.*;
import java.nio.charset.StandardCharsets;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

@RestController
@RequestMapping("/api/notes/{id}/harness")
public class HarnessController {
    public record Investigation(Long revision, String answer, Integer pauseAfter, ObjectNode configFacts, String intentMode, String decisionPolicy) {}
    public record Approval(Long revision, String intentMode, String decisionPolicy) {}

    private final HarnessService harness;
    private final IdempotentApprovals approvals;
    private final ObjectMapper json;

    public HarnessController(HarnessService harness, ObjectMapper json, IdempotentApprovals approvals) {
        this.approvals = approvals;
        this.harness = harness;
        this.json = json;
    }

    private long version(Long revision) {
        if (revision == null || revision < 0) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "缺少有效版本号");
        return revision;
    }

    @GetMapping
    public ResponseEntity<ObjectNode> current(@PathVariable String id, @RequestParam(required=false) String intentMode) {
        var result = harness.current(id,IntentMode.parse(intentMode));
        return result == null ? ResponseEntity.noContent().build() : ResponseEntity.ok(result);
    }

    @PostMapping(consumes = MediaType.APPLICATION_JSON_VALUE)
    public ObjectNode run(@PathVariable String id, @RequestBody Investigation request) {
        return harness.run(id, version(request.revision()), request.answer(), request.configFacts(), request.pauseAfter(), step -> {}, IntentMode.parse(request.intentMode()), request.decisionPolicy());
    }

    @PostMapping(value = "/apply", consumes = MediaType.APPLICATION_JSON_VALUE)
    public ObjectNode apply(@PathVariable String id, @RequestBody Approval request) {
        return approvals.apply(id, version(request.revision()), IntentMode.parse(request.intentMode()), request.decisionPolicy());
    }

    @PostMapping(value = "/stream", consumes = MediaType.APPLICATION_JSON_VALUE, produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public ResponseEntity<StreamingResponseBody> stream(@PathVariable String id, @RequestBody Investigation request) {
        long revision = version(request.revision());
        IntentMode mode = IntentMode.parse(request.intentMode());
        StreamingResponseBody body = output -> {
            try {
                var result = harness.run(id, revision, request.answer(), request.configFacts(), request.pauseAfter(),
                    step -> send(output, json.createObjectNode().put("type","step").set("step", step)), mode, request.decisionPolicy());
                send(output, json.createObjectNode().put("type","result").set("result", result));
            } catch (ResponseStatusException ex) {
                send(output, json.createObjectNode().put("type","error").put("status",ex.getStatusCode().value())
                    .put("message",ex.getReason()));
            } catch (UncheckedIOException ex) {
                throw ex.getCause();
            } catch (RuntimeException ex) {
                send(output, json.createObjectNode().put("type","error").put("status",500)
                    .put("message","调查未能完成，请刷新并重试"));
            }
        };
        return ResponseEntity.ok().contentType(MediaType.TEXT_EVENT_STREAM).cacheControl(CacheControl.noStore()).header("X-Accel-Buffering","no").body(body);
    }

    private void send(OutputStream output, ObjectNode event) {
        try {
            output.write(("data: " + json.writeValueAsString(event) + "\n\n").getBytes(StandardCharsets.UTF_8));
            output.flush();
        } catch (IOException ex) { throw new UncheckedIOException(ex); }
    }
}
