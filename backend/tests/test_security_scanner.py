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
