"""금융 해석의 공통 경계. 수치 검사/의미 심사를 대신해 자동 승인하지 않는다."""
from dataclasses import asdict, dataclass
from decimal import Decimal
import re


POLICY = """금융 해석은 네 단계로 구분합니다. 숫자/출처 검증 통과가 선행하며 단계만으로 자동 승인하지 않습니다.
T1: 자료가 직접 확인하는 사실/범위입니다. 보유 비율 불변은 거래 없음·수급 영향 제한을 뜻하지 않습니다.
T2: 같은 기업/기간/기준의 검증된 계산이나 관계 설명입니다. 매출/이익/마진 개선, 원가율·판관비율 변화와 이익률 관계를 설명할 수 있습니다. 계산이 맞아도 원자료에 없는 사업 원인을 보태지 않습니다.
T3: 조건부 해석은 확인된 사실 연결·구체적 경제/수급 메커니즘·비약 없음·관측과 가설 구분을 모두 충족해야 합니다. 생산능력 확대 목적의 투자 계획은 설비 가동과 수요/판매 조건을 명시해 가능한 출하 경로를 설명할 수 있습니다. 조건 자체를 이미 성립한 사실로 쓰지 않습니다.
같은 카드·같은 근거의 제목/조건 문장은 함께 읽되 다른 사건의 조건이나 뒤의 경고로 앞의 허구 사실을 면책하지 않습니다.
T4: 근거 없는 원인/주가 확정 전망/관측하지 않은 투자심리 단정은 거절합니다. '가능성', '다만 확인 필요'라는 말로 앞의 무근거 주장을 승인하지 않습니다.
수급 비교는 같은 기간 시장/해당 기업 자료가 각각 있어야 합니다. 거래 이유·앞으로의 가격 방향은 관측 수급에서 자동 도출되지 않습니다.
확인된 원가 구성이나 잠정 실적이 있으면 먼저 그 의미를 답합니다. 잠정을 확정으로 바꾸지 않으며 이미 제공된 비교를 사용자에게 다시 조사하라고 넘기지 않습니다.
기사의 관계/사실 확인과 분석 질문 관련성은 별개입니다. 주주라는 사실만으로 해당 주주의 모든 사업 소식이 대상 종목의 실적 근거가 되지는 않습니다."""

GENERATION_POLICY = """확인된 사실과 검증된 계산의 의미를 먼저 설명합니다. 원가 구성이 있으면 실제 비중 변화로 답하며 같은 자료를 다시 조사하라고 넘기지 않습니다.
조건부 해석은 확인된 사실 연결·구체적 경로·비약 없음·관측과 가설 구분을 모두 지킵니다. 생산능력 확대 계획은 가동/수요 조건으로 출하 경로를 설명할 수 있지만 이미 매출/주가에 반영됐다고 쓰지 않습니다.
지분율 불변은 거래 없음이나 주가 영향 제한을 뜻하지 않습니다. 수급은 같은 기간끼리 비교합니다. 잠정/확정·회사 역할을 유지합니다. 한계 문구로 근거 없는 원인·전망을 정당화하지 않습니다."""


@dataclass(frozen=True)
class InterpretationDecision:
    unit_id: str
    tier: str
    flags: tuple[str,...] = ()
    requirements: tuple[str,...] = ()

    def payload(self):
        return asdict(self)


def _source_text(evidence):
    return ' '.join(str(item.get(key) or '') for item in evidence.values()
                    for key in ('text','excerpt','source_excerpt'))


def _denied(text):
    return bool(re.search(r'아닙|아니|않|없|어렵|단정.{0,10}(?:금지|불가)|판단.{0,8}불가',text))


def _cost_drop(item):
    if not item.get('cost_bridge_reconciled') or item.get('item')!='cost_of_sales_ratio':
        return False
    try:
        old,new=Decimal(str(item.get('previous_cost'))),Decimal(str(item.get('current_cost')))
        return old.is_finite() and new.is_finite() and new<old
    except ArithmeticError:
        return False


