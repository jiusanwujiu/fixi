"""伏羲 Cortex v1 — 裁量中枢 (核心)

纯Python逻辑运算，零LLM依赖。
输入: Profile (scanner输出) + Values/Boundaries (values模块)
输出: DecisionDict = {role, stance, depth, tone, constraints}

设计原则:
- 不"思考"——是规则引擎，不是推理主体
- 价值冲突时按优先级排序，无歧义
- 每次决策可追溯：记录触发了哪些价值和边界
"""


from dataclasses import dataclass, asdict


# ============================================================
# 枚举常量 (复用 scanner.py 的常量)
# ============================================================

INTENT_CHAT = "CHAT"
INTENT_QUERY = "QUERY"
INTENT_ANALYSIS = "ANALYSIS"
INTENT_CREATE = "CREATE"
INTENT_DEBUG = "DEBUG"
INTENT_DESIGN = "DESIGN"

URGENCY_LOW = "LOW"
URGENCY_MEDIUM = "MEDIUM"
URGENCY_HIGH = "HIGH"

RISK_LOW = "LOW"
RISK_MEDIUM = "MEDIUM"
RISK_HIGH = "HIGH"


ROLE_CHAT = "对话伙伴"
ROLE_RESEARCHER = "行业研究员"
ROLE_ANALYST = "数据分析师"
ROLE_CREATOR = "创作助手"
ROLE_TECH_LEAD = "技术负责人"

STANCE_DIRECT = "DIRECT"
STANCE_PROVISIONAL = "PROVISIONAL"
STANCE_EXPLORATORY = "EXPLORATORY"
STANCE_CONSERVATIVE = "CONSERVATIVE"

DEPTH_SHALLOW = "SHALLOW"
DEPTH_MEDIUM = "MEDIUM"
DEPTH_DEEP = "DEEP"
DEPTH_MINIMAL = "MINIMAL"

TONE_CASUAL = "CASUAL"
TONE_PROFESSIONAL = "PROFESSIONAL"
TONE_ANALYTICAL = "ANALYTICAL"
TONE_CREATIVES = "CREATIVE"
TONE_CONVERSATIONAL = "CONVERSATIONAL"


# ============================================================
# Decision 数据类
# ============================================================

@dataclass
class Decision:
    """裁量中枢的唯一输出"""
    role: str
    stance: str
    depth: str
    tone: str
    constraints: list          # ["citation_required", "disclaimer_if_finance"]
    value_triggers: list       # ["V1", "V4"] — 审计日志用
    boundary_violations: list  # 触发的边界ID (空=无违规)

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# Cortex 核心类
# ============================================================

