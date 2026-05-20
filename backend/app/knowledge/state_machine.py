"""
行业状态机（Industry State Machine）

参考 RAGFlow 状态机设计，定义产业阶段跃迁逻辑：
  - 防止 Agent 把"送样"误判为"量产"等早期/晚期混淆
  - 状态转换携带时序字段（valid_from / valid_to）
  - 支持从文本关键词推断当前阶段

状态层级：
  LAB        实验室阶段（理论/基础研究）
  RND        研发阶段（原理验证/工艺开发）
  PILOT      中试阶段（小批量/客户验证）
  EARLY_ADOPTION 早期采用（头部客户/示范项目）
  GROWTH     成长期（规模量产/市场份额扩张）
  MATURITY   成熟期（行业标准/利润率稳定）
  DECLINE    衰退期（技术迭代替代/需求下降）
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional


# ── 状态枚举 ──────────────────────────────────────────────────────────────

class IndustryState(str, Enum):
    LAB            = "LAB"            # 实验室
    RND            = "RND"            # 研发
    PILOT          = "PILOT"          # 中试
    EARLY_ADOPTION = "EARLY_ADOPTION"  # 早期采用
    GROWTH         = "GROWTH"         # 成长期
    MATURITY       = "MATURITY"       # 成熟期
    DECLINE        = "DECLINE"        # 衰退期


# ── 有效转换矩阵 ─────────────────────────────────────────────────────────

# 单向允许转换（不允许跳级或倒退太多）
VALID_TRANSITIONS: dict[IndustryState, set[IndustryState]] = {
    IndustryState.LAB:            {IndustryState.RND, IndustryState.PILOT},
    IndustryState.RND:            {IndustryState.LAB, IndustryState.PILOT, IndustryState.EARLY_ADOPTION},
    IndustryState.PILOT:          {IndustryState.RND, IndustryState.EARLY_ADOPTION, IndustryState.GROWTH},
    IndustryState.EARLY_ADOPTION: {IndustryState.PILOT, IndustryState.GROWTH, IndustryState.MATURITY},
    IndustryState.GROWTH:         {IndustryState.EARLY_ADOPTION, IndustryState.MATURITY, IndustryState.DECLINE},
    IndustryState.MATURITY:       {IndustryState.GROWTH, IndustryState.DECLINE},
    IndustryState.DECLINE:         {IndustryState.GROWTH, IndustryState.MATURITY},  # 可逆：技术升级再成长
}


# ── 状态关键词 ─────────────────────────────────────────────────────────────

STATE_KEYWORDS: dict[IndustryState, list[str]] = {
    IndustryState.LAB: [
        "理论研究", "基础研究", "概念验证", "原理探索", "论文阶段",
        "科学问题", "机理研究", "实验室研究", "可行性论证",
        "尚无商业化", "无商业化", "商业化前景不明", "仅停留在理论",
        "学术研究", "学术论文", "基础科学",
    ],
    IndustryState.RND: [
        "研发中", "研发阶段", "产品开发", "工艺研发", "技术攻关",
        "样机研制", "性能测试", "可靠性验证", "在研", "研制",
        "小试", "工艺定型", "配方研发", "持续研发",
        "研发早期", "早期研发", "研发初期",
    ],
    IndustryState.PILOT: [
        "中试", "小批量", "试产", "试制", "试生产", "送样验证",
        "客户认证", "产品定型", "工艺验证", "工程验证", "PVT",
        "导入量产", "转产", "可靠性认证", "样品阶段", "送样",
        "客户验证", "认证中", "产品认证", "小批量供货",
    ],
    IndustryState.EARLY_ADOPTION: [
        "头部客户", "重点客户", "首批交付", "商业化初期", "早期采用",
        "战略合作", "独家供货", "小批量量产", "初始产能",
        "客户拓展", "商业化验证", "定点", "取得订单", "开始供货",
    ],
    IndustryState.GROWTH: [
        "规模量产", "大规模量产", "产能释放", "规模交付", "订单饱满",
        "产能紧张", "满产满销", "营收增长", "规模效应", "市场份额提升",
        "进入头部客户", "批量商业化", "规模扩张",
    ],
    IndustryState.MATURITY: [
        "成熟", "稳定量产", "标准产品", "行业标准", "毛利率稳定",
        "行业龙头", "主导市场", "稳定供货", "成熟产品", "工艺稳定",
        "满产满销", "稳定增长", "市场份额稳定", "行业标准制定",
    ],
    IndustryState.DECLINE: [
        "需求下降", "产能过剩", "技术替代", "被淘汰", "市场萎缩",
        "毛利率下降", "竞争加剧", "营收下滑", "停产", "退出市场",
        "技术迭代", "新产品替代", "需求疲软", "去库存", "夕阳产业",
        "关停产线", "产能关停", "大幅亏损", "债务危机", "破产",
    ],
}


# ── 关键词 → 状态映射（用于快速推断）──────────────────────────────────

# 预编译正则，避免每次推断重复编译
_STATE_PATTERNS: dict[IndustryState, list[re.Pattern]] = {}
for _state, _kws in STATE_KEYWORDS.items():
    _STATE_PATTERNS[_state] = [re.compile(_kw) for _kw in _kws]


# ── 核心函数 ──────────────────────────────────────────────────────────────

@dataclass
class Transition:
    """一次状态转换记录"""
    from_state: IndustryState
    to_state: IndustryState
    valid_from: date
    valid_to: Optional[date] = None
    evidence: str = ""
    confidence: float = 1.0


def infer_state_from_text(text: str) -> Optional[IndustryState]:
    """
    从文本关键词推断当前行业状态。

    策略：分数相同时，取"更晚期"的状态（GROWTH > MATURITY > ...）。
    原因：同一文本中，早期+晚期词共存时，取更保守的晚期解读。

    Returns:
        IndustryState 或 None（无法判断）
    """
    if not text:
        return None

    scores: dict[IndustryState, int] = {s: 0 for s in IndustryState}
    matched_kw_lengths: dict[IndustryState, int] = {s: 0 for s in IndustryState}

    for state, patterns in _STATE_PATTERNS.items():
        for pat in patterns:
            match = pat.search(text)
            if match:
                scores[state] += 1
                # 记录最长匹配关键词长度（用于同分时优选更长的）
                matched_kw_lengths[state] = max(matched_kw_lengths[state], len(pat.pattern))

    if not any(scores.values()):
        return None

    # 分数相同时取更晚期状态（数值越大越晚期）
    # 优先级：GROWTH(5) > MATURITY(4) > EARLY_ADOPTION(3) > PILOT(2) > RND(1) > LAB(0) > DECLINE(6,独立)
    state_rank = {
        IndustryState.GROWTH: 5,
        IndustryState.MATURITY: 4,
        IndustryState.EARLY_ADOPTION: 3,
        IndustryState.PILOT: 2,
        IndustryState.RND: 1,
        IndustryState.LAB: 0,
        IndustryState.DECLINE: -1,  # 衰退独立，不与其他早期状态并列
    }

    best_state: Optional[IndustryState] = None
    best_score = -1
    best_rank = -2
    best_kw_len = -1

    for state, score in scores.items():
        if score == 0:
            continue
        rank = state_rank.get(state, -1)
        kw_len = matched_kw_lengths[state]
        # 优先分数，其次优先级（晚期>早期），同分时选最长关键词匹配
        if (score > best_score or
            (score == best_score and rank > best_rank) or
            (score == best_score and rank == best_rank and kw_len > best_kw_len)):
            best_score = score
            best_rank = rank
            best_kw_len = kw_len
            best_state = state

    return best_state


def validate_transition(
    from_state: IndustryState,
    to_state: IndustryState,
) -> bool:
    """
    校验状态转换是否合法。

    注意：DECLINE → GROWTH/MATURITY 允许（技术升级再成长）
    """
    if from_state == to_state:
        return True  # 状态维持
    return to_state in VALID_TRANSITIONS.get(from_state, set())


def describe_state(state: IndustryState) -> str:
    """返回状态的自然语言描述"""
    descriptions = {
        IndustryState.LAB:            "实验室/理论研究阶段",
        IndustryState.RND:            "研发/产品工程化阶段",
        IndustryState.PILOT:          "中试/客户认证阶段",
        IndustryState.EARLY_ADOPTION: "早期采用/商业化初期",
        IndustryState.GROWTH:         "规模量产/成长期",
        IndustryState.MATURITY:       "成熟稳定期",
        IndustryState.DECLINE:        "衰退/被替代阶段",
    }
    return descriptions.get(state, str(state))


def get_all_states() -> list[IndustryState]:
    """返回所有状态（按生命周期顺序）"""
    return [
        IndustryState.LAB,
        IndustryState.RND,
        IndustryState.PILOT,
        IndustryState.EARLY_ADOPTION,
        IndustryState.GROWTH,
        IndustryState.MATURITY,
        IndustryState.DECLINE,
    ]


# ── 状态跃迁提取 ─────────────────────────────────────────────────────────────

@dataclass
class StateTransition:
    """一次状态跃迁"""
    from_state: IndustryState
    to_state: IndustryState
    direction: str          # positive（进步）/ negative（退步）/ neutral（同级）
    evidence: str          # 原文证据（包含关键词的句子片段）
    source_type: str       # 证据来源描述
    confidence: float       # 置信度（基于来源）


# 显式跃迁模式：从X进入/升级到/跃迁到Y
# B11 fix: 移除不合理的正则，依赖关键词匹配
_EXPLICIT_PATTERNS: list[re.Pattern] = [
    # 从X → Y 显式表述（依赖 _match_state_keyword 匹配状态关键词）
    re.compile(r"从(.+?阶段).*?升级到(.+?期)"),
    re.compile(r"(.+?)已.*?进入?(.+?期)"),
    re.compile(r"(.+?)已.*?跃迁到(.+?期)"),
    re.compile(r"(.+?)已.*?升级到(.+?期)"),
    re.compile(r"(.+?)实现.*?进入?(.+?期)"),
    re.compile(r"从(.+?)向(.+?)跃迁"),
    re.compile(r"(.+?)向(.+?)迈进"),
    re.compile(r"(.+?)已处于(.+?期)"),
    re.compile(r"(.+?)目前处于(.+?期)"),
    # 量产信号
    re.compile(r"已实现规模量产"),
    re.compile(r"进入?产能爬坡"),
    re.compile(r"产能.*?释放"),
    re.compile(r"批量供货|规模交付|正式投产"),
    # 衰退信号
    re.compile(r"产能过剩|需求下降|被替代"),
    re.compile(r"技术迭代|新产品替代"),
]

# 状态等级（用于判断进步/退步）
_STATE_LEVEL: dict[IndustryState, int] = {
    IndustryState.LAB: 0,
    IndustryState.RND: 1,
    IndustryState.PILOT: 2,
    IndustryState.EARLY_ADOPTION: 3,
    IndustryState.GROWTH: 4,
    IndustryState.MATURITY: 5,
    IndustryState.DECLINE: -1,
}


def _match_state_keyword(text: str) -> list[tuple[IndustryState, int]]:
    """
    找出文本中所有匹配的状态关键词及其位置索引。
    返回 [(state, match_start_index), ...]，按位置升序。
    """
    matches: list[tuple[IndustryState, int]] = []
    for state, patterns in _STATE_PATTERNS.items():
        for pat in patterns:
            for m in pat.finditer(text):
                matches.append((state, m.start()))
    # 按位置排序
    matches.sort(key=lambda x: x[1])
    # 去重（同一位置只保留最高等级状态）
    seen_pos: dict[int, IndustryState] = {}
    for state, pos in matches:
        if pos not in seen_pos:
            seen_pos[pos] = state
        else:
            # 同位置保留等级更高的
            if _STATE_LEVEL.get(state, -1) > _STATE_LEVEL.get(seen_pos[pos], -1):
                seen_pos[pos] = state
    return [(s, p) for p, s in sorted(seen_pos.items())]


def _infer_direction(from_state: IndustryState, to_state: IndustryState) -> str:
    if from_state == to_state:
        return "neutral"
    from_level = _STATE_LEVEL.get(from_state, 0)
    to_level = _STATE_LEVEL.get(to_state, 0)
    if from_state == IndustryState.DECLINE:
        return "positive" if to_level > 0 else "neutral"
    if to_state == IndustryState.DECLINE:
        return "negative"
    return "positive" if to_level > from_level else "negative"


def extract_state_transitions(
    text: str,
    max_sentences: int = 50,
) -> list[StateTransition]:
    """
    从文本中提取所有状态跃迁。

    策略：
    1. 显式跃迁模式：匹配"从X进入Y"等明确表述
    2. 相邻状态推断：同句中相邻位置出现不同状态关键词 → 推断为跃迁

    Args:
        text: 原始文本
        max_sentences: 最大处理句子数（防止过长文本）

    Returns:
        list[StateTransition]，可能为空
    """
    if not text:
        return []

    transitions: list[StateTransition] = []
    seen_pairs: set[tuple] = set()  # 去重 (from, to) 对

    # 按句子分割（减少跨句误匹配）
    sentences = [s.strip() for s in re.split(r"[。！？\n]", text) if s.strip()]
    sentences = sentences[:max_sentences]

    for sent in sentences:
        matched_states = _match_state_keyword(sent)
        if not matched_states:
            continue

        # 策略1：显式跃迁模式（直接匹配"进入/升级/跃迁"等动词）
        for pattern in _EXPLICIT_PATTERNS:
            m = pattern.search(sent)
            if m and matched_states:
                # 取第一个匹配状态作为 to_state
                to_state = matched_states[0][0]
                # 找上一个不同状态作为 from_state
                from_state = IndustryState.RND  # 默认值
                for st, _ in matched_states:
                    if st != to_state:
                        from_state = st
                        break
                pair = (from_state, to_state)
                if pair not in seen_pairs and from_state != to_state:
                    if validate_transition(from_state, to_state):
                        seen_pairs.add(pair)
                        transitions.append(StateTransition(
                            from_state=from_state,
                            to_state=to_state,
                            direction=_infer_direction(from_state, to_state),
                            evidence=sent[:200],
                            source_type="explicit_pattern",
                            confidence=0.85,
                        ))
                break  # 一个句子只匹配一次显式模式

        # 策略2：相邻状态推断（同句中两个不同状态连续出现）
        # 严格要求句子含有显式过渡动词，避免"目前处于...已通过..."误判为状态跃迁
        if len(matched_states) >= 2:
            transition_verbs = re.search(
                r"从.+到|从.+进入|进入|升级|跃迁|迈向|过渡|转化|迈进",
                sent
            )
            current_state_marker = re.search(r"目前处于|处于|目前是|目前为", sent)
            if transition_verbs and not current_state_marker:
                states_in_sent = [st for st, _ in matched_states]
                to_state = states_in_sent[-1]
                from_state = states_in_sent[0]
                if from_state != to_state and validate_transition(from_state, to_state):
                    pair = (from_state, to_state)
                    if pair not in seen_pairs:
                        seen_pairs.add(pair)
                        transitions.append(StateTransition(
                            from_state=from_state,
                            to_state=to_state,
                            direction=_infer_direction(from_state, to_state),
                            evidence=sent[:200],
                            source_type="adjacent_states",
                            confidence=0.70,
                        ))

    # 策略3：跨句状态追踪
    # 每句返回多个状态，追踪状态序列，捕获"此前X，现在Y"类过渡
    doc_state_sequence: list[tuple[IndustryState, str, bool]] = []  # (state, sentence, is_past_marker)
    for sent in sentences:
        matched = _match_state_keyword(sent)
        if not matched:
            continue
        # 取等级最高的状态作为主状态
        dominant = max(matched, key=lambda x: _STATE_LEVEL.get(x[0], -1))
        # 检查是否有"此前/过去/曾经"等回溯词（表示此句描述的是过去状态）
        past_markers = re.search(r"此前|之前|过去|曾经|去年|前年|上一年", sent)
        doc_state_sequence.append((dominant[0], sent, bool(past_markers)))

    # 追踪状态序列，区分当前状态和历史状态
    # 策略：最后一个非回溯句的状态 = 当前状态；第一个回溯句的状态 = 前一状态
    current_state: Optional[IndustryState] = None
    prev_historical_state: Optional[IndustryState] = None
    for st, sent, is_past in reversed(doc_state_sequence):
        if not is_past and current_state is None:
            current_state = st
        if is_past and prev_historical_state is None:
            prev_historical_state = st

    # 如果 current_state 已知，且前序历史状态也已知，提取跃迁
    if current_state and prev_historical_state:
        pair = (prev_historical_state, current_state)
        if pair not in seen_pairs and validate_transition(prev_historical_state, current_state):
            seen_pairs.add(pair)
            transitions.append(StateTransition(
                from_state=prev_historical_state,
                to_state=current_state,
                direction=_infer_direction(prev_historical_state, current_state),
                evidence=f"当前状态: {current_state.value}，历史状态: {prev_historical_state.value}",
                source_type="current_vs_historical",
                confidence=0.75,
            ))

    # 额外：从状态序列中提取顺序跃迁（用于有多个状态的文本）
    if len(doc_state_sequence) >= 2:
        prev_s, prev_sent_s, _ = doc_state_sequence[0]
        for cur_s, cur_sent, is_past in doc_state_sequence[1:]:
            # 跳过回溯句（"此前"描述的是更早状态，不是当前→下一步）
            if is_past:
                continue
            if prev_s != cur_s:
                pair = (prev_s, cur_s)
                if pair not in seen_pairs and validate_transition(prev_s, cur_s):
                    seen_pairs.add(pair)
                    st_dir = _infer_direction(prev_s, cur_s)
                    # 过滤：cross_sentence_progression 只接受 positive 或 neutral，不接受 negative
                    if st_dir != "negative":
                        transitions.append(StateTransition(
                            from_state=prev_s,
                            to_state=cur_s,
                            direction=st_dir,
                            evidence=cur_sent[:200],
                            source_type="cross_sentence_progression",
                            confidence=0.65,
                        ))
            prev_s, prev_sent_s = cur_s, cur_sent

    return transitions


def extract_current_and_previous_state(text: str) -> tuple[Optional[IndustryState], Optional[IndustryState]]:
    """
    推断当前状态和前序状态（用于判断最新阶段）。

    当前状态：文本末段匹配的状态
    前序状态：文本前段匹配的最新不同状态

    Returns:
        (current_state, previous_state)
    """
    if not text:
        return None, None

    # 取后1/3作为"当前"区域
    cutoff = len(text) * 2 // 3
    current_text = text[cutoff:]
    prev_text = text[:cutoff]

    current = infer_state_from_text(current_text)
    prev = infer_state_from_text(prev_text)

    # 如果当前状态和前序相同，说明无跃迁
    if current == prev:
        return current, None

    return current, prev


def build_transition_signal(
    transitions: list[StateTransition],
) -> dict:
    """
    根据跃迁列表构建投资信号。

    核心逻辑：
    - positive 跃迁 + 从 PILOT/EA → GROWTH = 业绩释放信号（最强烈）
    - positive 跃迁 + 从 RND → PILOT = 导入期信号
    - negative 跃迁 = 风险信号

    Returns:
        dict，包含 signal_type / urgency / description / transitions
    """
    if not transitions:
        return {"signal": None, "urgency": 0, "description": ""}

    # 只看 positive 跃迁
    positive = [t for t in transitions if t.direction == "positive"]
    negative = [t for t in transitions if t.direction == "negative"]

    # 最有价值的跃迁：从 PILOT/EA → GROWTH（量产拐点）
    inflection = [
        t for t in positive
        if t.from_state in (IndustryState.PILOT, IndustryState.EARLY_ADOPTION)
        and t.to_state == IndustryState.GROWTH
    ]

    if inflection:
        sig = inflection[0]
        return {
            "signal": "PRODUCTION_INFLECTION",  # 量产拐点信号
            "urgency": 5,
            "level": "A+",
            "description": f"从{sig.from_state.value}跃迁至{sig.to_state.value}，业绩释放预期最强",
            "transitions": [f"{t.from_state.value} → {t.to_state.value}({t.direction})" for t in transitions],
        }

    if positive:
        sig = positive[0]
        return {
            "signal": "STATE_ADVANCE",
            "urgency": 3,
            "level": "B",
            "description": f"状态进步：{sig.from_state.value} → {sig.to_state.value}",
            "transitions": [f"{t.from_state.value} → {t.to_state.value}({t.direction})" for t in transitions],
        }

    if negative:
        sig = negative[0]
        return {
            "signal": "STATE_DECLINE",
            "urgency": 4,
            "level": "B+",
            "description": f"状态退步：{sig.from_state.value} → {sig.to_state.value}，注意风险",
            "transitions": [f"{t.from_state.value} → {t.to_state.value}({t.direction})" for t in transitions],
        }

    return {"signal": None, "urgency": 0, "description": ""}

