"""The native observer rejects broken evidence, rather than assigning a score."""

import importlib.util
from pathlib import Path
from xml.etree.ElementTree import ParseError

import pytest

PATH = Path(__file__).parents[1] / "tools/validation/programbench_seqtk_native.py"
SPEC = importlib.util.spec_from_file_location("seqtk_native", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_results_follow_official_last_occurrence_and_do_not_merge_outcomes():
    xml = b"""<testsuites><testsuite>
      <testcase classname="tests.sample" name="a"><failure/></testcase>
      <testcase classname="tests.sample" name="a"/>
      <testcase classname="tests.sample" name="b"><failure/><failure/></testcase>
      <testcase classname="tests.sample" name="c"><error/></testcase>
      <testcase classname="tests.sample" name="d"><skipped/></testcase>
    </testsuite></testsuites>"""
    assert MODULE.parse_tests(xml) == {
        "tests.sample.a": "passed",
        "tests.sample.b": "failure",
        "tests.sample.c": "error",
        "tests.sample.d": "skipped",
    }


@pytest.mark.parametrize(
    "xml",
    [
        b"<testsuites/>",
        b"<broken",
        b"<testcase/>",
        b'<testcase name="a"><error/><failure/></testcase>',
    ],
)
def test_invalid_or_missing_results_are_not_candidate_scores(xml):
    with pytest.raises((ValueError, ParseError)):
        MODULE.parse_tests(xml)
