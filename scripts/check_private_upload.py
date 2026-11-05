"""Check the user's quality condition without performing any Git/network write."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ontocare.upload_gate import assess


def main():
    try:
        result = assess(ROOT)
    except FileNotFoundError:
        result = {'allowed': False, 'reason': '尚未完成候选冻结，或缺少完整的回归与确认测试记录。',
                  'action': '保持本地，不上传。'}
        current=ROOT/'reports/workbench-v5/active-reference-profile.json'
        newer=current.exists()
        if not newer:current=ROOT/'reports/workbench-v4/retrieval-comparison.json'
        if current.exists():
            from ontocare.data import load_json
            result['current_large_regression']=load_json(current)['metrics' if newer else 'after']
            result['reason']='当前300题已见回归Recall@1仍低于90%，独立确认与独立忠实度非退化测试尚未完成。'
    except (ValueError, KeyError) as error:
        result = {'allowed': False, 'reason': str(error),
                  'action': '保持本地，不上传。'}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['allowed'] else 2


if __name__ == '__main__':
    sys.exit(main())
