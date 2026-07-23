from app.code_parser import FileSymbols
from app.security_scanner import scan_files


def _file(path: str, content: str, tmp_path) -> FileSymbols:
    full = tmp_path / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)
    return FileSymbols(path=str(full), language="python")


def test_clean_file_produces_no_findings(tmp_path):
    files = [_file("app.py", "def add(a, b):\n    return a + b\n", tmp_path)]

    report = scan_files(files)

    assert report.issues == []


def test_detects_aws_access_key(tmp_path):
    files = [_file("config.py", 'AWS_KEY = "AKIAABCDEFGHIJKLMNOP"\n', tmp_path)]

    report = scan_files(files)

    kinds = [i.kind for i in report.issues]
    assert "hardcoded_secret" in kinds
    assert report.issues[0].severity == "critical"


def test_does_not_flag_unrelated_short_string(tmp_path):
    files = [_file("config.py", 'GREETING = "hello world this is fine"\n', tmp_path)]

    report = scan_files(files)

    assert report.issues == []


def test_detects_private_key_header(tmp_path):
    files = [
        _file(
            "key.py",
            'KEY = """-----BEGIN RSA PRIVATE KEY-----\\nMIIB...\\n-----END RSA PRIVATE KEY-----"""\n',
            tmp_path,
        )
    ]

    report = scan_files(files)

    kinds = [i.kind for i in report.issues]
    assert "hardcoded_secret" in kinds


def test_detects_generic_secret_assignment(tmp_path):
    files = [_file("settings.py", 'api_key = "sk_live_1234567890abcdef"\n', tmp_path)]

    report = scan_files(files)

    kinds = [i.kind for i in report.issues]
    assert "hardcoded_secret" in kinds


def test_detects_subprocess_shell_true(tmp_path):
    files = [
        _file(
            "runner.py",
            "import subprocess\nsubprocess.run(cmd, shell=True)\n",
            tmp_path,
        )
    ]

    report = scan_files(files)

    kinds = [i.kind for i in report.issues]
    assert "dangerous_execution" in kinds
    assert report.issues[0].severity == "important"


def test_does_not_flag_subprocess_without_shell_true(tmp_path):
    files = [
        _file(
            "runner.py",
            'import subprocess\nsubprocess.run(["cmd", "--flag"])\n',
            tmp_path,
        )
    ]

    report = scan_files(files)

    assert report.issues == []


def test_detects_os_system_and_eval_and_exec(tmp_path):
    files = [
        _file(
            "risky.py",
            "os.system(user_input)\neval(user_input)\nexec(user_input)\n",
            tmp_path,
        )
    ]

    report = scan_files(files)

    kinds = [i.kind for i in report.issues]
    assert kinds.count("dangerous_execution") == 3


def test_does_not_flag_eval_method_call_on_a_custom_object(tmp_path):
    # Regression test for the 2026-07-24 real-world validation finding:
    # Django's django/template/smartif.py defines Operator.eval(), an
    # expression-evaluator method unrelated to the builtin eval() that
    # executes arbitrary strings -- x.eval(context) must not be flagged the
    # same as a bare eval(...) call.
    files = [
        _file(
            "smartif.py",
            'result = lambda context, x, y: x.eval(context) or y.eval(context)\n',
            tmp_path,
        )
    ]

    report = scan_files(files)

    assert report.issues == []


def test_still_flags_bare_eval_at_start_of_expression(tmp_path):
    files = [_file("risky.py", "result = (eval(user_input))\n", tmp_path)]

    report = scan_files(files)

    kinds = [i.kind for i in report.issues]
    assert kinds.count("dangerous_execution") == 1


def test_detects_js_child_process_exec(tmp_path):
    files = [
        FileSymbols(
            path=str((tmp_path / "run.js")),
            language="javascript",
        )
    ]
    (tmp_path / "run.js").write_text('child_process.exec("rm -rf " + userInput);\n')

    report = scan_files(files)

    kinds = [i.kind for i in report.issues]
    assert "dangerous_execution" in kinds


