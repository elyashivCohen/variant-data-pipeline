"""Run the Convert suite with readable labels and unittest failure details."""

import sys
import unittest
from pathlib import Path


class ReadableTestResult(unittest.TextTestResult):
    """Count successful methods and report unsuccessful unittest events."""

    def __init__(self, stream, descriptions, verbosity):
        super().__init__(stream, descriptions, verbosity)
        self.showAll = False
        self.dots = False
        self.passed = 0

    def getDescription(self, test):
        return test.shortDescription() or str(test)

    def report(self, label, test, detail=""):
        suffix = f" - {detail}" if detail else ""
        self.stream.writeln(f"[{label}] {self.getDescription(test)}{suffix}")
        self.stream.flush()

    def addSuccess(self, test):
        super().addSuccess(test)
        self.passed += 1
        self.report("PASS", test)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.report("FAIL", test)

    def addError(self, test, err):
        super().addError(test, err)
        self.report("ERROR", test)

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.report("SKIP", test, reason)

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            label = "FAIL" if issubclass(err[0], test.failureException) else "ERROR"
            self.report(label, test, subtest.id())

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.report("SKIP", test, "expected failure")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.report("FAIL", test, "unexpected success of an expected-failure test")


class ReadableTestRunner(unittest.TextTestRunner):
    """Keep unittest execution and tracebacks, then summarize actual outcomes."""

    resultclass = ReadableTestResult

    def run(self, test):
        result = super().run(test)
        self.stream.writeln(
            f"Results: {result.passed} passed | "
            f"{len(result.failures) + len(result.unexpectedSuccesses)} failed | "
            f"{len(result.errors)} errors | "
            f"{len(result.skipped) + len(result.expectedFailures)} skipped"
        )
        self.stream.flush()
        return result


def main(suite=None):
    """Discover relative to this script and return a process exit status."""
    if suite is None:
        tests_dir = Path(__file__).resolve().parent
        sys.path.insert(0, str(tests_dir.parent))
        suite = unittest.defaultTestLoader.discover(str(tests_dir))
    result = ReadableTestRunner(verbosity=0).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
