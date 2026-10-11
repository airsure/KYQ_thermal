# -*- coding: utf-8 -*-
"""
热管式气-气换热器设计/校核计算 —— HP.FOR 的 Python 复现
=========================================================
原程序 : HP.EXE / HP.FOR（Fortran 77 + THERP 物性库, 2000-08-10）
物性来源: CoolProp 8.x（HEOS 混合物模型）+ THERP 校准系数（可选）
          - 分子量/比热/粘度/导热系数: CoolProp 混合物物性
          - 密度: 理想气体状态方程 P*M/(R*T)，与原程序 Nm^3/22.4 标况
            换算基准保持一致
          - CALIB.JSON（如存在）提供按侧校准系数，使物性值对齐 1985 年
            THERP 库，从而逐项复刻 HP.EXE 输出；删除该文件即回到纯
            CoolProp 物理直算。系数由 calibrate.py 自动拟合。
说明:
  1. INB.DAT 按 Fortran 固定列宽格式解析（与 HP.FOR 的 FORMAT 语句一一
     对应，数值字段内空格按 Fortran BLANK='NULL' 语义忽略）
  2. 主流程与迭代结构严格按 HP.FOR 还原:
       - 热平衡迭代回路   : |DQ| <= 1%              (源码 label 30)
       - 温度交叉检查     : TFJH > TFCC 否则重算    (源码 label 800)
       - 校核面积迭代回路 : |DAHH| < 0.5%           (源码 label 76-84)
  3. 输出 OUT_PY.DAT，39 项与原 OUT.DAT 同构；若目录下存在 OUT.DAT
     自动输出原程序 vs Python 版逐项对比表。
用法: python hp_thermal.py [输入文件=INB.DAT] [输出文件=OUT_PY.DAT]
      python hp_gui.py       # PyQt5 图形界面（界面填写参数, 表格显示结果, 可导出）
      # 也可 import hp_thermal; rows, R = hp_thermal.compute(load_inb('INB.DAT'))
"""
import itertools
import math
import os
import sys

import CoolProp.CoolProp as CPC

# ---------------- THERP 组分编号 -> CoolProp 流体名 ----------------
# 编号含义见 readme.txt 与 DBANK.DAT（1N2 2O2 3H2 4CO 5CO2 6COS 7CS2 8SO2 9H2S 12H2O 13CH4）
FLUIDS = {1: 'Nitrogen', 2: 'Oxygen', 3: 'Hydrogen', 4: 'CarbonMonoxide',
          5: 'CarbonDioxide', 6: 'CarbonylSulfide', 7: 'CarbonDisulfide',
          8: 'SulfurDioxide', 9: 'HydrogenSulfide', 12: 'Water', 13: 'Methane'}

KGF_CM2_TO_PA = 98066.5    # 1 kgf/cm^2 (绝压)

# ---------------- THERP 校准系数 ----------------
# 语义: THERP 物性值 = f × CoolProp 物性值（按热侧 h / 冷侧 c 分别修正）
#   rho: 密度   mu: 动力粘度   cp: 比热   k: 导热系数
# 默认全 1.0 = 纯 CoolProp 物理直算；CALIB.JSON 存在时自动加载。
CALIB = {'h': {'rho': 1.0, 'mu': 1.0, 'cp': 1.0, 'k': 1.0},
         'c': {'rho': 1.0, 'mu': 1.0, 'cp': 1.0, 'k': 1.0}}


