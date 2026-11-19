from netdiag.cli import finish_session


class FakeConsole:
    def __init__(self, answer):
        self.answer = answer
        self.lines = []

    def print(self, value):
        self.lines.append(str(value))

    def input(self, _prompt):
        return self.answer


def test_finish_can_skip_report(tmp_path):
    console = FakeConsole("n")
    finish_session(tmp_path, console)
    output = "\n".join(console.lines)
    assert "Medicion terminada limpiamente" in output
    assert "netdiag report" in output
