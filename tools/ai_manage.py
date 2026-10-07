"""Explicit server-only key generation, environment import and legacy export."""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import ai, ai_config, management_store as store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('generate-key', 'init', 'inspect', 'export-env'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        if args.mode == 'generate-key':
            if args.output is None:
                parser.error('--output required')
            ai_config.generate_key(args.output)
            print('独立主密钥已生成；不输出密钥。请只读挂载并单独备份。')
        elif args.mode == 'init':
            result = ai_config.initialize(ai.Settings.environment())
            print('环境配置已显式初始化。' if result['imported'] else '已有 AI 后台配置，未覆盖。')
        elif args.mode == 'inspect':
            import json
            print(json.dumps(ai_config.overview(), ensure_ascii=False))
        else:
            ai_config.required()
            if args.output is None or args.output.exists():
                parser.error('--output must name a new private destination')
            with store.connection() as db:
                current = ai_config.state(db)
                row = ai_config.version(db, current['last_good_version'] or current['desired_version'])
            settings = ai_config.load(row, ai.Settings.environment(), current['last_good_compat'] or current['desired_compat'])
            names = {'enabled':'AI_ENABLED','key':'DASHSCOPE_API_KEY','workspace':'BAILIAN_WORKSPACE_ID',
                     'agent':'BAILIAN_AGENT_ID','version':'AI_CONFIG_VERSION','timeout':'AI_TIMEOUT_SECONDS',
                     'concurrency':'AI_CONCURRENCY','visitor_daily':'AI_VISITOR_DAILY_LIMIT','ip_daily':'AI_IP_DAILY_LIMIT',
                     'site_daily':'AI_SITE_DAILY_LIMIT','token_daily':'AI_DAILY_TOKEN_LIMIT','token_reservation':'AI_TOKEN_RESERVATION'}
            args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor,'w',encoding='utf-8') as handle:
                for field, name in names.items():
                    value = getattr(settings,field)
                    handle.write(name + '=' + (str(int(value)) if type(value) is bool else str(value)) + '\n')
            print('旧版 AI 环境片段已写入私有文件；含密钥，请勿输出或上传。')
    except (store.ManagementError, OSError, ValueError):
        parser.exit(1,'AI 配置操作失败。请检查参数、主密钥及数据库；未输出密钥。\n')


if __name__ == '__main__':
    main()
