package studio.notes;

import static org.junit.jupiter.api.Assertions.*;
import java.util.function.Function;
import java.util.function.Consumer;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.web.server.ResponseStatusException;

class HarnessServiceTest {
    final ObjectMapper json = new ObjectMapper();
    int invocations;
    Function<ObjectNode,ObjectNode> investigation;
    final HarnessRunner runner = new HarnessRunner(json, "") {
        @Override public ObjectNode investigate(ObjectNode input, Consumer<ObjectNode> onStep) {
            invocations++;
            return investigation.apply(input);
        }
    };
    JdbcTemplate db;
    ReviewStore notes;
    HarnessService service;

    @BeforeEach void start() throws Exception {
        db = new JdbcTemplate(new DriverManagerDataSource("jdbc:h2:mem:" + UUID.randomUUID() + ";DB_CLOSE_DELAY=-1"));
        notes = new ReviewStore(db, json);
        notes.initialize(json.readTree("[{\"id\":\"a\",\"filename\":\"test.md\",\"original\":\"base\",\"proposed\":null}]"));
        var repository = new HarnessReports(db, json, notes);
        repository.initialize();
        service = new HarnessService(repository, runner, notes, json);
    }

    private ObjectNode result(String status, String proposed) {
        return json.createObjectNode().put("decisionPolicy",HarnessService.POLICY).put("status", status).put("proposed", proposed).put("revision", 0);
    }

    @Test void referenceEvidenceCannotBeReplacedWithAnIntentChoice() {
        investigation = input -> result("question", null).put("questionType", "reference_evidence")
                .put("question", "参照实现实际使用几次初始化？");
        service.run("a", 0, null);
        for (String answer : new String[]{"old", "default"}) {
            assertEquals(409, assertThrows(ResponseStatusException.class,
                    () -> service.run("a", 0, answer)).getStatusCode().value());
        }
        assertEquals(1, invocations);
    }

    @Test void pausesForAnswerAndOnlyAppliesStoredCompleteProposal() {
        investigation = input -> input.has("answer") ? result("complete", "approved")
            : result("question", null).put("reason","unknown").put("question","旧版还是新版？");
        assertNull(service.current("a"));
        assertEquals(409, assertThrows(ResponseStatusException.class,
            () -> service.run("a", 0, "old")).getStatusCode().value());
        assertEquals("question", service.run("a", 0, null).get("status").asText());
        assertEquals(409, assertThrows(ResponseStatusException.class,
            () -> service.apply("a", 0)).getStatusCode().value());
        assertEquals(400, assertThrows(ResponseStatusException.class,
            () -> service.run("a", 0, "invented")).getStatusCode().value());
        assertEquals("complete", service.run("a", 0, "old").get("status").asText());
        assertEquals("approved", service.run("a", 0, null).get("proposed").asText());
        assertEquals(2, invocations);
        assertEquals("旧版还是新版？", service.current("a").path("clarification").path("question").asText());
        assertEquals("base", notes.list().get(0).path("current").asText());
        assertEquals("approved", service.apply("a", 0).path("current").asText());
        assertNull(service.current("a"));
    }

    @Test void discardsResultsWhenNoteChangesDuringToolExecution() {
        investigation = input -> {
            notes.edit("a", "manual", 0);
            return result("complete", "obsolete");
        };
        assertEquals(409, assertThrows(ResponseStatusException.class,
            () -> service.run("a", 0, null)).getStatusCode().value());
        assertNull(service.current("a"));
        assertEquals("manual", notes.list().get(0).get("current").asText());
    }

    @Test void staleAnswerIsRejectedAndPartialReportsCannotBeApplied() {
        investigation = input -> result("blocked", null);
        service.run("a", 0, null);
        assertEquals(409, assertThrows(ResponseStatusException.class,
            () -> service.apply("a", 0)).getStatusCode().value());
        notes.edit("a", "unrelated", 0);
        assertEquals(409, assertThrows(ResponseStatusException.class,
            () -> service.run("a", 0, "old")).getStatusCode().value());
        assertEquals(1, invocations);
    }
    @Test void aBlockedRunCanBeRetriedAndApprovalsCanBeUndone() {
        investigation = input -> invocations == 1 ? result("blocked", null) : result("complete", "patched");
        service.run("a", 0, null);
        assertEquals("complete", service.run("a", 0, null).path("status").asText());
        assertEquals("accept", service.apply("a", 0).path("decision").asText());
        investigation = input -> result("complete", null).put("revision", 1);
        service.run("a", 1, null);
        assertEquals("patched", service.apply("a", 1).path("current").asText());
        assertEquals("accept", notes.decide("a", "pending", 2).path("decision").asText());
        assertEquals("base", notes.decide("a", "pending", 3).path("current").asText());
    }

