# -*- coding: utf-8 -*-
"""
calibrate.py —— THERP 校准系数自动拟合
======================================
以 HP.EXE 的 OUT.DAT 为基准, 对 hp_thermal.CALIB 中 8 个物性校准因子
(热侧/冷侧 各 rho/mu/cp/k) 做不动点迭代, 使 Python 版输出逐项复刻原程序。

更新规则(由输出量对物性因子的敏感性直接导出, 带阻尼):
  WW  ∝ 1/rho       -> f_rho *= (WW_run / WW_target)
  RE  ∝ 1/mu        -> f_mu   *= (RE_run / RE_target)
  QH  ∝ cp·ΔT       -> f_cp   *= (QH_t/QH_run)·(ΔT_run/ΔT_t)
  HFE ≈ ∝ k^(2/3)   -> f_k    *= (HFE_t/HFE_run)^1.5
收敛后写入 CALIB.JSON, hp_thermal.py 启动时自动加载; 删除该文件即回到
纯 CoolProp 物理直算模式。
"""
import json
import os
import sys

import hp_thermal as hp

HERE = os.path.dirname(os.path.abspath(__file__))
INB = os.path.join(HERE, 'INB.DAT')
OUT = os.path.join(HERE, 'OUT_PY.DAT')
REF = os.path.join(HERE, 'OUT.DAT')

if not os.path.exists(REF):
    print('错误: 找不到基准文件 OUT.DAT, 无法校准')
    sys.exit(1)


def parse_out(path):
    vals = {}
    with open(path, 'r', encoding='gbk', errors='replace') as f:
        for line in f:
            t = line.split()
            if len(t) >= 3 and t[0].isdigit():
                try:
                    vals[int(t[0])] = float(t[-1])
                except ValueError:
                    pass
    return vals


T = parse_out(REF)
p = hp.load_inb(INB)
TFJH, TFJC = p['tfjh'], p['tfjc']

# 校准目标: 21 热侧放热量, 23 冷侧吸热量, 25/26 流速(rho), 27/28 雷诺数(mu),
#           29/30 有效换热系数(k); 4/8 出口温度为收敛校验项
KEYS = [('qh', 21), ('qc1', 23), ('wwh', 25), ('wwc', 26),
        ('reh', 27), ('rec', 28), ('hfeh', 29), ('hfec', 30)]

DAMP = 0.7
fac = {'h': dict(hp.CALIB['h']), 'c': dict(hp.CALIB['c'])}

print('校准目标(取自 OUT.DAT):')
print('  QH=%.0f  QC1=%.0f  WWH=%.2f  WWC=%.2f' % (T[21], T[23], T[25], T[26]))
print('  REH=%.1f REC=%.1f  HFEH=%.2f HFEC=%.2f' % (T[27], T[28], T[29], T[30]))
print('  TFCH=%.1f TFCC=%.1f (收敛校验)\n' % (T[4], T[8]))
print('%-4s %-30s %-30s %s' % ('迭代', '热侧因子 rho/mu/cp/k',
                              '冷侧因子 rho/mu/cp/k', '最大残差%'))

for it in range(1, 61):
    hp.CALIB['h'].update(fac['h'])
    hp.CALIB['c'].update(fac['c'])
    R = hp.main(INB, OUT, verbose=False)
    res = max(abs(R[k] / T[no] - 1.) for k, no in KEYS) * 100.
    fh, fc = fac['h'], fac['c']
    print('%-4d %-30s %-30s %.4f' % (
        it,
        '/'.join('%.4f' % fh[k] for k in ('rho', 'mu', 'cp', 'k')),
        '/'.join('%.4f' % fc[k] for k in ('rho', 'mu', 'cp', 'k')),
        res))
    if res < 0.05:
        break

    def upd(f0, ratio):
        return f0 * ratio ** DAMP

    nh = dict(fh)
    nc = dict(fc)
    nh['rho'] = upd(fh['rho'], R['wwh'] / T[25])
    nh['mu'] = upd(fh['mu'], R['reh'] / T[27])
    nh['cp'] = upd(fh['cp'], (T[21] / R['qh']) * ((TFJH - R['tfch']) / (TFJH - T[4])))
    nh['k'] = upd(fh['k'], (T[29] / R['hfeh']) ** 1.5)
    nc['rho'] = upd(fc['rho'], R['wwc'] / T[26])
    nc['mu'] = upd(fc['mu'], R['rec'] / T[28])
    nc['cp'] = upd(fc['cp'], (T[23] / R['qc1']) * ((R['tfcc'] - TFJC) / (T[8] - TFJC)))
    nc['k'] = upd(fc['k'], (T[30] / R['hfec']) ** 1.5)
    fac = {'h': nh, 'c': nc}

hp.CALIB['h'].update(fac['h'])
hp.CALIB['c'].update(fac['c'])
with open(os.path.join(HERE, 'CALIB.JSON'), 'w', encoding='utf-8') as f:
    json.dump(fac, f, indent=2)
print('\n校准系数已写入 CALIB.JSON:')
print(json.dumps(fac, indent=2))

print('\n================ 校准后最终对比 ================')
hp.main(INB, OUT, verbose=True)
sys.stdout.flush()
os._exit(0)