def _criterion_modality(clause):
    # 양태 동사나 명사의 언급만으로 실제 회사 예측이라고 단정하지 않는다.
    text=re.sub(r'((?:확인해야|점검해야|비교해야|검토해야|살펴봐야|보아야|봐야)\s*(?:만\s*)?판단할)\s*수\s*있',r'\1',clause)
    # 이미 확인된 과거 결과에 대한 '개선됐다고 판단할 수 있다'도 미래 가능성과 다르다.
    text=re.sub(r'((?:했|졌|됐|였|었|았)다고\s*(?:(?:판단|평가|해석)할|볼))\s*수\s*있',r'\1',text)
    # 자료의 가용 범위/조회 가능 여부 표현('확인 가능한 실적', '확인할 수 있는 자료')은 회사 실적 가능성/전망 가설과 다르다.
    text=re.sub(r'(?:확인|조회|수집|파악|제공|이용)\s*가능(?:한|합|하|합니|성)?', '가용', text)
    text=re.sub(r'(?:확인|조회|수집|파악|제공|이용)할\s*수\s*있(?:는|습|었|다)', '가용', text)
    advisory=re.search(r'확인해야|비교해야|검토해야|살펴봐야|분석.{0,12}필요|판단.{0,12}필요',text)
    if advisory:
        text=re.sub(r'수\s*있는지', '여부', text)
        text=re.sub(r'가능성(?:을|여부)', '여부', text)
    if (re.search(r'판단하기\s*위해|판단하려면|판단할\s*때',text)
            and re.search(r'고려해야|비교해야|확인해야|살펴봐야|봐야',text)):
        # '예상되는 이익과 현재 가격을 비교'라는 판단 변수만 정규화한다.
        # '예상되는 이익은 ...', '예상되는 이익 증가로 주가가 ...'는 그대로 남긴다.
        text=re.sub(r'예상되는\s*(이익|실적|수요)(?=\s*(?:과|와|및|을|를|의|에\s*대한))',r'\1 기대',text)
    return text


