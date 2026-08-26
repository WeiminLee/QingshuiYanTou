from app.config import Settings


def test_api_scheduler_defaults_off_to_prevent_duplicate_consumers():
    settings = Settings(
        database_url="postgresql+asyncpg://test",
        mongodb_url="mongodb://test",
        llm_api_key="test",
        neo4j_password="test",
    )

    assert settings.enable_api_scheduler is False
