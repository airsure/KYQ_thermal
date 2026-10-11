# -*- coding: utf-8 -*-
"""
热管式气-气换热器热力计算 —— PyQt5 图形界面
=============================================
- 输入参数全部在界面中填写（启动时自动读取 INB.DAT 作为默认值, 也可手动导入）
- 点击「开始计算」在后台线程调用 hp_thermal.compute()（不卡界面）
- 结果以表格展示; 工作目录存在 OUT.DAT 时自动附加 HP.EXE 参考值与偏差列
- 结果支持导出 Excel(.xlsx, 含「输入参数」+「计算结果」双工作表) 与 CSV

运行: python hp_gui.py
依赖: venv C:/Users/.../.workbuddy/binaries/python/envs/default
      (PyQt5 + CoolProp + openpyxl, 均已安装)
"""
import os
import sys
import csv
import traceback

from PyQt5.QtCore import Qt, QThread, QRegExp, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QBrush, QRegExpValidator
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QLineEdit,
    QGroupBox, QFormLayout, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QMessageBox, QFileDialog,
    QRadioButton, QButtonGroup, QSplitter, QHeaderView, QScrollArea,
    QAbstractItemView, QStatusBar)

import hp_thermal
from hp_thermal import compute, load_inb

HERE = os.path.dirname(os.path.abspath(__file__))

# OUT.DAT 中出现的全部单位, 用于把输出标签行拆成 (序号, 名称, 单位)
UNIT_SET = {'Nm^3/h', 'kgf/cm^2', '℃', 'mm', 'kJ/h', 'm/s',
            'w/m^2℃', 'm^2', '根', '排', 'Pa'}

# 输入框校验: 只允许数字(整数/浮点)。允许输入过程的中间状态(空串/末尾小数点),
# 提交计算时再由 collect_params() 统一校验并给出中文提示。
RE_FLOAT = QRegExp(r'[0-9]*\.?[0-9]*')
RE_INT = QRegExp(r'[0-9]*')

# ---------------- 输入字段定义 ----------------
# (key, 标签, 单位, 小数位数)  —— 组分编号/IBH/IMH 为整数另行处理
SPEC = [
    ('热侧气体（烟气）', [
        ('vfh',   '气体流量',        'Nm^3/h',    1),
        ('pfh',   '气体压力(绝压)',  'kgf/cm^2',  3),
        ('tfjh',  '进口温度',        '℃',         1),
        ('tfch',  '出口温度(初值)',  '℃',         1)]),
    ('冷侧气体（空气）', [
        ('vfc',   '气体流量',        'Nm^3/h',    1),
        ('pfc',   '气体压力(绝压)',  'kgf/cm^2',  3),
        ('tfjc',  '进口温度',        '℃',         1),
        ('tfcc',  '出口温度(初值)',  '℃',         1)]),
    ('换热管参数', [
        ('do',    '光管外径',        'mm',        1),
        ('di',    '光管内径',        'mm',        1),
        ('st',    '横向节距',        'mm',        1),
        ('sl',    '斜向节距',        'mm',        1)]),
    ('热侧翅片', [
        ('alh',    '换热段长度',     'mm',        1),
        ('hfh',    '翅片高度',       'mm',        1),
        ('drtafh', '翅片厚度',       'mm',        2),
        ('sfh',    '翅片节距',       'mm',        1)]),
    ('冷侧翅片', [
        ('alc',    '换热段长度',     'mm',        1),
        ('hfc',    '翅片高度',       'mm',        1),
        ('drtafc', '翅片厚度',       'mm',        2),
        ('sfc',    '翅片节距',       'mm',        1)]),
    ('迎风面流速、翅片/管壁材料与污垢', [
        ('wn',   '迎风面设计流速',    'm/s',       2),
        ('flmd', '翅片导热系数',      'W/(m·K)',   1),
        ('tlmd', '管壁导热系数',      'W/(m·K)',   1),
        ('ryh',  '热侧污垢热阻',      'm^2·K/W',   5),
        ('ryc',  '冷侧污垢热阻',      'm^2·K/W',   5),
        ('hzf',  '蒸发换热系数',      'W/(m^2·K)', 1),
        ('hlz',  '冷凝换热系数',      'W/(m^2·K)', 1)]),
]

# 组分编号说明（与 hp_thermal.FLUIDS 一致）
ID_HINT = ('01=N2  02=O2  03=H2  04=CO  05=CO2  08=SO2  '
           '09=H2S  12=H2O  13=CH4')


