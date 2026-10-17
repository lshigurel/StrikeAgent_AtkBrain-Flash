import unittest

from atkbrain.api.routes import _normalize_ctf_flag_count


class CtfFlagCountTests(unittest.TestCase):
    def test_default_is_one(self):
        self.assertEqual(_normalize_ctf_flag_count(None), 1)

    def test_accepts_boundaries_and_strings(self):
        self.assertEqual(_normalize_ctf_flag_count(1), 1)
        self.assertEqual(_normalize_ctf_flag_count(100), 100)
        self.assertEqual(_normalize_ctf_flag_count("3"), 3)

    def test_rejects_invalid_values(self):
        for value in (0, 101, -1, "abc", ""):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _normalize_ctf_flag_count(value)


if __name__ == "__main__":
    unittest.main()