def classify_unit(unit):
    text=unit['statement']
    evidence=unit['evidence']
    source=_source_text(evidence)
    mechanism_text=unit.get('conditional_context',text)
    heading=unit['id'].startswith('block_') and unit['id'].endswith('_0')
    def reported_forecast(clause):
        return bool(re.search(r'전망|예상',source) and re.search(r'전망했|예상했|전망이\s*보도|것으로\s*봤',clause)
                    and re.search(r'증권사|회사|보도|기관',clause))
    market_facts=[fact for item in evidence.values() for fact in item.get('structured_facts',())
                  if fact.get('status')=='verified' and fact.get('item') in {'foreign_net_buy','foreign_net_sell','volume'}]
    flags=[]
    benchmark=any("PEER" in key or "AVG" in key or item.get("kind")=="peer_comparison" for key,item in evidence.items())
    proofs=[proof for item in evidence.values() for proof in item.get('relationship_proofs',())]
    if (proofs and all(proof.get('validity')=='document_only' for proof in proofs)
            and re.search(r'현재|최신',text) and re.search(r'주주|보유\s*관계|협력사|공급사',text)
            and not re.search(r'단정|판단할\s*수\s*없|알\s*수\s*없|미확인',text)):
        flags.append('relationship_currentness_unverified')
    # 한 문장 뒤의 경고가 앞의 잘못된 원인을 합법화하지 않게 절 단위로 대조한다.
    clauses=re.split(r'[.!?。！？]\s+|[,，]?\s*(?:다만|하지만|그러나)|지만\s*|(?:이며|이고),\s*',text)
    for clause in clauses:
        # 부정/한계의 목적어인 추정은 허용한다. 무관한 뒤 문장의 부정으로 앞을 면책하지 않는다.
        impact=re.search(r'주가\s*(?:에\s*미치는\s*)?영향.{0,15}제한|수급\s*영향.{0,15}제한',clause)
        if impact and not _denied(clause[impact.start():]):
            flags.append('unsupported_limited_market_impact')
        no_trade=re.search(r'(?:거래|매매)(?:가|는|도)?\s*(?:없었|없습|없다|하지\s*않았)',clause)
        if no_trade and not re.search(r'단정|판단할\s*수\s*없|의미하지\s*않',clause[no_trade.end():]):
            if re.search(r'지분|보유\s*비율',source) and not re.search(r'(?:거래|매매).{0,8}(?:없었|없음|없다)',source):
                flags.append('holding_ratio_is_not_no_trade')
        forecast=re.search(r'주가.{0,30}(?:반드시|확실|보장|확정|상승할\s*것|오를\s*것)|(?:앞으로|향후).{0,15}주가.{0,20}(?:오릅니다|상승합니다)',clause)
        if forecast and not _denied(clause[forecast.start():]) and not reported_forecast(clause):
            flags.append('unverified_price_forecast')
        if re.search(r'지배구조.{0,12}완전히\s*안정',clause) and not _denied(clause):
            flags.append('holding_is_not_control_stability')
        if "PER" in evidence and not benchmark:
            relative=re.search(r'PER(?:은|는|이|가)?[^.!?]{0,25}(?:낮습니다|높습니다|낮은\s*수준(?:임을|입니다)|높은\s*수준(?:임을|입니다))|(?:주가|가격|이익\s*대비)[^.!?]{0,25}(?:낮은|높은)\s*수준(?:임을|입니다|에서)',clause)
            if relative:
                tail=clause[relative.end():relative.end()+30]
                deferred=re.match(r'\s*(?:확인|판단|단정)(?:할\s*수\s*없|하기\s*어렵)',tail)
                if not deferred:
                    flags.append('relative_per_without_benchmark')
        for cause in ('판가 인상','원자재 가격 하락','생산 효율 개선','제품 믹스 개선','고객 주문 확보'):
            compact=re.sub(r'\s+','',cause)
            if (compact in re.sub(r'\s+','',clause) and re.search(r'덕분|때문|힘입|영향으로|원인',clause)
                    and compact not in re.sub(r'\s+','',source) and not _denied(clause)):
                flags.append('unsupported_business_cause')
        if re.search(r'원가\s*절감',clause) and not _denied(clause):
            actual_drop=any(_cost_drop(item) for item in evidence.values())
            if not actual_drop and not re.search(r'원가\s*절감',source):
                flags.append('ratio_drop_is_not_absolute_cost_cut')
        if (re.search(r'가동|생산라인|신규\s*(?:공장|라인)',clause) and re.search(r'완료|이미.{0,10}반영',clause)
                and re.search(r'계획|목표|예정',source) and not re.search(r'가동\s*완료|집행\s*완료|실적\s*반영',source)
                and not _denied(clause)):
            flags.append('plan_promoted_to_realized')
    # '확인해야 판단할 수 있다'는 판단 기준이며 회사 성과/주가의 가능성 주장이 아니다.
    # 그 문형의 양태만 제거한다. 같은 절에 남은 '주가가 오를 수 있다' 등은 계속 심사한다.
    hypothesis_clauses=[_criterion_modality(clause) for clause in clauses]
    hypothesis=any(re.search(r'가능|기여할|수\s*있|예상(?!치)|전망(?!치)',clause) and not _denied(clause) and not reported_forecast(clause)
                   and not (re.search(r'확인할|살펴볼|점검할|비교할',clause) and not re.search(r'기여|효과|영향',clause)) for clause in hypothesis_clauses)
    requirements=()
    if hypothesis and re.search(r'생산|출하|수급|매수|주가|매출|이익|실적',text):
        requirements=('fact_connection','concrete_mechanism','no_leap','hypothesis_separated')
        if re.search(r'생산|출하',text):
            if not re.search(r'생산\s*능력.{0,12}(?:확대|증설)|생산\s*확대|출하\s*확대|증설',source):
                flags.append('hypothesis_without_related_fact')
            if not heading and not (re.search(r'가동|설비',mechanism_text) and re.search(r'수요|판매|주문',mechanism_text)
                    and re.search(r'경우|다면|되면|하면|뒷받침',mechanism_text)):
                flags.append('hypothesis_without_conditions_or_mechanism')
        elif re.search(r'주가|수급|매수|매도',text):
            if not market_facts:
                flags.append('market_hypothesis_without_trade_fact')
            if not heading and not (re.search(r'매수|매도|공급|수요|유통',mechanism_text) and re.search(r'경우|다면|되면|하면|지속|이어지',mechanism_text)):
                flags.append('market_hypothesis_without_mechanism')
        elif re.search(r'매출|이익|실적',text):
            if not re.search(r'공급\s*계약|수주|출하|생산\s*능력|투자|수요|판매',source):
                flags.append('earnings_hypothesis_without_related_fact')
            if not heading and not (re.search(r'경우|다면|되면|하면|뒷받침|이어지면',mechanism_text)
                                    and re.search(r'가동|판매|수요|계약.{0,8}이행|출하',mechanism_text)):
                flags.append('earnings_hypothesis_without_mechanism')
        tier='T3'
    elif any(item.get('kind') in {'annual_comparison','cost_structure_comparison','quarterly_comparison'} for item in evidence.values()) and re.search(r'개선|성장|비중|원가율|이익률|수익성|마진',text):
        tier='T2'
    else:
        tier='T1'
    if flags:
        tier='T4'
    return InterpretationDecision(unit['id'],tier,tuple(dict.fromkeys(flags)),requirements)