class DecisionCortex:
    """裁量中枢 — 伏羲的核心决策引擎"""

    HIGH_RISK_DOMAINS = {
        "FINANCE": {"constraints": ["disclaimer_required", "no_advice_format"]},
        "HEALTH": {"constraints": ["medical_disclaimer", "consult_professional_required"]},
        "LEGAL": {"constraints": ["legal_disclaimer", "jurisdiction_note"]},
    }

    def __init__(self):
        pass

    def decide(self, profile) -> Decision:
        """
        主决策入口 — 从 Profile 到 Decision。

        Args:
            profile: scanner.scan_with_scores() 返回的画像

        Returns:
            Decision 实例
        """
        # Step 1: 基础决策 (role/stance/depth/tone)
        role = self._decide_role(profile)
        stance = self._decide_stance(profile)
        depth = self._decide_depth(profile)
        tone = self._decide_tone(profile)

        # Step 2: 约束列表构建
        constraints = self._build_constraints(profile)

        # Step 3: 价值触发记录 (审计用)
        value_triggers = self._trace_values(profile, role, stance)

        # Step 4: 边界违规检测
        boundary_violations = []
        if hasattr(profile, 'raw_keywords') and profile.raw_keywords:
            for kw in str(profile.raw_keywords):
                violations = self._check_boundary(kw)
                boundary_violations.extend(violations)

        # Step 5: 如果有边界违规，调整决策为保守姿态
        if boundary_violations:
            stance = STANCE_CONSERVATIVE
            constraints.append("boundary_alert_shown")

        return Decision(
            role=role,
            stance=stance,
            depth=depth,
            tone=tone,
            constraints=list(set(constraints)),  # 去重
            value_triggers=value_triggers,
            boundary_violations=list(set(boundary_violations)),
        )

    def _decide_role(self, profile) -> str:
        """根据意图和领域决定角色"""
        intent = getattr(profile, 'intent', "UNKNOWN")
        domain = getattr(profile, 'domain', None) or "UNKNOWN"

        # 高风险领域 → 专业研究员角色
        if isinstance(domain, tuple):
            domain = domain[0] if domain else "UNKNOWN"
        if domain in ("FINANCE", "HEALTH", "LEGAL"):
            return ROLE_RESEARCHER

        # 意图驱动角色映射
        role_map = {
            INTENT_CREATE: ROLE_CREATOR,
            INTENT_DEBUG: ROLE_TECH_LEAD,
            INTENT_ANALYSIS: ROLE_ANALYST,
            INTENT_CHAT: ROLE_CHAT,
            INTENT_QUERY: ROLE_RESEARCHER,
        }
        return role_map.get(intent, ROLE_RESEARCHER)

    def _decide_stance(self, profile) -> str:
        """决定判断姿态"""
        intent = getattr(profile, 'intent', "UNKNOWN")
        risk = getattr(profile, 'risk_level', RISK_LOW)

        # 高风险领域 → 保守/留余地
        if risk == RISK_HIGH:
            return STANCE_PROVISIONAL

        # CHAT → 直接
        if intent == INTENT_CHAT:
            return STANCE_DIRECT

        # ANALYSIS + 中等风险 → 探索性
        if intent == INTENT_ANALYSIS and risk == RISK_MEDIUM:
            return STANCE_EXPLORATORY

        # 默认 → 直接但有依据
        return STANCE_DIRECT

    def _decide_depth(self, profile) -> str:
        """决定输出深度"""
        intent = getattr(profile, 'intent', "UNKNOWN")
        urgency = getattr(profile, 'urgency', URGENCY_MEDIUM)
        domain = getattr(profile, 'domain', None) or "UNKNOWN"

        if isinstance(domain, tuple):
            domain = domain[0] if domain else "UNKNOWN"

        # 闲聊/简单查询 → 浅层
        if intent == INTENT_CHAT:
            return DEPTH_SHALLOW

        # 紧急 + 调试 → 中等 (快速给方案)
        if urgency == URGENCY_HIGH and intent == INTENT_DEBUG:
            return DEPTH_MEDIUM

        # 分析类/高风险领域 → 深度
        if intent in (INTENT_ANALYSIS, INTENT_DESIGN) or domain in ("FINANCE", "HEALTH", "LEGAL"):
            return DEPTH_DEEP

        # CREATE → 中等 (需要完整框架)
        if intent == INTENT_CREATE:
            return DEPTH_MEDIUM

        # DEBUG → 中等
        if intent == INTENT_DEBUG:
            return DEPTH_MEDIUM

        # 默认 → 中等
        return DEPTH_MEDIUM

    def _decide_tone(self, profile) -> str:
        """决定表达风格"""
        intent = getattr(profile, 'intent', "UNKNOWN")
        domain = getattr(profile, 'domain', None) or "UNKNOWN"
        expertise = getattr(profile, 'expertise', "MEDIUM")

        if isinstance(domain, tuple):
            domain = domain[0] if domain else "UNKNOWN"

        # 闲聊 → 轻松
        if intent == INTENT_CHAT:
            return TONE_CASUAL

        # 专业领域 → 专业严谨
        if domain in ("FINANCE", "HEALTH", "LEGAL"):
            return TONE_PROFESSIONAL

        # 技术 + 用户高水平 → 对话式(同行交流)
        if intent == INTENT_DEBUG and expertise == "HIGH":
            return TONE_CONVERSATIONAL

        # CREATE → 创意
        if intent == INTENT_CREATE:
            return TONE_CREATIVES

        # 默认 → 专业分析
        return TONE_ANALYTICAL

    def _build_constraints(self, profile) -> list:
        """构建约束列表 — 从领域配置 + 画像特征推导"""
        constraints = []
        domain = getattr(profile, 'domain', None) or "UNKNOWN"

        if isinstance(domain, tuple):
            domain = domain[0] if domain else "UNKNOWN"

        # 1. 来自高风险领域的默认约束
        if domain in self.HIGH_RISK_DOMAINS:
            config = self.HIGH_RISK_DOMAINS[domain]
            for c in config.get("constraints", []):
                constraints.append(c)

        # 2. 价值推导的通用约束
        intent = getattr(profile, 'intent', "UNKNOWN")
        if intent == INTENT_ANALYSIS:
            constraints.append("citation_optional")

        return constraints

    def _trace_values(self, profile, role, stance) -> list:
        """记录触发了哪些价值 — 用于审计日志"""
        triggers = []
        intent = getattr(profile, 'intent', "UNKNOWN")
        risk = getattr(profile, 'risk_level', RISK_LOW)

        # V1 (产生增量): ANALYSIS/CREATE 必然触发
        if intent in (INTENT_ANALYSIS, INTENT_CREATE):
            triggers.append("V1")

        # V2 (判断力优先): HIGH风险领域触发
        if risk == RISK_HIGH:
            triggers.append("V2")

        # V3 (主动不越界): CHAT + 中等以上专业度 → 可能引导话题
        if intent == INTENT_CHAT and getattr(profile, 'expertise', "MEDIUM") != "LOW":
            triggers.append("V3")

        # V4 (可追溯推理): ANALYSIS/QUERY 触发
        if intent in (INTENT_ANALYSIS, INTENT_QUERY):
            triggers.append("V4")

        return triggers if triggers else ["V6"]  # 至少记录V6(连续性)

    def _check_boundary(self, text: str) -> list:
        """检查文本是否违反硬边界，返回违规ID列表"""
        import re
        violations = []

        # B0/B3: 对外发送消息检测 (发/寄/打/传 + 微/信/邮件/短信/电话/发布)
        pattern = r"(发|寄|打|传).{0,4}(微|信|邮件|email|短信|电话|发布)"
        if re.search(pattern, text):
            violations.append("B3")

        # B1: 隐私泄露检测
        kw_b1 = ["泄露", "暴露隐私", "告诉别人", "透露"]
        for k in kw_b1:
            if k in text:
                violations.append("B1")
                break

        # B4: 编造数据检测
        if re.search(r"编.{0,2}数|虚构|伪造", text):
            violations.append("B4")

        return violations


# ============================================================
# API (全局单例)
# ============================================================

cortex = DecisionCortex()


def decide(profile) -> Decision:
    """快捷函数：从 Profile 到 Decision"""
    return cortex.decide(profile)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, '.')  # ensure current dir is on path
    from scanner import scan_with_scores, scanner as scanner_instance

    test_cases = [
        "帮我分析一下A股新能源板块的回调",
        "你好，吃了没",
        "Python代码报错: FileNotFoundError: [Errno 2] No such file or directory",
        "帮我写一首关于月亮的古诗",
        "这个股票该买还是卖？",
    ]

    print("=== FUXI Cortex Test ===\n")
    for msg in test_cases:
        profile = scanner_instance.scan_with_scores(msg)
        decision = cortex.decide(profile)
        d = decision.to_dict()
        print(f"输入: {msg}")
        print(f"  role={d['role']}, stance={d['stance']}")
        print(f"  depth={d['depth']}, tone={d['tone']}")
        if d['constraints']:
            print(f"  constraints={d['constraints']}")
        if d['value_triggers']:
            print(f"  value_triggers={d['value_triggers']}")
        if d['boundary_violations']:
            print(f"  ⚠️ boundary_violations={d['boundary_violations']}")
        print()
