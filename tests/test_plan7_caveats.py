import unittest
from src.agents.chat import strip_habitual_caveats as f
class T(unittest.TestCase):
    def test_mixed(self):
        t="PER은 10.43배입니다. 2025년 실적 기준 수익성이 개선된 흐름을 보이고 있으나, 투자 시점의 시장 상황과 개별 투자 목표에 따른 판단이 필요합니다."
        self.assertEqual(f(t),"PER은 10.43배입니다. 2025년 실적 기준 수익성이 개선된 흐름을 보이고 있습니다.")
    def test_drop_pure(self):
        self.assertEqual(f("영업이익은 증가했습니다. 추가 확인이 필요합니다."),"영업이익은 증가했습니다.")
        self.assertEqual(f("현재 확인된 삼성전자의 주가는 70,000.00원이며, 제공된 뉴스 자료 내에서는 주가 변동과 직접적으로 연결되는 구체적인 사건이나 보도 내용이 확인되지 않습니다."),
                         "현재 확인된 삼성전자의 주가는 70,000.00원입니다.")
        self.assertEqual(f("실적이 개선되었습니다. 수익성 개선의 구체적인 원인이 되는 세부 비용 항목이나 원가 구조의 변화는 확인된 자료 범위 내에서 단정하기 어려워 추가 확인이 필요합니다."),
                         "실적이 개선되었습니다.")
        self.assertEqual(f("실적 흐름이 좋습니다. 앞으로의 판단을 위해서는 향후 반도체 수요 전망이나 회사의 구체적인 생산 계획 등 실적 지속성을 뒷받침할 추가 자료 확인이 필요합니다."),
                         "실적 흐름이 좋습니다.")
    def test_keep(self):
        t="영업이익률이 13.07%로 올랐습니다."
        self.assertEqual(f(t),t)
if __name__=="__main__": unittest.main()
