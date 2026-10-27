from loopsmith import config


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def test_dotenv_loads_key_value(tmp_path, monkeypatch):
    monkeypatch.delenv("LOOPSMITH_SKIP_DOTENV", raising=False)
    monkeypatch.delenv("LOOPSMITH_EXAMPLE_A", raising=False)
    monkeypatch.delenv("LOOPSMITH_EXAMPLE_B", raising=False)
    env = _write(tmp_path / ".env",
                 "# comment\n\nLOOPSMITH_EXAMPLE_A=one\nLOOPSMITH_EXAMPLE_B = 'two words'\n")
    assert config.load_dotenv(env)
    import os
    assert os.environ["LOOPSMITH_EXAMPLE_A"] == "one"
    assert os.environ["LOOPSMITH_EXAMPLE_B"] == "two words"


def test_dotenv_supports_powershell_and_export_styles(tmp_path, monkeypatch):
    monkeypatch.delenv("LOOPSMITH_SKIP_DOTENV", raising=False)
    monkeypatch.delenv("LOOPSMITH_EXAMPLE_C", raising=False)
    monkeypatch.delenv("LOOPSMITH_EXAMPLE_D", raising=False)
    env = _write(tmp_path / ".env",
                 '$env:LOOPSMITH_EXAMPLE_C = "three"\nexport LOOPSMITH_EXAMPLE_D=four\n')
    config.load_dotenv(env)
    import os
    assert os.environ["LOOPSMITH_EXAMPLE_C"] == "three"
    assert os.environ["LOOPSMITH_EXAMPLE_D"] == "four"


def test_dotenv_does_not_override_real_env(tmp_path, monkeypatch):
    monkeypatch.delenv("LOOPSMITH_SKIP_DOTENV", raising=False)
    monkeypatch.setenv("LOOPSMITH_EXAMPLE_E", "real")
    env = _write(tmp_path / ".env", "LOOPSMITH_EXAMPLE_E=dotenv\n")
    config.load_dotenv(env)
    import os
    assert os.environ["LOOPSMITH_EXAMPLE_E"] == "real"


def test_dotenv_skip_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOPSMITH_SKIP_DOTENV", "1")
    monkeypatch.delenv("LOOPSMITH_EXAMPLE_F", raising=False)
    env = _write(tmp_path / ".env", "LOOPSMITH_EXAMPLE_F=x\n")
    assert config.load_dotenv(env) is False
    import os
    assert "LOOPSMITH_EXAMPLE_F" not in os.environ


def test_dotenv_missing_file(tmp_path):
    assert config.load_dotenv(tmp_path / "nope.env") is False


def test_llm_config_configured_flag():
    assert not config.LLMConfig().configured
    assert config.LLMConfig(base_url="u", api_key="k", model="m").configured