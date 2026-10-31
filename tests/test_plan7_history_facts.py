import unittest
from src.agents.literal_numbers import mask_history_facts as m
EV={"HISTORY":{"first_close":220000.0,"last_close":237750.0,"change_pct":8.068181818181808,"period":"2026-07-28~2026-10-28"}}
class T(unittest.TestCase):
    def test_masks_matching_values(self):
        t="2026년 7월 28일 220,000.00원 대비 2026년 10월 28일 237,750원으로 8.07% 상승했습니다."
        self.assertFalse(any(c.isdigit() for c in m(t,EV)))
    def test_direction_mismatch_kept(self):
        self.assertIn("8", m("8.07% 하락했습니다.",EV))
    def test_wrong_value_kept(self):
        self.assertIn("2", m("종가는 230,000원이었습니다.",EV))
    def test_requires_cited_history(self):
        t="220,000.00원에서 8.07% 상승"
        self.assertEqual(m(t,{}),t)
if __name__=="__main__": unittest.main()
