package studio.notes;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.charset.StandardCharsets;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Consumer;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
public class HarnessService {
    static final String POLICY = "context-decisions-v14";
    private static final String CHECKPOINT_SCHEMA = "kmeans-review-v18";
    private final HarnessReports reports;
    private final HarnessRunner runner;
    private final ReviewStore notes;
    private final ObjectMapper json;
    private record RunKey(String id, long revision, IntentMode mode) {}
    private final Set<RunKey> active = ConcurrentHashMap.newKeySet();

    public HarnessService(HarnessReports reports, HarnessRunner runner, ReviewStore notes, ObjectMapper json) {
        this.reports = reports;
        this.runner = runner;
        this.notes = notes;
        this.json = json;
    }

    public ObjectNode current(String id) {
        return current(id, IntentMode.RULE);
    }

    public ObjectNode current(String id, IntentMode mode) {
        var snapshot = reports.snapshot(id, null, mode);
        if (obsoleteCheckpoint(snapshot) || (snapshot.checkpoint() == null && obsolete(snapshot.report()))) {
            return outdated(snapshot.note().path("revision").asLong(),mode);
        }
        if (snapshot.checkpoint() != null) {
            return paused(snapshot.note().path("revision").asLong(), snapshot.checkpoint().payload(), mode);
        }
        return snapshot.report() == null ? null : snapshot.report().result().put("intentMode",mode.wire);
    }

    private boolean obsolete(HarnessReports.Report report) {
        return report != null && !POLICY.equals(report.result().path("decisionPolicy").asText());
    }

    private boolean obsoleteCheckpoint(HarnessReports.Snapshot snapshot) {
        var checkpoint = snapshot.checkpoint();
        if (checkpoint == null) return false;
        if (checkpoint.payload() == null) {
            return (checkpoint.answer() != null || checkpoint.facts() != null) && obsolete(snapshot.report());
        }
        return !CHECKPOINT_SCHEMA.equals(checkpoint.payload().path("version").asText());
    }

    private ObjectNode outdated(long revision, IntentMode mode) {
        return json.createObjectNode().put("revision",revision).put("intentMode",mode.wire)
            .put("status","blocked").putNull("proposed")
            .put("reason","此调查使用旧版判读规则，请重新调查当前修订，再核对问题和建议。");
    }

