"""Render observed repair status; missing experiments remain explicitly incomplete."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from ontocare.data import load_json, write_json


def main():
    folder = ROOT / 'reports/workbench-v5'
    read = lambda name: load_json(folder / name) if (folder / name).exists() else None
    sources = read('reference-audit.json'); judge = read('judge-consistency.json')
    history = []
    for arm, label in [('reference', '官方正文＋条件Prompt'), ('action', '来源动作筛选初版'), ('verified', '增加模型支持性检查'), ('action-fixed', '来源动作筛选修正版')]:
        replay = read(arm + '-result.json'); raw = read(arm + '-ragas-raw.json'); faith = {}
        if raw:
            for name in ['parent', arm]:
                values = [r['metrics'].get('faithfulness') for r in raw['cases'] if r['arm'] == name]
                if len(values) == 12 and all(type(v) in {float, int} for v in values): faith[name] = sum(values) / len(values)
        m = replay['arms'][arm] if replay else None
        decision = '评测未完成'
        if m and len(faith) == 2:
            if arm == 'action': decision = '拒绝初版：发现restart词形遗漏，保留记录'
            elif m['task_pass_rate'] < replay['arms']['parent']['task_pass_rate']: decision = '拒绝：流程通过或完成率回归'
            elif faith[arm] < faith['parent']: decision = '拒绝：忠实度下降'
            else: decision = '本机局部修复；保留1个新退步，未通过独立验收'
        history.append({'id': arm, 'name': label, 'metrics': m, 'faithfulness': faith, 'decision': decision,
                        'runtime_id': replay['protocol']['runtimes'][arm]['id'] if replay else None})
    fit = read('chunk-fit.json'); chunk = read('chunk-validation.json'); ranking = read('reference-ranking-validation.json'); legacy = read('reference-ranking-legacy.json')
    report = {'status': '原始资料、gold、Judge五维和通过阈值保留；所有候选与回归同时展示。独立验收未通过，不上传。',
              'sources': {k: sources[k] for k in ['articles', 'article_status', 'link_status']} if sources else None,
              'judge': {'cases': len(judge['cases']), 'agreement_rate': judge['agreement_rate'], 'pending_adjudication': judge['pending_adjudication']} if judge else None,
              'history': history, 'chunk': {'fit': fit, 'metrics': chunk['metrics'] if chunk else None} if fit else None,
              'reference_ranking': {'validation': ranking['metrics'] if ranking else None, 'legacy': legacy['metrics'] if legacy else None},
              'active_retrieval': (read('active-reference-profile.json') or {}).get('metrics'),
              'paired_check': read('paired-repair-check.json'),
              'repaired_judge': {k:v for k,v in (read('repaired-judge-consistency.json') or {}).items() if k in ['agreement_rate','pending_adjudication']},
              'confirmation_status': '未运行，保持冻结；验证与回归达标后才开启一次',
              'upload_status': '禁止上传：独立Recall@1>90%且独立忠实度不下降的证据尚未齐全',
              'old_gold_changed': False, 'judge_rubric_changed': False, 'old_scores_overwritten': False}
    write_json(folder / 'repair-status.json', report); write_json(ROOT / 'web/workbench-repairs.json', report)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    task = [read('reference-result.json')['arms']['parent']['task_pass_rate']] + [h['metrics']['task_pass_rate'] if h['metrics'] else np.nan for h in history]
    faith = [history[0]['faithfulness'].get('parent', np.nan)] + [h['faithfulness'].get(h['id'], np.nan) for h in history]
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6)); labels = ['Parent', 'References', 'Action v1', 'LLM guard', 'Action fix']
    for axis, values, title in zip(axes, [task, faith], ['Machine workflow pass (72 seen cases)', 'Ragas faithfulness (12 fixed queries)']):
        axis.plot(range(5), np.array(values) * 100, marker='o', color='#7656d8'); axis.set_xticks(range(5), labels, rotation=15); axis.set_title(title); axis.set_ylabel('%'); axis.set_ylim(80, 101); axis.grid(alpha=.2)
        for i, value in enumerate(values):
            if np.isfinite(value): axis.annotate(f'{value*100:.2f}', (i, value * 100), xytext=(0, -15), textcoords='offset points', ha='center', fontsize=9)
    fig.suptitle('All candidate outcomes retained; not independent convergence evidence', fontsize=11); fig.tight_layout(); fig.savefig(ROOT / 'web/repair-history.svg'); fig.savefig(folder / 'repair-history.png', dpi=160); plt.close(fig)
    print({'history': [(h['id'], h['decision']) for h in history], 'sources': bool(sources), 'confirmation': report['confirmation_status']}, flush=True)


if __name__ == '__main__': main()
