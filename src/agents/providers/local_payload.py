"""로컬 전송용 중복 표시 정보 축소. 원본/검사 근거는 수정하지 않는다."""
from copy import deepcopy
import json

# 원래 심사 지시문이 여섯 기준을 상세 정의한다. 전송 자료에는 같은 뜻의
# 짧은 이름만 싣고 JSON 필드/문장별 심사·코드 거절 기준은 그대로 둔다.
CHECK_DESCRIPTIONS={
    'evidence_match':'자기 근거의 사실·수치·계획 단계 일치',
    'time_basis':'발행/조회일과 사건일·실적 기간 구별',
    'question_focus':'질문 대상·범위 유지, 무관한 항목 제외',
    'explanation':'요약/분석 요청에 맞는 실질 설명',
    'scope_disclosed':'본문과 하단 출처의 범위·기간·기준 일치',
    'context_consistent':'후속 대상 유지, 과거 AI를 사실 근거로 쓰지 않음',
}


def compact_messages(messages):
    result=[]
    for role, content in messages:
        if role not in {'human','user'}:
            result.append((role,content))
            continue
        payload=json.loads(content)
        evidence=payload.get('evidence') if isinstance(payload,dict) else None
        if isinstance(evidence,dict):
            payload=deepcopy(payload)
            for item in payload['evidence'].values():
                if not isinstance(item,dict):
                    continue
                # 결과ID는 검증 원본에 유지한다. 회사 코드는 다중 기업 구분에
                # 필요하므로 남긴다. 조회 시각은
                # 사건 시각이 아니며 화면 하단에 남는다. 자료 기준 as_of/period는 보존한다.
                for field in ('retrieved_at','result_id'):
                    item.pop(field,None)
                if 'value_text' in item and item['value_text']:
                    item.pop('text',None)  # 같은 값을 회사명과 함께 반복한 표시 문자열
                for field in tuple(item):
                    if item[field] is None or item[field]=='':
                        del item[field]
        if (isinstance(payload,dict) and payload.get('task')=='chat_grounding_review'
                and payload.get('review_profile')=='scoped-v1'
                and set(payload.get('quality_checks',{}))==set(CHECK_DESCRIPTIONS)):
            payload={**payload,'quality_checks':CHECK_DESCRIPTIONS}
        result.append((role,json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':'))))
    return result
