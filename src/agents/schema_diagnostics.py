"""검수용 형식 오류 진단. 모델 생성문/오류 본문 대신 허용된 구조 정보만 남긴다."""
import json


def schema_failure_summary(detail, response_format, task):
    schema = response_format.get("json_schema", {}).get("schema", {})
    event = {"event": "schema_failure", "code": "json_validate_failed",
             "task": task if task in {"chat_answer", "chat_grounding_review", "chat_route"} else "other",
             "violations": []}
    raw = detail.get("failed_generation")
    if not isinstance(raw, str) or len(raw) > 20000:
        event["diagnostic"] = "no_bounded_generation"
        return event
    try:
        from jsonschema import Draft202012Validator
        parsed = json.loads(raw)
        # 스키마의 알려진 키만 경로에 표시한다. 미지의 사용자 키는 저장하지 않는다.
        allowed = set(schema.get("properties", {})) | {"title", "text", "evidence_ids"}
        for error in Draft202012Validator(schema).iter_errors(parsed):
            path = [part if (type(part) is int or part in allowed) else "unknown_field"
                    for part in error.absolute_path]
            event["violations"].append({"path": path[:8], "rule": error.validator})
            if len(event["violations"]) >= 8:
                break
        event["diagnostic"] = "local_schema_checked"
    except ImportError:
        event["diagnostic"] = "validator_unavailable"
    except (ValueError, TypeError, RecursionError):
        event["diagnostic"] = "generation_not_json"
    return event
