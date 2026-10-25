"""기존 흐름 검사의 모의 검증 응답에 문장별 계약을 붙인다. 의미 검증을 흉내 내지는 않는다."""
from copy import deepcopy


def with_review_units(responses):
    responses = iter(responses)

    def invoke(settings, instruction, request, *args, **kwargs):
        result = next(responses)
        if isinstance(result, Exception):
            raise result
        result = deepcopy(result)
        if (request.get("task") == "chat_grounding_review" and isinstance(result, dict)
                and "checks" in result and "unit_reviews" not in result):
            result["unit_reviews"] = [
                {"id": unit["id"], "reason": "모의 판정: 실제 의미 검증 결과가 아닙니다.",
                 "supported": result.get("supported") is True}
                for unit in request["review_units"]
            ]
        return result

    return invoke
