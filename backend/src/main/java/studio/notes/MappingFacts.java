package studio.notes;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.charset.StandardCharsets;
import java.util.Set;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

final class MappingFacts {
    private MappingFacts() {}
    static void validate(ObjectNode facts) {
        if (facts == null) return;
        JsonNode mapping = facts.path("mapping");
        JsonNode init = facts.path("init");
        JsonNode count = facts.path("n_init");
        if (facts.size() != 3 || !mapping.isTextual() || mapping.textValue().isBlank() ||
            mapping.textValue().getBytes(StandardCharsets.UTF_8).length > 2000 ||
            !init.isTextual() || !Set.of("absent","k-means++","random","callable","array-like","unknown").contains(init.textValue()) ||
            !(count.isTextual() && Set.of("absent","auto","unknown").contains(count.textValue()) ||
              count.isIntegralNumber() && count.canConvertToInt() && count.intValue() > 0)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "需要填写该映射的 init 和有效 n_init 值，无法核对时请选择尚不清楚");
        }
    }
}