    @Test void mappingReplyMustMatchCurrentQuestionAndSurvivesLaterIntentQuestion() {
        var facts = json.createObjectNode().put("mapping","settings").put("init","absent").put("n_init","absent");
        investigation = input -> {
            if (!input.has("configFacts")) return result("question",null)
                .put("questionType","external_config").put("mapping","settings").put("question","核对 settings");
            assertEquals(facts,input.path("configFacts"));
            return input.has("answer") ? result("complete","patched")
                : result("question",null).put("questionType","intent").put("question","选择升级意图");
        };
        assertEquals(409,assertThrows(ResponseStatusException.class,
            () -> service.run("a",0,null,facts,null,step->{})).getStatusCode().value());
        service.run("a",0,null);
        assertEquals(409,assertThrows(ResponseStatusException.class,
            () -> service.run("a",0,"old")).getStatusCode().value());
        assertEquals(409,assertThrows(ResponseStatusException.class,
            () -> service.run("a",0,null,facts.deepCopy().put("mapping","other"),null,step->{})).getStatusCode().value());
        assertEquals(400,assertThrows(ResponseStatusException.class,
            () -> service.run("a",0,null,facts.deepCopy().put("n_init",-2),null,step->{})).getStatusCode().value());
        assertEquals("intent", service.run("a",0,null,facts,null,step->{}).get("questionType").textValue());
        var complete=service.run("a",0,"old");
        assertEquals(facts,complete.get("configFacts"));
        assertEquals("complete",complete.get("status").textValue());
        assertEquals("patched",service.apply("a",0).get("current").textValue());
        assertEquals(409,assertThrows(ResponseStatusException.class,
            () -> service.run("a",0,null,facts,null,step->{})).getStatusCode().value());
    }

    @Test void obsoleteProposalAndOldAnswerAreRejectedUntilNewDecisionIsReviewed() {
        var obsolete = result("complete","unsafe old draft");
        obsolete.put("decisionPolicy","context-decisions-v13");
        db.update("INSERT INTO harness_report VALUES ('a',0,1,?)",obsolete.toString());
        assertEquals("blocked",service.current("a").path("status").asText());
        assertTrue(service.current("a").path("proposed").isNull());
        assertThrows(ResponseStatusException.class,()->service.apply("a",0));
        investigation = data -> {
            if (data.has("answer")) return result("complete","current draft");
            var question=result("question",null).put("decisionGap","requirement_owner").put("question","这是本项目的要求吗？");
            question.putObject("questionChoices").put("old","本项目也采用这项要求").put("default","只用于参考");
            question.putArray("citations").addObject().put("line",3).put("quote","参考团队的要求");
            question.put("decisionTarget","authority");
            var gate = question.putArray("trace").addObject().put("tool","read_intent").putObject("applicability");
            gate.put("route","candidate_claims").put("outcome","ask").put("reason","终审人尚未确定").put("modelCalled",false);
            gate.set("citations",question.path("citations"));
            var cites = question.putObject("choiceCitations");
            var oldReferences = cites.putArray("old");
            oldReferences.addObject().put("sentence",1).put("line",3).put("quote","终审人为陈老师");
            oldReferences.addObject().put("sentence",2).put("line",4).put("quote","陈老师要求保留旧设置");
            cites.putArray("default").addObject().put("sentence",3).put("line",5).put("quote","参考团队采用库默认");
            var evidence=question.putObject("choiceEvidence");
            evidence.putObject("old").put("sentence",1).put("line",3).put("quote","作者保留旧设置");
            evidence.putObject("default").put("sentence",2).put("line",5).put("quote","参考团队采用库默认");

            return question;
        };
        assertThrows(ResponseStatusException.class,()->service.run("a",0,"old"));
        var question=service.run("a",0,null);
        assertEquals("question",question.path("status").asText());
        assertThrows(ResponseStatusException.class,()->service.run("a",0,"old"));
        var answered=service.run("a",0,"old",null,null,step->{},IntentMode.RULE,HarnessService.POLICY);
        assertEquals("本项目也采用这项要求",answered.at("/clarification/selectedChoice").asText());
        assertEquals(question.path("citations"),answered.at("/clarification/citations"));
        assertEquals(question.path("choiceEvidence"),service.current("a").at("/clarification/choiceEvidence"));
        assertEquals(question.path("decisionTarget"),service.current("a").at("/clarification/decisionTarget"));
        assertEquals(question.path("choiceCitations"),service.current("a").at("/clarification/choiceCitations"));
        assertEquals(question.at("/trace/0/applicability"),service.current("a").at("/clarification/applicability"));
        assertThrows(ResponseStatusException.class,()->service.apply("a",0));
        assertEquals("current draft",service.apply("a",0,IntentMode.RULE,HarnessService.POLICY).path("current").asText());
    }

    @Test void twoModesKeepIndependentRoundsAnswersAndProposals() {
        investigation = input -> {
            String mode = input.path("intentMode").asText();
            if (mode.equals("model")) return result("complete","model draft").put("intentMode",mode);
            return input.has("answer") ? result("complete","rule draft").put("intentMode",mode)
                : result("question",null).put("intentMode",mode);
        };
        service.run("a",0,null);
        assertNull(service.current("a",IntentMode.MODEL));
        assertEquals(409,assertThrows(ResponseStatusException.class,
            ()->service.run("a",0,"old",null,null,step->{},IntentMode.MODEL)).getStatusCode().value());
        service.run("a",0,null,null,null,step->{},IntentMode.MODEL);
        assertEquals("question",service.current("a",IntentMode.RULE).path("status").asText());
        assertEquals("model draft",service.current("a",IntentMode.MODEL).path("proposed").asText());
        service.run("a",0,"old");
        assertEquals("rule draft",service.current("a").path("proposed").asText());
        assertEquals("model draft",service.apply("a",0,IntentMode.MODEL).path("current").asText());
        assertEquals(409,assertThrows(ResponseStatusException.class,()->service.apply("a",0)).getStatusCode().value());
    }
}
