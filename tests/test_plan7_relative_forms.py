import unittest
from src.agents.literal_numbers import mask_relative_years as m
import datetime
class T(unittest.TestCase):
    def test_in_form(self):
        r=m("내년인 2027년의 경우 목표는 없고 2027년의 수치는 없습니다.", datetime.date(2026,10,28))
        self.assertNotRegex(r,r"\d")
    def test_wrong_year_kept(self):
        r=m("내년인 2030년의 경우", datetime.date(2026,10,28))
        self.assertIn("2030",r)
if __name__=="__main__": unittest.main()