def split_label(label):
    """把输出标签行 '   1   热侧气体流量          Nm^3/h ' 拆成 (序号, 名称, 单位)"""
    t = label.split()
    no = int(t[0])
    if t[-1] in UNIT_SET:
        return no, ''.join(t[1:-1]), t[-1]
    return no, ''.join(t[1:]), '—'


class CalcThread(QThread):
    """后台计算线程"""
    done = pyqtSignal(object, list)     # (R, rows)
    fail = pyqtSignal(str)              # 错误堆栈

    def __init__(self, params, parent=None):
        super().__init__(parent)
        self.params = params

    def run(self):
        try:
            rows, R = compute(self.params)
            self.done.emit(R, rows)
        except Exception:
            self.fail.emit(traceback.format_exc())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('热管式气-气换热器热力计算程序')
        self.resize(1180, 720)
        self.R = None
        self.rows = None
        self.params = None
        self.thread = None
        self.dspins = {}        # key -> QLineEdit (数值文本框)
        self.id_spins = []      # 7 个组分编号 (QLineEdit)
        self.xh_spins = []      # 热侧组分%
        self.xc_spins = []      # 冷侧组分%
        # 各浮点字段的小数位数 (仅用于显示格式化), 来自 SPEC
        self._dec = {key: dec for _, fields in SPEC
                     for key, _, _, dec in fields}
        self._build_ui()

        # 启动时自动读取 INB.DAT 作为默认值
        inb = os.path.join(HERE, 'INB.DAT')
        if os.path.exists(inb):
            try:
                self.set_params(load_inb(inb))
                self.statusBar().showMessage('已从 INB.DAT 载入默认参数', 5000)
            except Exception as e:
                self.statusBar().showMessage('INB.DAT 载入失败: %s' % e, 5000)

    # ---------------- 输入框工厂 ----------------
    def _float_edit(self, width=None):
        """浮点数文本输入框"""
        ed = QLineEdit()
        ed.setValidator(QRegExpValidator(RE_FLOAT, ed))
        ed.setAlignment(Qt.AlignRight)
        if width:
            ed.setFixedWidth(width)
        return ed

    def _int_edit(self, width=None):
        """整数文本输入框"""
        ed = QLineEdit()
        ed.setValidator(QRegExpValidator(RE_INT, ed))
        ed.setAlignment(Qt.AlignRight)
        if width:
            ed.setFixedWidth(width)
        return ed

    @staticmethod
    def _ed_val(ed, name=''):
        """读取文本框数值, 非法/为空时抛出带字段名的中文异常"""
        t = ed.text().strip()
        try:
            return float(t)
        except ValueError:
            raise ValueError('输入项%s不是有效数字: %r, 请检查'
                             % (('「%s」' % name) if name else '', t or '(空)'))

    # ---------------- UI 构建 ----------------
    def _build_ui(self):
        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        # ============ 左侧: 参数输入 ============
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 8, 8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(0, 0, 4, 0)
        pv.setSpacing(8)

        # --- 组分编号 ---
        gb_id = QGroupBox('气体组分编号（热侧/冷侧共用, 7 个）')
        form_id = QFormLayout(gb_id)
        row = QHBoxLayout()
        row.setSpacing(4)
        for i in range(7):
            ed = self._int_edit(width=44)
            self.id_spins.append(ed)
            row.addWidget(ed)
        hint = QLabel(ID_HINT)
        hint.setStyleSheet('color:#666; font-size:11px;')
        hint.setWordWrap(True)
        form_id.addRow(row)
        form_id.addRow(hint)
        pv.addWidget(gb_id)

        # --- 热侧/冷侧气体 + 各参数组 ---
        for title, fields in SPEC:
            gb = QGroupBox(title)
            form = QFormLayout(gb)
            form.setLabelAlignment(Qt.AlignRight)
            if '组分' in title or False:
                pass
            # 组分%行挂在气体组之后单独建组
            for key, name, unit, dec in fields:
                ed = self._float_edit(width=110)
                self.dspins[key] = ed
                form.addRow('%s  [%s]' % (name, unit), ed)
            pv.addWidget(gb)

        # --- 组分体积% (热/冷两行, 标签列 + 7 个输入列) ---
        gb_x = QGroupBox('气体组分体积分数（%, 与组分编号顺序对应）')
        gx = QGridLayout(gb_x)
        gx.setHorizontalSpacing(4)
        for col in range(7):
            head = QLabel('No.%d' % (col + 1))
            head.setAlignment(Qt.AlignCenter)
            head.setStyleSheet('color:#666;')
            gx.addWidget(head, 0, col + 1)
        for r, (tag, lst) in enumerate([('热侧', self.xh_spins),
                                        ('冷侧', self.xc_spins)], start=1):
            lab = QLabel(tag)
            lab.setAlignment(Qt.AlignCenter)
            gx.addWidget(lab, r, 0)
            for col in range(7):
                ed = self._float_edit(width=52)
                ed.setToolTip('第 %d 个组分的体积分数' % (col + 1))
                lst.append(ed)
                gx.addWidget(ed, r, col + 1)
        pv.addWidget(gb_x)

        # --- 计算类型 ---
        gb_kt = QGroupBox('计算类型')
        hk = QHBoxLayout(gb_kt)
        self.rb_design = QRadioButton('设计计算（KT=0, 自动排管）')
        self.rb_check = QRadioButton('校核计算（KT=1, 校验已布置管束）')
        self.rb_design.setChecked(True)
        bg = QButtonGroup(gb_kt)
        bg.addButton(self.rb_design)
        bg.addButton(self.rb_check)
        self.rb_design.toggled.connect(self._kt_toggled)
        hk.addWidget(self.rb_design)
        hk.addWidget(self.rb_check)
        pv.addWidget(gb_kt)

        # --- 校核管束 (KT=1 时可用) ---
        gb_ib = QGroupBox('校核计算管束布置（仅 KT=1 时有效）')
        form_ib = QFormLayout(gb_ib)
        self.ed_ibh = self._int_edit(width=110)
        self.ed_imh = self._int_edit(width=110)
        form_ib.addRow('迎风面换热管根数 IBH [根]', self.ed_ibh)
        form_ib.addRow('换热管排数 IMH [排]', self.ed_imh)
        self.gb_ib = gb_ib
        pv.addWidget(gb_ib)
        pv.addStretch(1)

        scroll.setWidget(panel)
        lv.addWidget(scroll)
        splitter.addWidget(left)

        # ============ 右侧: 结果表格 ============
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 8, 8, 8)

        btns = QHBoxLayout()
        self.btn_calc = QPushButton('开始计算')
        self.btn_calc.setMinimumHeight(32)
        self.btn_calc.setStyleSheet(
            'QPushButton{background:#1e6bb8; color:white; font-weight:bold;'
            'padding:4px 18px; border-radius:4px;}'
            'QPushButton:hover{background:#175a9c;}'
            'QPushButton:disabled{background:#9db8d2;}')
        self.btn_calc.clicked.connect(self.start_calc)
        self.btn_excel = QPushButton('导出 Excel')
        self.btn_csv = QPushButton('导出 CSV')
        self.btn_import = QPushButton('从 INB.DAT 导入')
        self.btn_excel.clicked.connect(self.export_excel)
        self.btn_csv.clicked.connect(self.export_csv)
        self.btn_import.clicked.connect(self.import_inb)
        for b in (self.btn_excel, self.btn_csv):
            b.setEnabled(False)
        btns.addWidget(self.btn_calc)
        btns.addWidget(self.btn_excel)
        btns.addWidget(self.btn_csv)
        btns.addStretch(1)
        btns.addWidget(self.btn_import)
        rv.addLayout(btns)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['序号', '项目', '单位', '数值'])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        f = self.table.font()
        f.setPointSize(10)
        self.table.setFont(f)
        rv.addWidget(self.table)

        #tip = QLabel('提示: 「HP.EXE 参考值 / 偏差%」两列仅当当前输入与 INB.DAT 基准工况'
        #             '完全一致时显示（OUT.DAT 是该工况的结果）; 修改任意参数后对比列自动隐藏。'
        #             'Excel 导出含输入参数与计算结果双工作表。')
        #tip.setStyleSheet('color:#888; font-size:11px;')
        #tip.setWordWrap(True)
        #rv.addWidget(tip)
        splitter.addWidget(right)
        splitter.setSizes([430, 750])

        self.statusBar().showMessage('就绪。填写参数后点击「开始计算」。')

    # ---------------- 参数 <-> 界面 ----------------
    def _kt_toggled(self):
        self.gb_ib.setEnabled(self.rb_check.isChecked())

    def collect_params(self):
        """从界面收集参数; 文本框内容非法时抛 ValueError(中文提示)"""
        p = {}
        p['ids'] = [int(self._ed_val(ed, '组分编号 No.%d' % (i + 1)))
                    for i, ed in enumerate(self.id_spins)]
        for k, ed in self.dspins.items():
            p[k] = self._ed_val(ed, self._field_info(k)[0])
        p['xh'] = [self._ed_val(ed, '热侧组分 No.%d' % (i + 1))
                   for i, ed in enumerate(self.xh_spins)]
        p['xc'] = [self._ed_val(ed, '冷侧组分 No.%d' % (i + 1))
                   for i, ed in enumerate(self.xc_spins)]
        p['kt'] = 1 if self.rb_check.isChecked() else 0
        p['ibh'] = int(self._ed_val(self.ed_ibh, 'IBH 根数'))
        p['imh'] = int(self._ed_val(self.ed_imh, 'IMH 排数'))
        return p

    def set_params(self, p):
        for i, ed in enumerate(self.id_spins):
            ed.setText('%d' % int(p['ids'][i]))
        for k, ed in self.dspins.items():
            ed.setText('%.*f' % (self._dec.get(k, 2), float(p.get(k, 0.0))))
        for i, ed in enumerate(self.xh_spins):
            ed.setText('%.2f' % float(p['xh'][i]))
        for i, ed in enumerate(self.xc_spins):
            ed.setText('%.2f' % float(p['xc'][i]))
        if int(p.get('kt', 0)) == 1:
            self.rb_check.setChecked(True)
        else:
            self.rb_design.setChecked(True)
        self.ed_ibh.setText('%d' % int(p.get('ibh', 1)))
        self.ed_imh.setText('%d' % int(p.get('imh', 1)))
        self.gb_ib.setEnabled(self.rb_check.isChecked())

    # ---------------- 动作 ----------------
    def import_inb(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '选择 INB.DAT 输入文件', HERE, '输入文件 (*.DAT *.dat);;所有文件 (*)')
        if not path:
            return
        try:
            self.set_params(load_inb(path))
            self.statusBar().showMessage('已导入: %s' % path, 5000)
        except Exception as e:
            QMessageBox.critical(self, '导入失败',
                                 '文件解析失败:\n%s\n\n%s' % (path, e))

    def start_calc(self):
        if self.thread is not None and self.thread.isRunning():
            return
        try:
            self.params = self.collect_params()
        except ValueError as e:
            QMessageBox.warning(self, '输入有误', str(e))
            return
        # 基础校验
        if sum(self.params['xh']) <= 0 or sum(self.params['xc']) <= 0:
            QMessageBox.warning(self, '参数错误', '热侧/冷侧组分体积分数之和必须大于 0。')
            return
        if self.params['tfjh'] <= self.params['tfjc']:
            QMessageBox.warning(self, '参数错误',
                                '热侧进口温度(%g℃)应高于冷侧进口温度(%g℃)。'
                                % (self.params['tfjh'], self.params['tfjc']))
            return
        self.btn_calc.setEnabled(False)
        self.btn_calc.setText('计算中…')
        self.statusBar().showMessage('正在迭代计算（热平衡 ±1% / 校核面积 ±0.5%）…')
        self.thread = CalcThread(self.params, self)
        self.thread.done.connect(self.on_done)
        self.thread.fail.connect(self.on_fail)
        self.thread.start()

    def on_done(self, R, rows):
        self.btn_calc.setEnabled(True)
        self.btn_calc.setText('开始计算')
        self.R, self.rows = R, rows
        self.fill_table(R, rows)
        self.btn_excel.setEnabled(True)
        self.btn_csv.setEnabled(True)
        self.statusBar().showMessage(
            '计算完成: %s (KT=%d) | 换热管 %d 根 (%d×%d) | 热侧出口 %.1f℃ | '
            '冷侧出口 %.1f℃ | 传热系数 %.2f W/(m^2·℃)%s'
            % (R['bno'], R['kt'], R['n'], R['ib'], R['im'],
               R['tfch'], R['tfcc'], R['ufh'],
               '' if self._show_ref
               else ''))#| 输入与 OUT.DAT 基准工况(INB.DAT)不一致, 对比列已隐藏

    def on_fail(self, stack):
        self.btn_calc.setEnabled(True)
        self.btn_calc.setText('开始计算')
        self.statusBar().showMessage('计算失败', 5000)
        QMessageBox.critical(self, '计算失败', stack)

    # ---------------- 结果表 ----------------
    def _load_ref(self):
        """读 OUT.DAT 原程序参考值 (no -> float), 不存在返回 None"""
        ref_path = os.path.join(HERE, 'OUT.DAT')
        if not os.path.exists(ref_path):
            return None
        vals = {}
        try:
            with open(ref_path, 'r', encoding='gbk', errors='replace') as fh:
                for line in fh:
                    t = line.split()
                    if len(t) >= 3 and t[0].isdigit():
                        try:
                            vals[int(t[0])] = float(t[-1])
                        except ValueError:
                            pass
        except OSError:
            return None
        return vals or None

    def _result_rows(self):
        """整理成 [(no, name, unit, value, ref, dev%), ...]"""
        ref = self._load_ref() if getattr(self, '_show_ref', False) else None
        out = []
        for label, v in self.rows:
            no, name, unit = split_label(label)
            dev = None
            rv = None
            if ref and no in ref and ref[no] != 0:
                rv = ref[no]
                dev = (float(v) - rv) / rv * 100.0
            out.append((no, name, unit, v, rv, dev))
        return out

    def _ref_case_match(self):
        """当前界面输入是否与 OUT.DAT 对应的基准工况 (INB.DAT) 一致。
        不一致时 HP.EXE 对比列无意义, 应隐藏。"""
        try:
            base = load_inb(os.path.join(HERE, 'INB.DAT'))
        except Exception:
            return False
        cur = self.collect_params()
        for k, v in base.items():
            b = cur.get(k)
            if isinstance(v, list):
                if [round(x, 6) for x in v] != [round(x, 6) for x in (b or [])]:
                    return False
            elif abs(float(v) - float(b)) > 1e-6 * max(1.0, abs(float(v))):
                return False
        return True

    def fill_table(self, R, rows):
        ref = self._load_ref() if self._ref_case_match() else None
        self._show_ref = ref is not None
        cols = ['序号', '项目', '单位', '数值']
        if ref:
            cols += ['HP.EXE 参考值', '偏差%']
        self.table.clear()
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.setRowCount(len(rows))
        for i, (label, v) in enumerate(rows):
            no, name, unit = split_label(label)
            val_s = ('%d' % v) if isinstance(v, int) else ('%.2f' % float(v))
            for col, s in enumerate([str(no), name, unit, val_s]):
                it = QTableWidgetItem(s)
                if col in (0, 2, 3):
                    it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(i, col, it)
            if ref:
                no2, _, _ = split_label(label)
                rv = ref.get(no2)
                if rv:
                    dev = (float(v) - rv) / rv * 100.0
                    c1 = QTableWidgetItem('%.2f' % rv)
                    c1.setTextAlignment(Qt.AlignCenter)
                    c2 = QTableWidgetItem('%+.2f%%' % dev)
                    c2.setTextAlignment(Qt.AlignCenter)
                    if abs(dev) >= 5.0:
                        c2.setForeground(QBrush(QColor('#c62828')))
                    elif abs(dev) >= 1.0:
                        c2.setForeground(QBrush(QColor('#e65100')))
                    else:
                        c2.setForeground(QBrush(QColor('#2e7d32')))
                    self.table.setItem(i, 4, c1)
                    self.table.setItem(i, 5, c2)

    # ---------------- 导出 ----------------
    def export_excel(self):
        if not self.rows:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, '导出 Excel', os.path.join(HERE, '计算结果.xlsx'),
            'Excel 工作簿 (*.xlsx)')
        if not path:
            return
        try:
            import openpyxl
            from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
            wb = openpyxl.Workbook()

            thin = Side(style='thin', color='999999')
            border = Border(left=thin, right=thin, top=thin, bottom=thin)
            head_fill = PatternFill('solid', fgColor='1F6FB8')
            head_font = Font(bold=True, color='FFFFFF')
            center = Alignment(horizontal='center', vertical='center')

            # ---- Sheet1: 计算结果 ----
            ws = wb.active
            ws.title = '计算结果'
            ws['A1'] = '%s —— 热管式气-气换热器%s' % (
                os.path.basename(path), self.R['bno'])
            ws['A1'].font = Font(bold=True, size=13)
            ws.merge_cells('A1:F1')
            headers = ['序号', '项目', '单位', '数值']
            has_ref = getattr(self, '_show_ref', False) and self._load_ref() is not None
            if has_ref:
                headers += ['HP.EXE 参考值', '偏差%']
            for c, h in enumerate(headers, 1):
                cell = ws.cell(row=3, column=c, value=h)
                cell.font = head_font
                cell.fill = head_fill
                cell.alignment = center
                cell.border = border
            for r, (no, name, unit, v, rv, dev) in enumerate(self._result_rows(), 4):
                val = v if isinstance(v, int) else round(float(v), 2)
                row_vals = [no, name, unit, val]
                if has_ref:
                    row_vals += [round(rv, 2) if rv is not None else '',
                                 round(dev, 2) if dev is not None else '']
                for c, val2 in enumerate(row_vals, 1):
                    cell = ws.cell(row=r, column=c, value=val2)
                    cell.border = border
                    if c != 2:
                        cell.alignment = center
            for col, w in zip('ABCDEF', (8, 30, 12, 14, 16, 10)):
                ws.column_dimensions[col].width = w

            # ---- Sheet2: 输入参数 ----
            ws2 = wb.create_sheet('输入参数')
            ws2['A1'] = '输入参数'
            ws2['A1'].font = Font(bold=True, size=13)
            for c, h in enumerate(['参数', '数值', '单位'], 1):
                cell = ws2.cell(row=3, column=c, value=h)
                cell.font = head_font
                cell.fill = head_fill
                cell.alignment = center
                cell.border = border
            r = 4
            p = self.params if self.params else self.collect_params()
            sec_font = Font(bold=True)
            def wrow(label, val, unit):
                nonlocal r
                ws2.cell(row=r, column=1, value=label).border = border
                c2 = ws2.cell(row=r, column=2, value=val)
                c2.border = border
                c2.alignment = center
                c3 = ws2.cell(row=r, column=3, value=unit)
                c3.border = border
                c3.alignment = center
                r += 1
            def section(title):
                nonlocal r
                c = ws2.cell(row=r, column=1, value=title)
                c.font = sec_font
                r += 1
            section('气体组分编号（7 个）')
            wrow('组分编号', ' '.join(str(x) for x in p['ids']), '—')
            for tag, keyp, keys in (
                    ('热侧', 'xh', ('vfh', 'pfh', 'tfjh', 'tfch')),
                    ('冷侧', 'xc', ('vfc', 'pfc', 'tfjc', 'tfcc'))):
                section('%s气体' % tag)
                wrow('%s组分体积分数' % tag,
                     ' '.join('%.2f' % x for x in p[keyp]), '%')
                for k in keys:
                    name, unit, _ = self._field_info(k)
                    wrow('%s - %s' % (tag, name), round(p[k], 3), unit)
            for title, fields in SPEC:
                if title.startswith('热侧气体') or title.startswith('冷侧气体'):
                    continue
                section(title)
                for key, name, unit, _ in fields:
                    wrow(name, round(p[key], 4), unit)
            section('计算类型与管束')
            wrow('计算类型', '校核计算 (KT=1)' if p['kt'] == 1 else '设计计算 (KT=0)', '—')
            wrow('迎风面换热管根数 IBH', p['ibh'], '根')
            wrow('换热管排数 IMH', p['imh'], '排')
            for col, w in zip('ABC', (32, 26, 14)):
                ws2.column_dimensions[col].width = w

            wb.save(path)
            self.statusBar().showMessage('已导出 Excel: %s' % path, 8000)
        except Exception:
            QMessageBox.critical(self, '导出失败', traceback.format_exc())

    def _field_info(self, key):
        """查字段 (名称, 单位, 小数位)"""
        for title, fields in SPEC:
            for f in fields:
                if f[0] == key:
                    return f[1], f[2], f[3]
        return key, '—', 2

    def export_csv(self):
        if not self.rows:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, '导出 CSV', os.path.join(HERE, '计算结果.csv'), 'CSV (*.csv)')
        if not path:
            return
        try:
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow(['序号', '项目', '单位', '数值', 'HP.EXE参考值', '偏差%'])
                for no, name, unit, v, rv, dev in self._result_rows():
                    val = v if isinstance(v, int) else round(float(v), 2)
                    w.writerow([no, name, unit, val,
                                '' if rv is None else round(rv, 2),
                                '' if dev is None else '%.2f%%' % dev])
            self.statusBar().showMessage('已导出 CSV: %s' % path, 8000)
        except Exception:
            QMessageBox.critical(self, '导出失败', traceback.format_exc())

    def closeEvent(self, event):
        if self.thread is not None and self.thread.isRunning():
            self.thread.wait(2000)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    win = MainWindow()
    win.show()
    ret = app.exec_()
    os._exit(ret)   # 规避 CoolProp8+Py3.13 解释器退出阶段崩溃, 不影响功能


if __name__ == '__main__':
    main()
