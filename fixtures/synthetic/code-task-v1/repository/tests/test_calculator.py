import unittest

from calculator import add_one


class AddOneTest(unittest.TestCase):
    def test_positive_value(self) -> None:
        self.assertEqual(add_one(4), 5)

    def test_negative_value(self) -> None:
        self.assertEqual(add_one(-2), -1)


if __name__ == "__main__":
    unittest.main()