    private void requireReviewedPolicy(HarnessReports.Report report, String requested) {
        if (obsolete(report) || (requested != null && !POLICY.equals(requested))
                || (report != null && report.result().path("replacesOldPolicy").asBoolean() && requested == null)) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,"判读规则已更新，请重新读取并核对本轮调查");
        }
    }

    private ObjectNode paused(long revision, ObjectNode checkpoint, IntentMode mode) {
        var view = json.createObjectNode().put("intentMode",mode.wire).put("status", "paused").put("revision", revision).putNull("proposed");
        var trace = checkpoint == null ? json.createArrayNode() : checkpoint.path("trace");
        view.set("trace", trace);
        view.put("checkpointSteps", trace.size());
        view.put("planner", checkpoint == null ? "" : checkpoint.path("planner").asText());
        view.put("reason", "已保存调查进度，继续时从下一步开始。");
        return view;
    }

    private static class RequestedPause extends RuntimeException {
        final ObjectNode view;
        RequestedPause(ObjectNode view) { super(null, null, false, false); this.view = view; }
    }

    public ObjectNode run(String id, long revision, String answer) {
        return run(id, revision, answer, null, step -> {});
    }

    public ObjectNode run(String id, long revision, String answer, Integer pauseAfter, Consumer<ObjectNode> onStep) {
        return run(id,revision,answer,null,pauseAfter,onStep);
    }

    public ObjectNode run(String id,long revision,String answer,ObjectNode facts,Integer pauseAfter,Consumer<ObjectNode> onStep) {
        return run(id,revision,answer,facts,pauseAfter,onStep,IntentMode.RULE);
    }

    public ObjectNode run(String id,long revision,String answer,ObjectNode facts,Integer pauseAfter,Consumer<ObjectNode> onStep, IntentMode mode) {
        return run(id,revision,answer,facts,pauseAfter,onStep,mode,null);
    }

    public ObjectNode run(String id,long revision,String answer,ObjectNode facts,Integer pauseAfter,Consumer<ObjectNode> onStep, IntentMode mode, String reviewedPolicy) {
        MappingFacts.validate(facts);
        if (answer != null && !Set.of("old", "default").contains(answer))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "无效的意图选项");
        if (pauseAfter != null && (pauseAfter < 1 || pauseAfter > 4))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "暂停位置应在第 1 至 4 步之间");
        var key = new RunKey(id, revision, mode);
        if (!active.add(key))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "此笔记的调查正在进行，请稍后读取");
        try { return investigate(id, revision, answer, facts, pauseAfter, onStep, mode, reviewedPolicy); }
        finally { active.remove(key); }
    }

    private ObjectNode investigate(String id, long revision, String answer, ObjectNode facts, Integer pauseAfter, Consumer<ObjectNode> onStep, IntentMode mode, String reviewedPolicy) {
        var snapshot = reports.snapshot(id, revision, mode);
        var last = snapshot.report();
        var saved = snapshot.checkpoint();
        if (facts != null || answer != null) requireReviewedPolicy(last,reviewedPolicy);
        if (obsoleteCheckpoint(snapshot)) {
            if (answer != null || facts != null)
                throw new ResponseStatusException(HttpStatus.CONFLICT,"旧检查点需要从当前修订重新调查");
            // Fence the obsolete worker, archive its round, then start without its answer or tool state.
            var retired = reports.claim(id,revision,last == null ? 0 : last.round(),saved,saved.answer(),saved.facts(),mode);
            reports.finish(retired,saved.steps(),outdated(revision,mode));
            snapshot = reports.snapshot(id,revision,mode);
            last = snapshot.report();
            saved = snapshot.checkpoint();
        }
        boolean replacesOldPolicy = obsolete(last) || last != null && last.result().path("replacesOldPolicy").asBoolean();
        if (saved != null) {
            if (answer != null && !answer.equals(saved.answer()))
                throw new ResponseStatusException(HttpStatus.CONFLICT, "恢复时不可替换已保存的回答");
            if (facts != null && !facts.equals(saved.facts()))
                throw new ResponseStatusException(HttpStatus.CONFLICT, "恢复时不可替换已保存的配置依据");
            facts = saved.facts();
            answer = saved.answer();
            if (pauseAfter != null && saved.steps() >= pauseAfter) return paused(revision, saved.payload(), mode);
        } else {
            if (answer == null && facts == null && last != null && !obsolete(last) && !last.result().path("status").asText().equals("blocked")) {
                if (pauseAfter != null)
                    throw new ResponseStatusException(HttpStatus.CONFLICT, "本轮调查已有结论，请在新版本或回答追问时演示暂停");
                return last.result().put("intentMode",mode.wire);
            }
            boolean question = last != null && last.result().path("status").asText().equals("question");
            boolean mappingQuestion = question && last.result().path("questionType").asText().equals("external_config");
            if (facts != null) {
                if (!mappingQuestion || answer != null || !facts.path("mapping").equals(last.result().path("mapping")))
                    throw new ResponseStatusException(HttpStatus.CONFLICT, "配置回答与此版本等待核对的映射不一致");
            } else if (answer != null && (!question || mappingQuestion || "reference_evidence".equals(last.result().path("questionType").asText()))) {
                throw new ResponseStatusException(HttpStatus.CONFLICT, "此版本没有等待回答的升级意图问题");
            } else if (last != null && !obsolete(last) && last.result().get("configFacts") instanceof ObjectNode known) {
                facts = known;
            }
        }
        var input = json.createObjectNode().put("intentMode",mode.wire).put("revision", revision);
        input.set("current", snapshot.note().get("current"));
        input.set("filename", snapshot.note().get("filename"));
        if (snapshot.note().has("librarySources"))
            input.set("librarySources", snapshot.note().get("librarySources"));
        if (input.path("current").asText().getBytes(StandardCharsets.UTF_8).length > 100_000)
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "当前笔记超过单次调查 100 KB 上限");
        if (answer != null) input.put("answer", answer);
        if (facts != null) input.set("configFacts", facts);
        if (saved != null && saved.payload() != null) input.set("checkpoint", saved.payload());
        var owner = reports.claim(id, revision, last == null ? 0 : last.round(), saved, answer, facts, mode);
        int resumed = saved == null ? 0 : saved.steps();
        var progress = new Progress(owner, resumed, pauseAfter, onStep);
        ObjectNode result;
        try { result = runner.investigate(input, progress::save); }
        catch (RequestedPause requested) { return requested.view; }
        if (!POLICY.equals(result.path("decisionPolicy").asText()) || !mode.wire.equals(result.path("intentMode").asText("rule")) || !result.path("revision").isIntegralNumber() || result.path("revision").asLong() != revision ||
            !Set.of("complete", "question", "blocked").contains(result.path("status").asText()) ||
            !result.has("proposed") || !(result.get("proposed").isNull() || result.get("proposed").isTextual())) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "调查器返回了无效的数据");
        }
        result.put("intentMode",mode.wire).put("resumedSteps", resumed);
        if (replacesOldPolicy) result.put("replacesOldPolicy",true);
        if (facts != null) result.set("configFacts", facts);
        if (answer != null) {
            var clarification = json.createObjectNode().put("answer", answer);
            for (String field : Set.of("decisionGap","decisionTarget","citations","questionChoices","choiceEvidence","choiceCitations")) {
                if (last.result().has(field)) clarification.set(field,last.result().get(field));
            }
            for (var step : last.result().path("trace")) {
                if ("read_intent".equals(step.path("tool").asText()) && step.path("applicability").isObject()) {
                    clarification.set("applicability",step.get("applicability"));
                }
            }
            String choice = last.result().path("questionChoices").path(answer).asText(null);
            if (choice != null) clarification.put("selectedChoice",choice);
            clarification.set("reason", last.result().path("reason"));
            clarification.set("question", last.result().path("question"));
            clarification.put("resumedSteps", last.result().path("resumedSteps").asInt());
            result.set("clarification", clarification);
        }
        reports.finish(owner, progress.count, result);
        return result;
    }

    private class Progress {
        private final HarnessReports.Owner owner;
        private final Integer pauseAfter;
        private final Consumer<ObjectNode> onStep;
        private int count;

        Progress(HarnessReports.Owner owner, int count, Integer pauseAfter, Consumer<ObjectNode> onStep) {
            this.owner = owner; this.count = count; this.pauseAfter = pauseAfter; this.onStep = onStep;
        }

        void save(ObjectNode event) {
            var step = event.path("step");
            var cp = event.path("checkpoint");
            var trace = cp.path("trace");
            if (!(step instanceof ObjectNode observation) || !(cp instanceof ObjectNode payload) ||
                !trace.isArray() || trace.size() != count + 1 || !step.equals(trace.get(count)))
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "检查点与已完成工具步数不一致");
            reports.saveStep(owner, count, payload);
            count++;
            onStep.accept(observation);
            if (pauseAfter != null && count == pauseAfter) throw new RequestedPause(paused(owner.revision(), payload, owner.mode()));
        }
    }

    public ObjectNode apply(String id, long revision) { return apply(id,revision,IntentMode.RULE); }

    public ObjectNode apply(String id, long revision, IntentMode mode) { return apply(id,revision,mode,null); }

    public ObjectNode apply(String id, long revision, IntentMode mode, String reviewedPolicy) {
        var snapshot = reports.snapshot(id, revision, mode);
        var last = snapshot.report();
        requireReviewedPolicy(last,reviewedPolicy);
        if (snapshot.checkpoint() != null || last == null || !last.result().path("status").asText().equals("complete"))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "当前版本没有可应用的调查建议");
        return notes.applyInvestigation(id, revision, last.result().get("proposed").textValue());
    }
}