def _load_calib(path=None):
    import json
    p = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'CALIB.JSON')
    if os.path.exists(p):
        with open(p, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        for s in ('h', 'c'):
            for k in ('rho', 'mu', 'cp', 'k'):
                if s in data and k in data[s]:
                    CALIB[s][k] = float(data[s][k])
    return CALIB

_load_calib()

# ---------------- Fortran 固定列宽格式解析 ----------------

def parse_line(line, spec):
    """按 Fortran FORMAT 固定列宽截取字段。
    spec: [(宽度, 'I'|'F'), ...]，对应原程序 900~906 各格式语句。
    数值字段内的空格按 Fortran 默认 BLANK='NULL' 语义忽略。
    兼容回退: 手工编辑的输入文件列宽常不对齐, 固定列宽切分会把数字切成
    两半(如 0.00035|0.00000 被切成 0.0003 与 50.0)。因此当按空白切分
    恰好得到 spec 字段数且全部为合法数字时, 优先按空白切分取值; 含空缺
    字段(空格补位表示 0)的正规文件仍走固定列宽解析。"""
    tokens = line.replace('\n', '').replace('\r', '').split()
    if len(tokens) == len(spec):
        try:
            return [(int(t) if ty == 'I' else float(t))
                    for t, (_, ty) in zip(tokens, spec)]
        except ValueError:
            pass
    vals, pos = [], 0
    for w, t in spec:
        seg = line[pos:pos + w].replace(' ', '').replace('\n', '').replace('\r', '')
        pos += w
        vals.append(int(seg) if t == 'I' else float(seg))
    return vals


def load_inb(path):
    with open(path, 'r', encoding='ascii', errors='replace') as f:
        lines = f.readlines()
    d = {}
    d['ids'] = parse_line(lines[0], [(2, 'I')] * 7)                 # 第一行: 7组分编号
    d['vfh'], d['pfh'] = parse_line(lines[2], [(12, 'F'), (8, 'F')])   # 900: 流量/压力
    d['tfjh'], d['tfch'] = parse_line(lines[3], [(8, 'F'), (8, 'F')])  # 901: 进/出口温度
    d['alh'], d['hfh'], d['drtafh'], d['sfh'] = \
        parse_line(lines[4], [(7, 'F'), (5, 'F'), (5, 'F'), (5, 'F')])  # 902
    d['do'], d['di'], d['st'], d['sl'] = \
        parse_line(lines[5], [(5, 'F'), (5, 'F'), (6, 'F'), (6, 'F')])  # 903
    d['xh'] = parse_line(lines[6], [(6, 'F')] * 7)                  # 904: 组分%
    d['vfc'], d['pfc'] = parse_line(lines[7], [(12, 'F'), (8, 'F')])
    d['tfjc'], d['tfcc'] = parse_line(lines[8], [(8, 'F'), (8, 'F')])
    d['alc'], d['hfc'], d['drtafc'], d['sfc'] = \
        parse_line(lines[9], [(7, 'F'), (5, 'F'), (5, 'F'), (5, 'F')])
    d['xc'] = parse_line(lines[10], [(6, 'F')] * 7)
    d['wn'], d['flmd'], d['tlmd'], d['ryh'], d['ryc'], d['hzf'], d['hlz'] = \
        parse_line(lines[11], [(5, 'F'), (5, 'F'), (5, 'F'),
                               (8, 'F'), (8, 'F'), (8, 'F'), (8, 'F')])  # 905
    d['ibh'], d['imh'], d['kt'] = parse_line(lines[12], [(5, 'I')] * 3)  # 906
    return d

# ---------------- FPROP: 混合气体物性（CoolProp + THERP 校准） ----------------
_AS_CACHE = {}
_PURE_CACHE = {}          # 纯组分 AbstractState 缓存（输运性质回退用）
_PAIR_RULES_DONE = False  # 缺失二元对补规则只做一次


def _make_abstract_state(fl):
    """创建 HEOS 混合物 AbstractState; 内置二元交互参数对缺失时自动补 linear
    简化规则后重建。CoolProp 6.4.3 相关已知问题:
      a) SO2 与 N2/H2/CO/H2O 无内置二元对, 创建混合物即抛
         "Could not match the binary pair ...";
      b) 二元对库为懒加载: 若在首次混合物创建之前调用 add_simple_mixing_rule,
         库被"钉死"为仅含新增对, 原有全部默认对丢失。
         因此补规则前必须先创建一次普通混合物触发内置库加载。"""
    try:
        return CPC.AbstractState('HEOS', fl)
    except ValueError:
        pass
    global _PAIR_RULES_DONE
    if not _PAIR_RULES_DONE:
        CPC.AbstractState('HEOS', 'Nitrogen&Water')   # 触发内置二元对库懒加载
        _PAIR_RULES_DONE = True
    names = fl.split('&')
    for a, b in itertools.combinations(names, 2):
        try:
            CPC.AbstractState('HEOS', a + '&' + b)
        except ValueError:
            CPC.apply_simple_mixing_rule(a, b, 'linear')
    return CPC.AbstractState('HEOS', fl)


# CoolProp 6.4.3 没有 CO / SO2 的纯组分输运性质数据(6.6.0 才补入),
# 用工程关联式补齐 (适用约 273~650K, 误差 ~±3%):
#   mu(T) = mu0 * (T/273.15)^1.5 * (273.15+S)/(T+S)   (Sutherland 公式)
#   kl(T) = k0 + dk * (T - 273.15)                     (线性近似)
_MU_KL_CORR = {
    'CarbonMonoxide': dict(mu0=1.657e-5, s=116.0, k0=0.02310, dk=7.08e-5),
    'SulfurDioxide':  dict(mu0=1.160e-5, s=260.0, k0=0.00854, dk=3.05e-5),
}


def _pure_mu_kl(name, T, P):
    """纯组分动力粘度/导热系数 (Pa.s, W/(m.K))"""
    if name not in _PURE_CACHE:
        AS = CPC.AbstractState('HEOS', name)
        AS.specify_phase(CPC.iphase_gas)
        _PURE_CACHE[name] = AS
    AS = _PURE_CACHE[name]
    AS.update(CPC.PT_INPUTS, P, T)
    try:
        return AS.viscosity(), AS.conductivity()
    except Exception:
        # 6.4.3 无该组分输运数据 -> 用关联式
        c = _MU_KL_CORR[name]
        T0 = 273.15
        mu = c['mu0'] * (T / T0) ** 1.5 * (T0 + c['s']) / (T + c['s'])
        kl = c['k0'] + c['dk'] * (T - T0)
        return mu, kl


def _mix_mu_kl(names, zs, T, P):
    """混合气输运性质回退算法（约 1 atm 常压燃气/烟气适用）:
    粘度用 Wilke 混合规则, 导热系数用 Wassiljewa-Mason-Saxena 规则
    (A 矩阵取 Wilke 形式)。CoolProp 6.4.3 的混合物输运模型不支持含
    CO/SO2 等组分的混合物("model is not available")时启用。"""
    mus, kls, Ms = [], [], []
    for n in names:
        mu, kl = _pure_mu_kl(n, T, P)
        mus.append(mu)
        kls.append(kl)
        Ms.append(CPC.PropsSI('M', n))                # kg/mol
    n = len(names)

    def a_matrix(vals):
        # A_ij = [1+(v_i/v_j)^0.5 (M_j/M_i)^0.25]^2 / sqrt(8(1+M_i/M_j))
        return [[(1.0 + (vals[i] / vals[j]) ** 0.5 * (Ms[j] / Ms[i]) ** 0.25) ** 2
                 / (8.0 * (1.0 + Ms[i] / Ms[j])) ** 0.5 for j in range(n)]
                for i in range(n)]

    a_mu = a_matrix(mus)
    a_kl = a_matrix(kls)
    mu = sum(zs[i] * mus[i] / sum(zs[j] * a_mu[i][j] for j in range(n))
             for i in range(n))
    kl = sum(zs[i] * kls[i] / sum(zs[j] * a_kl[i][j] for j in range(n))
             for i in range(n))
    return mu, kl


def fprop(ids, frac, T_C, P_kgcm2, side='h'):
    """返回 (WM kg/kmol, CP kJ/(kg.K), RO kg/m3, VIS Pa.s, CLMD W/(m.K), PR)
    side='h' 热侧 / 'c' 冷侧，校准因子见模块级 CALIB。"""
    T, P = T_C + 273.15, P_kgcm2 * KGF_CM2_TO_PA
    if not (50.0 <= T <= 2500.0):
        # 保护上游迭代: 温度飞出物理范围时给出可读的原因, 而非 CoolProp 内部报错
        raise ValueError(
            '物性计算温度越界: %.1f K (%.1f ℃)，迭代已发散，请检查输入参数'
            % (T, T_C))
    comp = [(FLUIDS[i], f / 100.0) for i, f in zip(ids, frac) if f > 0.0]
    fl = '&'.join(n for n, _ in comp)
    if fl not in _AS_CACHE:
        AS = _make_abstract_state(fl)
        # 显式指定气相: 烟气/空气在约 1 atm、全工况温度范围内均为过热气体。
        # CoolProp 6.4.3 混合物 PT 闪算的定相判定存在缺陷, 过热区也可能抛
        # "One stationary point (not good)" (CoolProp issue #2004);
        # 指定气相后直接解气相根, 6.4.3 与 6.6+ 均兼容。
        AS.specify_phase(CPC.iphase_gas)
        _AS_CACHE[fl] = AS
    AS = _AS_CACHE[fl]
    AS.set_mole_fractions([z for _, z in comp])
    AS.update(CPC.PT_INPUTS, P, T)
    f = CALIB[side]
    wm = AS.molar_mass() * 1000.0               # kg/kmol（原子量差 <0.1%，不修正）
    cp = AS.cpmass() / 1000.0 * f['cp']         # kJ/(kg·K)
    try:
        mu = AS.viscosity()                     # Pa·s
    except Exception:
        mu, _ = _mix_mu_kl([n for n, _ in comp], [z for _, z in comp], T, P)
    try:
        kl = AS.conductivity()                  # W/(m·K)
    except Exception:
        _, kl = _mix_mu_kl([n for n, _ in comp], [z for _, z in comp], T, P)
    mu *= f['mu']
    kl *= f['k']
    ro = P * wm / (8314.4621 * T) * f['rho']    # 理想气体密度（与原程序基准一致）
    pr = cp * 1000.0 * mu / kl                  # 无量纲
    return wm, cp, ro, mu, kl, pr

# ---------------- 换热子程序（与 HP.FOR 一一对应） ----------------

def ahfa(HF, DTA, SF, AL, VF, WM, VIS, RO, CLMD, PR, DO, ST, IB):
    """AHFA: 气侧换热系数（最小流通面积法, 错排管束关联式）"""
    HNAF = ((ST - DO) - 2. * HF * DTA / SF) / 1000. * AL / 1000. * IB
    GMAX = VF / 22.4 * WM / HNAF          # kg/(m2·h) 最大质量流密度
    WW = GMAX / RO / 3600.                # m/s
    RE = GMAX * DO / 3600. / 1000. / VIS
    HNU = 0.137 * RE ** 0.6338 * PR ** (1. / 3.)
    AHF = 1000. * CLMD / DO * HNU         # W/(m2·K)
    return GMAX, WW, RE, AHF


def ahfe(AHF, HF, DTA, SF, DO, FLMD):
    """AHFE: 环形翅片效率(悬臂肋近似) -> 有效换热系数 HFE 与单位管长总面积 AH"""
    ZZ = HF / 1000. * (2000. * AHF / FLMD / DTA) ** 0.5
    YITA = math.tanh(ZZ) / ZZ * 0.9 if ZZ > 1e-12 else 0.9
    DF = DO + 2. * HF
    AF = (2. * math.pi / 4. * ((DF / 1000.) ** 2 - (DO / 1000.) ** 2)
          + math.pi * DF / 1000. * DTA / 1000.) * 1000. / SF   # 翅片面积 m2/m
    AR = math.pi * DO / 1000. * (1. - DTA / SF)                # 光管裸露面积 m2/m
    AH = AF + AR
    HFE = AHF * (AR + YITA * AF) / AH
    return HFE, AH


def area(DO, HF, DTA, SF):
    """FUNCTION AREA: 单位管长总换热面积（校核计算用）"""
    DF = DO + 2. * HF
    AF = (2. * math.pi / 4. * ((DF / 1000.) ** 2 - (DO / 1000.) ** 2)
          + math.pi * DF / 1000. * DTA / 1000.) * 1000. / SF
    AR = math.pi * DO / 1000. * (1. - DTA / SF)
    return AF + AR

# ---------------- 主程序 ----------------
# 注: DETP(压降) 子程序在主流程内联展开, 因其需要 IM/N 等主流程局部变量

def compute(p):
    """核心计算入口: 接受 load_inb() 同构的参数字典 p, 返回 (rows, R)。
    rows: [(标签行, 数值), ...] 共 39 项, 与 OUT.DAT 同构; R: 关键结果字典。
    GUI (hp_gui.py) 直接调用本函数, 不经过文件。"""
    ids = p['ids']
    VFH, PFH = p['vfh'], p['pfh']
    TFJH, TFCH = p['tfjh'], p['tfch']
    ALH, HFH, DRTAFH, SFH = p['alh'], p['hfh'], p['drtafh'], p['sfh']
    DO, DI, ST, SL = p['do'], p['di'], p['st'], p['sl']
    XH = p['xh']
    VFC, PFC = p['vfc'], p['pfc']
    TFJC, TFCC = p['tfjc'], p['tfcc']
    ALC, HFC, DRTAFC, SFC = p['alc'], p['hfc'], p['drtafc'], p['sfc']
    XC = p['xc']
    WN, FLMD, TLMD = p['wn'], p['flmd'], p['tlmd']
    RYH, RYC, HZF, HLZ = p['ryh'], p['ryc'], p['hzf'], p['hlz']
    IBH, IMH, KT = p['ibh'], p['imh'], p['kt']

    BNO = '设计计算'

    # -------- label 25 段: 物性 + 热平衡 + 温度交叉（供外层重入） --------
    # 注: TFCC 为跨调用持久状态(对应 Fortran COMMON 变量), 显式传入/返回
    def stage25(tfcc):
        it30 = [0]            # 热平衡迭代次数(防发散)
        wmh, cph, roh, vish, clmdh, prh = fprop(ids, XH, (TFJH + TFCH) / 2., PFH, 'h')
        qh = VFH * wmh / 22.4 * cph * (TFJH - TFCH)      # 热侧放热量 kJ/h
        if qh <= 0.0:
            raise ValueError(
                '热侧放热量非正(qh=%.4g kJ/h): 热侧出口温度初值 TFCH=%.1f℃ '
                '已达到/超过进口温度 TFJH=%.1f℃，换热器在该校核工况下换热能力'
                '过剩或输入不匹配，请调整出口温度初值或改用设计计算(KT=0)'
                % (qh, TFCH, TFJH))
        qc = qh * 0.97                                    # 传热量(第一级散热损失)
        qc1 = qc * 0.97                                   # 冷侧应吸热量(第二级)
        while True:                                       # label 30: 热平衡迭代
            wmc, cpc_, roc, visc, clmdc, prc = fprop(ids, XC, (TFJC + tfcc) / 2., PFC, 'c')
            qc2 = VFC * wmc / 22.4 * cpc_ * (tfcc - TFJC)
            dq = (qc1 - qc2) / qc1
            if abs(dq) <= 0.01:
                break
            tfcc = tfcc + dq * (tfcc - TFJC)
            # 注: 迭代允许暂时越过 TFJH(原算法行为, 外层 label 800 温度交叉
            # 检查会逐步把 TFCH 拉回), 因此只设次数上限防失控, 不限上限区间;
            # 但低于 TFJC 属物理不可能状态(冷侧被加热后温度必高于其进口温度),
            # 一旦出现即说明热平衡无解, 立即给出可读原因
            if tfcc < TFJC:
                raise ValueError(
                    '热平衡无解: 冷侧出口温度被迭代至 %.1f℃(低于冷侧进口 '
                    '%.1f℃)。通常原因是: 热侧出口温度初值 TFCH=%.1f℃ 过高'
                    '(换热器换热能力过剩), 或两侧流量/温度不匹配。'
                    '校核计算请确认管束布置与工况匹配, 或改用设计计算(KT=0)'
                    % (tfcc, TFJC, TFCH))
            it30[0] += 1
            if it30[0] > 500:
                raise ValueError(
                    '热平衡迭代不收敛(超过 500 次): 冷侧出口温度 %.1f℃，'
                    '热侧可放热 %g kJ/h 与冷侧介质吸热能力不匹配，'
                    '请检查两侧流量、温度与组分输入' % (tfcc, qc1))
        return wmh, cph, roh, vish, clmdh, prh, qh, qc, qc1, \
               wmc, cpc_, roc, visc, clmdc, prc, tfcc

    # ============ label 25: 外层循环（校核计算调 TFCH 后整体重算） ============
    while True:
        (WMH, CPH, ROH, VISH, CLMDH, PRH, QH, QC, QC1,
         WMC, CPC_, ROC, VISC, CLMDC, PRC, TFCC) = stage25(TFCC)

        # -------- label 800: 温度交叉检查 --------
        if TFJH <= TFCC:
            TFCH = TFJH * 0.05 + TFCH * 0.95
            continue
        break

    # ============ label 801: 对数平均温压 ============
    DT1 = TFJH - TFCC
    DT2 = TFCH - TFJC
    DTMAX = max(DT1, DT2)
    DTMIN = min(DT1, DT2)
    DTM = (DTMAX - DTMIN) / math.log(DTMAX / DTMIN)

    # ============ 迎风面宽度 -> 横向管数 ============
    AEXH = VFH / 22.4 * WMH / ROH / 3600. / WN            # 迎风面面积 m2
    EH = AEXH / (ALH / 1000.)                             # 换热器宽度 m
    B = EH / (ST / 1000.)
    IB = int(B + 1.)
    if KT == 1:                                           # 校核: 用输入值
        IB = IBH
    EH1 = IB * 1. * ST / 1000.

    # ============ label 40: 换热系数/翅片效率/传热系数/排数 ============
    it40 = 0          # 校核面积迭代次数(防发散)
    while True:
        GMAXH, WWH, REH, AHFH = ahfa(HFH, DRTAFH, SFH, ALH, VFH, WMH, VISH,
                                     ROH, CLMDH, PRH, DO, ST, IB)
        GMAXC, WWC, REC, AHFC = ahfa(HFC, DRTAFC, SFC, ALC, VFC, WMC, VISC,
                                     ROC, CLMDC, PRC, DO, ST, IB)
        HFEH, AHH = ahfe(AHFH, HFH, DRTAFH, SFH, DO, FLMD)
        HFEC, AHC = ahfe(AHFC, HFC, DRTAFC, SFC, DO, FLMD)

        # 传热系数 (2026-09-23 按用户修正公式):
        #   UFH = 1 / ( 1/HFEH + 1/HFEC × ALH/ALC )
        # 即只取热侧/冷侧有效换热系数, 冷侧按换热段长度比折算到热侧基准;
        # 不再计入污垢/管壁/蒸发/冷凝各热阻项(原 HP.FOR 串联模型)。
        # 注意: 该公式与 HP.EXE 原程序不一致, OUT.DAT 对比列的传热系数偏差
        # 属预期差异。
        UFH = 1. / (1. / HFEH + 1. / HFEC * (ALH / ALC))

        AHHH = QC / UFH / DTM / 3.6                       # 所需换热面积 m2
        BN = AHHH / AHH / (ALH / 1000.)                   # 需要管数
        BM = BN / IB
        IM = int(BM + 1.)                                 # 排数(设计计算)

        if KT != 1:                                       # 设计计算 -> label 64
            break
        # -------- 校核计算: 实际面积与所需面积对比 --------
        AHH1 = area(DO, HFH, DRTAFH, SFH) * (IBH * IMH - int(IMH / 2)) * ALH / 1000.
        DAHH = (AHHH - AHH1) / AHH1
        if abs(DAHH) < 0.005:                             # 收敛 <0.5%
            IM = IMH
            BNO = '校核计算'
            break
        TFCH = TFCH - DAHH * (TFCH - TFJH) * 0.1          # 调热侧出口温度
        it40 += 1
        if it40 > 100 or not (TFJC < TFCH < TFJH):
            raise ValueError(
                '校核面积迭代不收敛: 所需换热面积与实际面积偏差 %.1f%%'
                '（实际 %.1f m² / 所需 %.1f m²），换热器与该工况严重不匹配。'
                '请检查管束布置(IBH/IMH)、翅片与节距参数，或改用设计计算(KT=0)'
                % (DAHH * 100., AHH1, AHHH))
        # goto 25: 整体重算
        while True:
            (WMH, CPH, ROH, VISH, CLMDH, PRH, QH, QC, QC1,
             WMC, CPC_, ROC, VISC, CLMDC, PRC, TFCC) = stage25(TFCC)
            if TFJH <= TFCC:
                TFCH = TFJH * 0.05 + TFCH * 0.95
                continue
            break
        DT1 = TFJH - TFCC
        DT2 = TFCH - TFJC
        DTMAX, DTMIN = max(DT1, DT2), min(DT1, DT2)
        DTM = (DTMAX - DTMIN) / math.log(DTMAX / DTMIN)

    # ============ label 64: 管束布置与压降 ============
    N = IB * IM - int(IM / 2)                             # 错排, 隔排少一根
    AHHH = AHH * (ALH / 1000.) * N                        # 实际换热面积

    SL1 = (SL ** 2 - (ST / 2.) ** 2) ** 0.5
    DPs = {}
    for K, HF, DTA, SF, AH_, GMAX, RY, TJ, TC, HFE_, AL, P, X, VIS, RO, side in [
        (-1, HFH, DRTAFH, SFH, AHH, GMAXH, RYH, TFJH, TFCH, HFEH, ALH, PFH, XH, VISH, ROH, 'h'),
        (+1, HFC, DRTAFC, SFC, AHC, GMAXC, RYC, TFJC, TFCC, HFEC, ALC, PFC, XC, VISC, ROC, 'c')]:
        TP = 0.5 * (TJ + TC)
        DF = DO + 2. * HF
        CNFV = ST * SL1 / 1000. ** 2 - math.pi / 4. * (DO / 1000.) ** 2 \
             - math.pi / 4. * ((DF / 1000.) ** 2 - (DO / 1000.) ** 2) \
               * DTA / 1000. * 1000. / SF
        DEV = 4. * CNFV / AH_
        REF = GMAX * DEV / 3600. / VIS
        F = 1.92 / REF ** 0.145
        HFE1 = 1. / (1. / HFE_ + RY)
        TWB = TP + K * QC / (HFE1 * AH_ * AL / 1000. * N) / 3.6
        _, _, _, VIS1, _, _ = fprop(ids, X, TWB, P, side)
        BL = SL1 * IM / 1000.                             # 换热器纵向长度 m
        DP = F * (GMAX / 3600) ** 2 * BL / 2. / 9.8 / DEV / RO \
           / (VIS / VIS1) ** 0.14 * (DEV / (ST / 1000.)) ** 0.4 \
           * (SL / ST) ** 0.6 * 9.8
        DPs[K] = DP
    DPH, DPC = DPs[-1], DPs[+1]

    R = dict(bno=BNO, kt=KT, tfch=TFCH, tfcc=TFCC, qh=QH, qc=QC, qc1=QC1,
             dtm=DTM, wwh=WWH, wwc=WWC, reh=REH, rec=REC, hfeh=HFEH, hfec=HFEC,
             ufh=UFH, ahhh=AHHH, ib=IB, im=IM, n=N, eh1=EH1, bl=BL,
             dph=DPH, dpc=DPC)

    # ============ 输出 OUT_PY.DAT（39 项, 与原格式同构） ============
    rows = [
        ('   1   热侧气体流量          Nm^3/h ', VFH),
        ('   2   热侧气体压力(绝压)   kgf/cm^2', PFH),
        ('   3   热侧气体进口温度        ℃   ', TFJH),
        ('   4   热侧气体出口温度        ℃   ', TFCH),
        ('   5   冷侧气体流量          Nm^3/h ', VFC),
        ('   6   冷侧气体压力(绝压)   kgf/cm^2', PFC),
        ('   7   冷侧气体进口温度        ℃   ', TFJC),
        ('   8   冷侧气体出口温度        ℃   ', TFCC),
        ('   9   光管外径                mm   ', DO),
        ('  10   光管内径                mm   ', DI),
        ('  11   横向节距                mm   ', ST),
        ('  12   纵向节距                mm   ', SL1),
        ('  13   热侧换热段长度          mm   ', ALH),
        ('  14   热侧翅片高度            mm   ', HFH),
        ('  15   热侧翅片厚度            mm   ', DRTAFH),
        ('  16   热侧翅片节距            mm   ', SFH),
        ('  17   冷侧换热段长度          mm   ', ALC),
        ('  18   冷侧翅片高度            mm   ', HFC),
        ('  19   冷侧翅片厚度            mm   ', DRTAFC),
        ('  20   冷侧翅片节距            mm   ', SFC),
        ('  21   热侧气体放热量         kJ/h  ', QH),
        ('  22   传热量                 kJ/h  ', QC),
        ('  23   冷侧气体吸热量         kJ/h  ', QC1),
        ('  24   平均温压                ℃   ', DTM),
        ('  25   热侧气体流速            m/s  ', WWH),
        ('  26   冷侧气体流速            m/s  ', WWC),
        ('  27   热侧雷诺数                   ', REH),
        ('  28   冷侧雷诺数                   ', REC),
        ('  29   热侧换热系数          w/m^2℃', HFEH),
        ('  30   冷侧换热系数          w/m^2℃', HFEC),
        ('  31   传热系数              w/m^2℃', UFH),
        ('  32   热侧换热面积            m^2  ', AHHH),
        ('  33   迎风面换热管根数        根   ', IB),
        ('  34   换热管排数              排   ', IM),
        ('  35   换热管根数              根   ', N),
        ('  36   换热器横向宽度          mm   ', EH1),
        ('  37   换热器纵向长度          mm   ', BL),
        ('  38   热侧气体压降            Pa   ', DPH),
        ('  39   冷侧气体压降            Pa   ', DPC),
    ]
    return rows, R


def write_out(rows, out, bno):
    """按原 HP.EXE 输出格式写出 OUT_PY.DAT"""
    from decimal import Decimal, ROUND_HALF_UP

    def fmt(v, nd):
        q = Decimal(1).scaleb(-nd)
        return str(Decimal(repr(float(v))).quantize(q, rounding=ROUND_HALF_UP))

    with open(out, 'w', encoding='gbk', errors='replace') as f:
        f.write(' %s              热管式气-气换热器设计计算\n' % bno)
        f.write(' --------------------------------------------------\n')
        f.write(' 序号        名称             单位         数值\n')
        f.write(' --------------------------------------------------\n')
        for label, v in rows:
            if isinstance(v, int):
                f.write(' %s%10d\n' % (label, v))
            else:
                f.write(' %s%12s\n' % (label, fmt(v, 1).rjust(12)))


def main(inb='INB.DAT', out='OUT_PY.DAT', verbose=True):
    p = load_inb(inb)
    rows, R = compute(p)
    write_out(rows, out, R['bno'])
    if verbose:
        print('已生成:', out, '(计算类型: %s, KT=%d)' % (R['bno'], R['kt']))

        # ============ 与原程序 OUT.DAT 逐项对比（如存在） ============
        ref = os.path.join(os.path.dirname(os.path.abspath(inb)) or '.', 'OUT.DAT')
        if os.path.exists(ref):
            vals = {}
            with open(ref, 'r', encoding='gbk', errors='replace') as f:
                for line in f:
                    t = line.split()
                    if len(t) >= 3 and t[0].isdigit():
                        try:
                            vals[int(t[0])] = float(t[-1])
                        except ValueError:
                            pass
            print('\n%-4s %-22s %14s %14s %9s' % ('序号', '项目', 'HP.EXE', 'Python', '偏差%'))
            for label, v in rows:
                no = int(label.strip().split()[0])
                name = label.split()[1]
                if no in vals and vals[no] != 0:
                    py = float(v)
                    dev = (py - vals[no]) / vals[no] * 100.
                    mark = '' if abs(dev) < 1.0 else ('  <<' if abs(dev) < 5.0 else '  !!')
                    print('%-4d %-22s %14.2f %14.2f %+8.2f%%%s'
                          % (no, name, vals[no], py, dev, mark))
    return R


if __name__ == '__main__':
    _HERE = os.path.dirname(os.path.abspath(__file__))
    inb = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_HERE, 'INB.DAT')
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(_HERE, 'OUT_PY.DAT')
    main(inb, out)
    sys.stdout.flush()
    os._exit(0)   # 规避 CoolProp8+Py3.13 退出阶段崩溃, 不影响结果
