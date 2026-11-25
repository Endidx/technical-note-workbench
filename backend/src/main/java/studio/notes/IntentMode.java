package studio.notes;

import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

enum IntentMode {
    RULE("rule"), MODEL("model");

    final String wire;
    IntentMode(String wire) { this.wire = wire; }

    static IntentMode parse(String value) {
        if (value == null || value.equals("rule")) return RULE;
        if (value.equals("model")) return MODEL;
        throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "未知的意图判读方式");
    }

    // The rule namespace retains the tables used by existing installations.
    String sql(String statement) {
        return this == RULE ? statement : statement.replace("harness_", "model_harness_");
    }
}
