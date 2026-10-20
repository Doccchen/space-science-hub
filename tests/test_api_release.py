"""Deployment preflight helpers must distinguish secrets from numeric token budgets."""
from tools.deploy_api_management import credential_name,replace_images


def test_credential_metadata_filter_keeps_numeric_budgets():
    for name in ['DASHSCOPE_API_KEY','READER_MODEL_KEY','READER_WANFANG_API_KEY','X_INSTTOKEN','ACCESS_TOKEN','ADMIN_PASSWORD']:
        assert credential_name(name),name
    for name in ['READER_SITE_DAILY_TOKENS','AI_DAILY_TOKEN_LIMIT','AI_TOKEN_RESERVATION','AI_MASTER_KEY_FILE','NEWS_AGENT_CREDENTIALS_FILE','READER_MAX_PAGES','GPG_KEY','PYTHON_GPG_KEY']:
        assert not credential_name(name),name


def test_compose_image_replacement_preserves_other_settings():
    before='services:\n  app:\n    image: old-app\n    environment:\n      SOME_FLAG: keep\n  admin:\n    image: old-admin\n'
    after=replace_images(before,{'app':'new-app','admin':'new-admin'})
    assert after==before.replace('image: old-app','image: new-app').replace('image: old-admin','image: new-admin')
