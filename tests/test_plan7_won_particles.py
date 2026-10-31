import unittest
from src.agents.chat import fix_won_particles


class WonParticleTests(unittest.TestCase):
    def test_particle_after_won_amount_follows_final_consonant(self):
        self.assertEqual(fix_won_particles("현재가 240,750.00원와 시장을 봅니다."), "현재가 240,750.00원과 시장을 봅니다.")
        self.assertEqual(fix_won_particles("주가 239,500.00원가 낮습니다."), "주가 239,500.00원이 낮습니다.")
        self.assertEqual(fix_won_particles("종가는 234,500원로 마감했습니다."), "종가는 234,500원으로 마감했습니다.")
        self.assertEqual(fix_won_particles("영업이익 43.6조 원는 늘었습니다."), "영업이익 43.6조 원은 늘었습니다.")

    def test_words_that_merely_contain_won_are_untouched(self):
        for text in ("매출원가는 낮아졌습니다.", "원가가 올랐습니다.", "100원가량 올랐습니다."):
            self.assertEqual(fix_won_particles(text), text)


if __name__ == "__main__":
    unittest.main()
