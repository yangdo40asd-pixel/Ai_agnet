"""재요약의 대상 근거를 보존한다. 답변 텍스트를 새 금융 사실로 취급하지 않는다."""
import re


_RESTATEMENT_VOCAB_LIST = (
    "너무|길어|긴데|방금|직전|앞의|앞서|앞선|위의|그|이|내용|답변|분석|이슈|뉴스|가지|세|두|한|네|다섯|"
    "를|을|은|는|의|문장|줄|로|으로|만|핵심|말|설명|전망|판단|결론|부분|짧게|간단히|간단하게|간결하게|더|좀|다시|"
    r"정리|요약|줄여서|줄여|해줘|해|줘|주세요|해주실래요|거|것|이야기|다룬|논의|\d+"
).split("|")
_RESTATEMENT_VOCAB_LIST.sort(key=len, reverse=True)
_RESTATEMENT_VOCAB_PATTERN = "|".join(_RESTATEMENT_VOCAB_LIST)


def is_restatement(question):
    if is_conversation_summary_request(question):
        return False
    text = re.sub(r"[.!?。！？,]", " ", question).strip()
    if not text or len(text) > 100 or re.search(r"20\d{2}|PER|PBR|ROE|EPS|BPS|주가|매출|영업이익|분기|연간", text, re.I):
        return False
    # 의미 없는 글자까지 허용하는 .* 대신 재요약에 쓰이는 어휘만 허용한다.
    return bool(re.search(r"요약|정리|줄여|(?:한|두|세|네|다섯|\d+)\s*(?:문장|줄)", text) and not re.sub(_RESTATEMENT_VOCAB_PATTERN + r"|\s+", "", text))


def is_conversation_summary_request(question: str) -> bool:
    """전체 대화 정리 요청(지금까지 정리 등)을 직전 답변 재요약과 구분하여 식별한다."""
    text = re.sub(r"[.!?。！？,]", " ", question).strip()
    if not text or len(text) > 120 or re.search(r"20\d{2}|PER|PBR|ROE|EPS|BPS|주가|매출|영업이익|분기|연간|실적", text, re.I):
        return False
    if re.search(r"(?:정리|요약|줄이|간추리)(?:하지\s*마|하지\s*말|지\s*마|지\s*말)|(?:정리|요약)\s*말고", text):
        return False
    return bool(re.search(
        r"^(?:(?:지금까지|전체|모든|앞서\s*(?:나눈|살펴본|확인한|다룬)?|이때까지|여태까지)\s*(?:대화|내용|이야기|결과|논의|논의한|다룬|나눈|나온|살펴본|확인한|\s)*|"
        r"대화(?:\s*내용)?\s*)\s*(?:정리|요약|간추려|줄여|종합)(?:해줘|해|줘|주세요|해주실래요)?$",
        text,
    ) or re.search(
        r"(?:지금까지|전체|모든|이때까지|여태까지)\s*(?:대화|내용|이야기|결과|논의|\s)*\s*(?:정리|요약|간추려|줄여|종합)",
        text,
    ))


def conversation_summary_evidence(question, messages, evidence):
    """지금까지 대화에서 다룬 증거들을 모아 요약 대상 근거로 삼는다. 새 사실을 지어내지 않는다."""
    if not is_conversation_summary_request(question):
        return None
    selected = {}
    current_code = next((v.get("stock_code") for v in evidence.values() if isinstance(v, dict) and v.get("stock_code")), None) if evidence else None
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for ref in msg.get("evidence", ()):
            if not isinstance(ref, dict):
                continue
            orig_id = ref.get("id") or "EVID"
            stock_code = ref.get("stock_code")
            if current_code and stock_code == current_code and orig_id in evidence:
                if not same_evidence(ref, evidence[orig_id]):
                    continue
                item = dict(evidence[orig_id])
            else:
                item = dict(ref)
            key = f"{orig_id}_{stock_code}" if stock_code and (orig_id in selected and selected[orig_id].get("stock_code") != stock_code or (current_code and stock_code != current_code)) else orig_id
            item["id"] = key
            if not item.get("unit"):
                if orig_id == "PRICE" or orig_id.startswith("PRICE"):
                    item["unit"] = "원"
                elif orig_id == "PER" or orig_id.startswith("PER") or orig_id == "PBR" or orig_id.startswith("PBR"):
                    item["unit"] = "배"
                elif orig_id in ("ROE", "EPS", "BPS"):
                    item["unit"] = "%" if orig_id == "ROE" else "원"
            if not item.get("value_text") and item.get("value") is not None:
                val = item["value"]
                unit = item.get("unit", "")
                try:
                    num = float(str(val).replace(",", ""))
                    if unit == "배" or num % 1 != 0:
                        item["value_text"] = f"{num:,.2f}{unit}"
                    else:
                        item["value_text"] = f"{num:,.0f}{unit}"
                except (ValueError, TypeError):
                    item["value_text"] = f"{val}{unit}"
            selected[key] = item
    if not selected:
        selected = dict(evidence)
    return selected or None


_IDENTITY = ("stock_code", "kind", "item", "years", "quarter", "fs_div", "scope",
             "value", "previous", "current", "text", "url", "excerpt")


def same_evidence(reference, current):
    return current is not None and all(str(reference.get(f)) == str(current.get(f)) for f in _IDENTITY)


def displayed_issue_ids(question, messages, evidence):
    """'첫 번째'는 기사 원본 번호가 아니라 실제 표시한 카드 순서다.

    None은 과거 카드가 없어 기존 명시 기사 번호 규칙을 쓸 수 있다는 뜻이고,
    빈 튜플은 해당 카드가 없거나 현재 원자료와 달라 재사용할 수 없다는 뜻이다.
    """
    ordinal = next((i for pattern, i in (
        (r'첫\s*번째|첫째|1\s*(?:번째|번)', 0),
        (r'두\s*번째|둘째|2\s*(?:번째|번)', 1),
        (r'세\s*번째|셋째|3\s*(?:번째|번)', 2),
    ) if re.search(pattern, question)), None)
    if ordinal is None:
        return None
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        cards = []
        for block in message.get("blocks", ()):
            ids = block.get("evidence_ids", ()) if isinstance(block, dict) else block.evidence_ids
            news = tuple(k for k in ids if k.startswith("NEWS_") and k != "NEWS_STATUS")
            if news:
                cards.append(news)
        if not cards:
            continue
        if ordinal >= len(cards):
            return ()
        refs = {r.get("id"): r for r in message.get("evidence", ())}
        selected = cards[ordinal]
        if any(key not in refs or not same_evidence(refs[key], evidence.get(key)) for key in selected):
            return ()
        return selected
    return None


def restatement_evidence(question, messages, evidence):
    if not is_restatement(question):
        return None
    last = next((m for m in reversed(messages) if m.get("role") == "assistant"), None)
    if not last or not last.get("evidence"):
        return None
    selected = {}
    for ref in last["evidence"]:
        key = ref.get("id")
        current = evidence.get(key)
        if not same_evidence(ref, current):
            return None  # 현재 근거와 다른 과거 값을 새 현재 사실로 승격하지 않는다.
        selected[key] = current
    if re.search(r"뉴스|이슈", question) and not any(k.startswith("NEWS_") for k in selected):
        return None
    return selected or None


def restatement_origin(messages):
    """연속 재요약이어도 원래의 질문 의도를 보존한다. 내용의 사실성은 현 근거로 심사한다."""
    return next((str(m.get("text", "")) for m in reversed(messages)
                 if m.get("role")=="user" and not is_restatement(str(m.get("text", "")))), "")
