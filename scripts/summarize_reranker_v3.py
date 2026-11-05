"""Local experiment ledger. Failed candidates remain visible; no upload occurs."""
from pathlib import Path
from collections import defaultdict
from math import comb
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ontocare.data import load_json, write_json, digest
from ontocare.upload_gate import threshold_passes


def main():
    folder = ROOT / 'reports/reranker-v3'
    selected_small = load_json(folder / 'english-selection.json')['selected']['name']
    sources = [
        ('原始基线', 'reports/grounded-eval/baseline-reserve.json'),
        ('上一轮受控核验', 'reports/grounded-eval/candidate-reserve.json'),
        ('小型重排器＋开发集权重', 'reports/reranker-v3/' + selected_small + '-legacy.json'),
        ('型号文本遮蔽', 'reports/reranker-v3/masked-legacy.json'),
        ('扩大证据池＋原话核验', 'reports/reranker-v3/alignment-legacy.json'),
        ('BGE 候选', 'reports/reranker-v3/bge-legacy.json'),
    ]
    history = []
    for label, name in sources:
        path = ROOT / name
        if not path.exists():
            continue
        data = load_json(path)
        history.append({'name': label, 'result_file': name,
                        'result_sha256': digest(data), 'metrics': data['metrics'],
                        'regression_gate_passed': threshold_passes(data['metrics'])})
    best = max(history, key=lambda r: r['metrics']['recall_at_1'])
    old = {r['id']: r for r in load_json(ROOT / sources[1][1])['cases']}
    compared = load_json(ROOT / sources[4][1])['cases']
    gains = losses = 0
    groups = defaultdict(list)
    for row in compared:
        delta = row['scores']['hit_at_1'] - old[row['id']]['scores']['hit_at_1']
        gains += int(delta > 0)
        losses += int(delta < 0)
        groups[row['family_id']].append(delta)
    differences = [sum(values) / len(values) for values in groups.values()]
    rng = random.Random(20261103)
    boot = sorted(sum(rng.choices(differences, k=len(differences))) / len(differences) for _ in range(5000))
    n = gains + losses
    paired = {'paired_queries': len(compared), 'source_families': len(groups),
              'improved_first_hit': gains, 'regressed_first_hit': losses,
              'net_more_hits': gains - losses,
              'family_bootstrap_hit_delta_95_interval': [boot[125], boot[4874]],
              'mcnemar_exact_two_sided_p': min(1., 2 * sum(comb(n, i) for i in range(min(gains, losses) + 1)) / (2 ** n)) if n else 1.,
              'unit_caveat': 'McNemar is query-level diagnostic only; use family bootstrap for paired zh/en dependence. Neither is production-outcome evidence.'}
    write_json(folder / 'paired-change.json', paired)
    state = {'status': 'local_only', 'upload_performed_by_this_workflow': False,
             'benchmark': 'same 300 query forms / 150 known source families',
             'benchmark_scope': 'exposed historical regression, not independent confirmation',
             'gold_modified': False, 'history': history, 'best_regression': best,
             'wide_vs_previous_paired': paired,
             'confirmation_status': 'not_run' if not (folder / 'confirmation-result.json').exists() else 'see_result_file',
             'resolution_rate': None,
             'notes': ['Model-training epochs and weight-search trials are not autonomous RSI publication rounds.',
                       'No new candidate is a release until both regression and frozen confirmation pass.',
                       'Source conflicts and suspected label equivalents remain pending owner review.']}
    pilot_path = folder / 'bge-pilot.json'
    pilot = load_json(pilot_path) if pilot_path.exists() else None
    if pilot:
        state['bge_development_pilot'] = {name: result['metrics'] for name, result in pilot['variants'].items()}
        state['bge_progression_passed'] = any(m['hit_at_1'] >= .93 and m['recall_at_1'] >= .89 for m in state['bge_development_pilot'].values())
    write_json(folder / 'local-status.json', state)
    lines = ['# 本地改进与上传门槛检查', '',
             '同一批 300 个问题形式、150 个已见来源案例。中英文不算两个独立客户。原冻结标准答案未改；此表是历史回归，不能当作独立盲测。', '',
             '| 候选 | 首条命中 Hit@1 | 资料集合 Recall@1 | 回归门槛 |',
             '|---|---:|---:|---|']
    for row in history:
        m = row['metrics']
        lines.append(f'| {row["name"]} | {m["hit_at_1"]:.2%} | {m["recall_at_1"]:.2%} | {"通过，仍需确认测试" if row["regression_gate_passed"] else "未通过"} |')
    lines += ['', '## 判定', '',
              '上传要求首条命中和资料集合 Recall@1 均严格大于 90%，同时通过完整的新措辞确认测试。验证集高分、工程检查通过、任务回复通过率，不能代替这个条件。', '',
              '当前最佳回归候选为“' + best['name'] + '”。确认集状态：' + state['confirmation_status'] + '。本流程没有执行 GitHub 上传。', '',
              '已有的 87% 历史实验分支是此前上传的记录，继续保留；本轮新增代码、README 和评测均留在本机。', '',
              '## 已完成的改进尝试', '',
              '- 多语言和英文小型交叉编码重排器；仅在开发集拟合全局权重，在验证集选择。',
              '- 对小型重排模型的最后两层做 3 个训练 epoch；这是重排模型训练，不是主 LLM 的 RLHF。',
              '- 型号字段继续作硬过滤，在相似度文本中遮蔽型号词，检查名称重复对排序的影响。',
              '- 扩大去重后的 FAQ 候选池，同时读取客户原话、检索改写和原文进行核验，保留每次选择理由。',
              '- 失败候选没有替换当前客服默认实现；新确认题没有用于调参。', '',
              '## 数据核查', '',
              '[六组来源与标签待核查记录](source-label-review.md)包含原表位置及逐字段核对。序列号位置和水痕处理存在冲突，部分升级等 FAQ 近似。它们仍按原口径计分；待负责人确认后，若需修订，应建立新版本，不能回写已测成绩。', '',
              '真实问题解决率尚不可测：现有首封邮件没有结案、重开、用户确认等结果。']
    interval = paired['family_bootstrap_hit_delta_95_interval']
    lines += ['', '## 配对变化与回归', '',
              f'扩大证据池相对上一轮：{gains} 个问题由未命中变命中，{losses} 个由命中变未命中，净增 {gains-losses} 个。', '',
              f'按来源案例分组重采样的首条命中差异 95% 区间为 {interval[0]:.2%} 至 {interval[1]:.2%}。区间包含零，不能宣称稳定提升或有效收敛。中英文形式始终按同一来源分组。']
    if pilot:
        lines += ['', '## BGE 开发小样本（不同于上述回归集）', '',
                  '固定 30 个开发来源、60 个中英文问题形式。三种预先设定的排序方式如下；此小样本不作为最终成绩，也不混入上面的 300 题。', '',
                  '| 方式 | 首条命中 | 资料集合 Recall@1 |', '|---|---:|---:|']
        for name, result in pilot['variants'].items():
            m = result['metrics']
            lines.append(f'| {name} | {m["hit_at_1"]:.2%} | {m["recall_at_1"]:.2%} |')
        lines += ['', '是否达到事先设定的扩大评测条件：' + str(state['bge_progression_passed']) + '。没有通过时不继续消耗确认测试，也不替换默认客服。', '',
                  '[BGE 官方说明](https://huggingface.co/BAAI/bge-reranker-v2-m3)。本地实验使用固定版本与半精度，不能把模型公开基准等同于本项目结果。']
    lines += ['', '![同一批历史回归题的候选对比](candidate-comparison.png)', '',
              '此图比较算法候选，包含被拒绝的下降结果；它不是生产解决率曲线，也不能单独证明收敛。']
    (folder / 'local-status.md').write_text('\n'.join(lines) + '\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    import numpy as np
    labels = ['Baseline', 'V2 verification', 'Small cross-encoder', 'PN text masking', 'Wide alignment', 'BGE'][:len(history)]
    chinese_font = Path('/System/Library/Fonts/Hiragino Sans GB.ttc')
    if chinese_font.exists():
        font_manager.fontManager.addfont(str(chinese_font))
        plt.rcParams['font.family'] = font_manager.FontProperties(fname=chinese_font).get_name()
        labels = [r['name'] for r in history]
    x = np.arange(len(history))
    fig, ax = plt.subplots(figsize=(10, 4.5), layout='constrained')
    hit_bars = ax.bar(x - .18, [r['metrics']['hit_at_1'] * 100 for r in history], .36, label='首条命中 Hit@1', color='#6174d8')
    recall_bars = ax.bar(x + .18, [r['metrics']['recall_at_1'] * 100 for r in history], .36, label='资料集合 Recall@1', color='#3b9d93')
    ax.bar_label(hit_bars, fmt='%.2f', padding=3, fontsize=8)
    ax.bar_label(recall_bars, fmt='%.2f', padding=3, fontsize=8)
    ax.axhline(90, color='#b74f51', linestyle='--', label='须严格超过 90%')
    ax.set(xticks=x, xticklabels=labels, ylim=(0, 105), ylabel='Percent',
           title='同一批历史回归 300 题：冻结标准答案未修改；包含被拒绝的候选')
    ax.tick_params(axis='x', labelsize=9)
    ax.legend(loc='lower left')
    fig.savefig(folder / 'candidate-comparison.svg')
    fig.savefig(folder / 'candidate-comparison.png', dpi=160)
    plt.close(fig)
    print({'best': best['name'], 'metrics': best['metrics'],
           'confirmation': state['confirmation_status'], 'upload': False})


if __name__ == '__main__':
    main()
