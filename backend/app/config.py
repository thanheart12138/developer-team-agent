from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "mysql+pymysql://root@127.0.0.1:3306/dev_team_simulator"
    workspace_root: Path = Path("workspace")
    model_provider: str = "deepseek"
    deepseek_api_key: str = ""
    deepseek_api_key_file: Path = Path("secrets/deepseek_api_key")
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    kimi_api_key: str = ""
    kimi_api_key_file: Path = Path("secrets/kimi_api_key")
    kimi_base_url: str = "https://api.kimi.com/coding/v1"
    kimi_model: str = "kimi-for-coding"
    kimi_max_completion_tokens: int = 8192
    openrouter_api_key: str = ""
    openrouter_api_key_file: Path = Path("secrets/openrouter_api_key")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openai/gpt-6-luna"
    worker_poll_seconds: float = 1.0
    frontend_origin: str = "http://127.0.0.1:5173"

    model_config = SettingsConfigDict(env_prefix="SIMULATOR_", extra="ignore")


settings = Settings()


def _get_api_key(value: str, path: Path) -> str:
    """从配置值或受控文件读取密钥，不记录或暴露其内容。"""
    # 已提供配置值时直接使用；否则仅从指定文件读取。
    if value:
        return value
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def get_deepseek_api_key() -> str:
    # 取得 DeepSeek 的 API 密钥。
    return _get_api_key(settings.deepseek_api_key, settings.deepseek_api_key_file)


def get_kimi_api_key() -> str:
    # 取得 Kimi 的 API 密钥。
    return _get_api_key(settings.kimi_api_key, settings.kimi_api_key_file)


def get_openrouter_api_key() -> str:
    # 取得 OpenRouter 的受控 API 密钥。
    return _get_api_key(settings.openrouter_api_key, settings.openrouter_api_key_file)