def test_detects_pickle_loads(tmp_path):
    files = [_file("cache.py", "import pickle\ndata = pickle.loads(raw)\n", tmp_path)]

    report = scan_files(files)

    kinds = [i.kind for i in report.issues]
    assert "unsafe_deserialization" in kinds
    assert report.issues[0].severity == "important"


def test_detects_bare_yaml_load(tmp_path):
    files = [_file("config.py", "import yaml\ndata = yaml.load(f)\n", tmp_path)]

    report = scan_files(files)

    kinds = [i.kind for i in report.issues]
    assert "unsafe_deserialization" in kinds


def test_does_not_flag_yaml_load_with_safe_loader(tmp_path):
    files = [
        _file(
            "config.py",
            "import yaml\ndata = yaml.load(f, Loader=yaml.SafeLoader)\n",
            tmp_path,
        )
    ]

    report = scan_files(files)

    assert report.issues == []


def test_hardcoded_secret_in_tests_directory_demoted_to_minor(tmp_path):
    # Regression test for the 2026-07-24 real-world validation finding:
    # Django's own test suite assigning dummy passwords in tests/ was
    # flagged critical, indistinguishable from a real leaked credential.
    files = [_file("tests/test_auth.py", 'password = "testpass123456"\n', tmp_path)]

    report = scan_files(files)

    assert len(report.issues) == 1
    assert report.issues[0].severity == "minor"
    assert "test/fixture path" in report.issues[0].message
    assert report.issues[0].kind == "hardcoded_secret"


def test_eval_in_test_fixtures_directory_demoted_to_minor(tmp_path):
    # Regression test: React's compiler test fixtures under __tests__/
    # legitimately contain eval()/exec() as the thing under test, flagged
    # important -- indistinguishable from a real dangerous-execution risk.
    files = [
        FileSymbols(
            path=str(tmp_path / "__tests__" / "fixtures" / "eval-case.js"),
            language="javascript",
        )
    ]
    (tmp_path / "__tests__" / "fixtures").mkdir(parents=True)
    (tmp_path / "__tests__" / "fixtures" / "eval-case.js").write_text("eval(userInput);\n")

    report = scan_files(files)

    assert len(report.issues) == 1
    assert report.issues[0].severity == "minor"


def test_test_prefixed_filename_demoted_even_outside_test_directory(tmp_path):
    files = [_file("test_config.py", 'api_key = "sk_live_1234567890abcdef"\n', tmp_path)]

    report = scan_files(files)

    assert report.issues[0].severity == "minor"


def test_dotted_test_suffix_filename_demoted(tmp_path):
    files = [
        FileSymbols(path=str(tmp_path / "auth.spec.ts"), language="javascript"),
    ]
    (tmp_path / "auth.spec.ts").write_text('const password = "hunter22222";\n')

    report = scan_files(files)

    assert report.issues[0].severity == "minor"


def test_regular_source_file_named_similarly_to_tests_dir_not_demoted(tmp_path):
    # "testutils.py" at the root is not a test file by our heuristic (no
    # test/tests/__tests__/fixtures directory segment, no test_/​_test/
    # .test/.spec filename pattern) -- a deliberately conservative
    # heuristic that only catches conventional naming, not anything with
    # "test" as a substring.
    files = [_file("testutils.py", 'password = "hunter222222"\n', tmp_path)]

    report = scan_files(files)

    assert report.issues[0].severity == "critical"


def test_issue_line_numbers_are_correct(tmp_path):
    files = [
        _file(
            "app.py",
            "x = 1\ny = 2\nAWS_KEY = \"AKIAABCDEFGHIJKLMNOP\"\n",
            tmp_path,
        )
    ]

    report = scan_files(files)

    assert report.issues[0].line == 3