def decisions_for(units, *, question='', evidence=None):
    enriched=[]
    for unit in units:
        if unit['id'].startswith('block_'):
            section=unit['id'].rsplit('_',1)[0]
            context=' '.join(other['statement'] for other in units if other['id'].rsplit('_',1)[0]==section
                             and set(other['evidence'])==set(unit['evidence']))
            enriched.append({**unit,'conditional_context':context})
        else:
            enriched.append(unit)
    result=[classify_unit(unit) for unit in enriched]
    for index,unit in enumerate(units):
        text=unit['statement']
        denied_comparison=re.search(r'(?:다른\s*방향|반대\s*방향|같은\s*기간)(?:인지|이라고|라고)?\s*(?:판단|확인|단정).{0,10}(?:없|어렵|않)',text)
        if re.search(r'시장|코스피|코스닥',text) and re.search(r'순매수|순매도',text) and re.search(r'이\s*기간|같은\s*기간|다른\s*방향|반대',text) and not denied_comparison:
            periods={item['period'] for item in unit['evidence'].values() if item.get('period') and '미확인' not in str(item['period'])
                     and re.search(r'순매수|순매도',str(item.get('text','')))}
            if len(periods)>1:
                old=result[index]
                result[index]=InterpretationDecision(old.unit_id,'T4',old.flags+('flow_period_mismatch',))
    if (evidence and any(item.get('cost_bridge_reconciled') for item in evidence.values())
            and re.search(r'왜|원인|이유|비결|요인',question)):
        text=' '.join(unit['statement'] for unit in units)
        explains_cost=bool(re.search(r'원가|판관비|판매관리비',text) and re.search(r'낮아|높아|하락|상승|같|유지|부담.{0,8}감소|비중.{0,8}감소',text))
        if not explains_cost and re.search(r'추가.{0,10}(?:확인|조사)|알\s*수\s*없|확인.{0,8}필요',text) and result:
            first=result[0]
            result[0]=InterpretationDecision(first.unit_id,'T4',first.flags+('available_cost_data_deferred',))
    return tuple(result)


def apply_veto(verdict,decisions):
    """기존 심사 호출·실패 계약은 유지한다. 코드 판정은 거절만 보강하며 승인하지 않는다."""
    rejected={d.unit_id for d in decisions if d.flags}
    if not rejected or not isinstance(verdict,dict):
        return verdict
    result={**verdict,'supported':False}
    if isinstance(verdict.get('checks'),dict):
        result['checks']={**verdict['checks'],'evidence_match':False}
    if isinstance(verdict.get('unit_reviews'),list):
        result['unit_reviews']=[{**item,'supported':False} if isinstance(item,dict) and item.get('id') in rejected else item
                                for item in verdict['unit_reviews']]
    return result
