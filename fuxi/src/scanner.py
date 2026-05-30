"""伏羲 Scanner v1 — 条件扫描器 → 情境画像

输入: 用户消息 (str) + 可选历史上下文
输出: 结构化情境画像 (ProfileDict)

核心维度:
- intent: 用户意图分类
- domain: 领域识别
- urgency: 紧急程度
- risk_level: 风险等级
- expertise: 用户专业度推测
"""


import re
from dataclasses import dataclass, asdict
from typing import Optional


# ============================================================
# 枚举定义 (用字符串常量，不依赖 enum 模块)
# ============================================================

INTENT_CHAT = "CHAT"
INTENT_QUERY = "QUERY"
INTENT_ANALYSIS = "ANALYSIS"
INTENT_CREATE = "CREATE"
INTENT_DEBUG = "DEBUG"
INTENT_DESIGN = "DESIGN"
INTENT_UNKNOWN = "UNKNOWN"

DOMAIN_TECH = "TECH"
DOMAIN_FINANCE = "FINANCE"
DOMAIN_LITERARY = "LITERARY"
DOMAIN_DAILY = "DAILY"
DOMAIN_HEALTH = "HEALTH"
DOMAIN_LEGAL = "LEGAL"
DOMAIN_ENTERTAINMENT = "ENTERTAINMENT"
DOMAIN_UNKNOWN = "UNKNOWN"

URGENCY_LOW = "LOW"
URGENCY_MEDIUM = "MEDIUM"
URGENCY_HIGH = "HIGH"
URGENCY_CRITICAL = "CRITICAL"

RISK_LOW = "LOW"
RISK_MEDIUM = "MEDIUM"
RISK_HIGH = "HIGH"
RISK_CRITICAL = "CRITICAL"


# ============================================================
# 正则匹配模式 (按优先级排列)
# ============================================================

INTENT_PATTERNS = [
    # CREATE: 创作/生成类
    (r"(写|创建|制作|生成|设计|画|编|做(一篇|一个|一段)|起草|撰写)", INTENT_CREATE, 0),
    # DEBUG: 调试/排错类
    (r"(debug|排错|报错|bug|出错|运行不了|异常|error|traceback|为什么跑不通)", INTENT_DEBUG, 0),
    # ANALYSIS: 分析/研究类
    (r"(分析|研究|对比|评测|趋势|走势|盘点|梳理|解读|怎么看|深度|洞察|该买还是卖|建议)", INTENT_ANALYSIS, 0),
    # QUERY: 查询/知识类
    (r"(查|看|是什么|怎么做|怎么弄|如何(实现|配置|安装)|教程|步骤|方法|资料|数据|信息)", INTENT_QUERY, 0),
    # CHAT: 闲聊/情感类
    (r"(^|\s)(你好|嗨|hello|hi|早上好|晚上好|在吗|吃了没|今天.*怎么样|哈哈|呵呵|嘻嘻)(\s|$)", INTENT_CHAT, re.IGNORECASE | re.MULTILINE),
]

URGENCY_PATTERNS = [
    ("紧急|快|立刻|马上|急需|赶紧|帮帮忙|救命|报错|跑不通", URGENCY_HIGH),
    ("急|尽快|快点|时间紧", URGENCY_MEDIUM),
    ("不急|慢慢来|有空再说|先放着|回头再说", URGENCY_LOW),
]

DOMAIN_PATTERNS = [
    # FINANCE
    (r"(股票|基金|A股|港股|美股|投资|理财|板块|回调|牛市|熊市|财报|估值|PE|PB|均线|成交量)", DOMAIN_FINANCE),
    # HEALTH
    (r"(医疗|医院|药|病情|症状|诊断|治疗|处方|健康|体检|疾病|疫苗|免疫)", DOMAIN_HEALTH),
    # LEGAL
    (r"(法律|合同|诉讼|律师|仲裁|法院|判决|法规|合规|侵权|知识产权|劳动法)", DOMAIN_LEGAL),
    # TECH
    (r"(代码|编程|Python|Java|JavaScript|React|Vue|API|数据库|服务器|部署|Docker|K8s|Git|算法|模型|AI|LLM)", DOMAIN_TECH),
    # LITERARY
    (r"(国学|易经|道德经|论语|诗词|书法|绘画|汉服|茶道|中医|风水|八字|命理)", DOMAIN_LITERARY),
]

EXPERTISE_INDICATORS = [
    ("专业术语|API|架构|部署|Docker|K8s|PE/PB|均线", "HIGH"),       # 用户懂行
    ("怎么用|怎么做|什么是|如何开始|教程", "LOW"),                       # 初学者
]


# ============================================================
# Profile 数据类
# ============================================================

@dataclass
class Profile:
    """情境画像 — scanner 的唯一输出"""
    intent: str = INTENT_UNKNOWN
    domain: str = DOMAIN_UNKNOWN
    urgency: str = URGENCY_MEDIUM
    risk_level: str = RISK_LOW
    expertise: str = "MEDIUM"  # HIGH / MEDIUM / LOW
    has_history: bool = False   # 是否有上下文历史
    
    # 原始匹配分数 (供 cortex 权衡使用)
    intent_scores: dict = None       # {intent_label: score}
    domain_scores: dict = None       # {domain_label: score}
    raw_keywords: list = None        # 扫描到的关键词列表

    def __post_init__(self):
        if self.intent_scores is None:
            self.intent_scores = {}
        if self.domain_scores is None:
            self.domain_scores = {}
        if self.raw_keywords is None:
            self.raw_keywords = []


# ============================================================
# Scanner 核心类
# ============================================================

class ConditionScanner:
    """条件扫描器 — 从用户消息中提取结构化情境画像"""

    def __init__(self):
        self.intents = INTENT_PATTERNS
        self.urgencies = URGENCY_PATTERNS
        self.domains = DOMAIN_PATTERNS

    def scan(self, message: str) -> Profile:
        """
        扫描用户消息，返回情境画像。

        Args:
            message: 原始用户输入

        Returns:
            Profile 实例
        """
        if not message or not isinstance(message, str):
            return self._default_profile()

        profile = Profile(
            intent=self._detect_intent(message),
            domain=self._detect_domain(message),
            urgency=self._detect_urgency(message),
            risk_level=self._detect_risk(message),
            expertise=self._detect_expertise(message),
        )

        return profile

    def _detect_intent(self, msg: str) -> str:
        """按优先级匹配意图"""
        best_intent = INTENT_UNKNOWN
        for item in self.intents:
            if isinstance(item, tuple):
                pattern_str = item[0]
                intent = item[1]
                flags = item[2] if len(item) > 2 else 0
            else:
                continue

            if re.search(pattern_str, msg, flags):
                best_intent = intent
                break
        return best_intent

    def _detect_domain(self, msg: str) -> tuple[str, dict]:
        """匹配领域，返回 (domain_label, scores_dict)"""
        domain_scores = {}
        for item in self.domains:
            if isinstance(item, tuple):
                p_str = item[0]
                domain = item[1]
            else:
                continue
            matches = re.findall(p_str, msg)
            if matches:
                domain_scores[domain] = len(matches)

        if not domain_scores:
            return DOMAIN_UNKNOWN, {}

        best_domain = max(domain_scores, key=domain_scores.get)
        return best_domain, domain_scores

    def _detect_urgency(self, msg: str) -> str:
        """检测紧急程度"""
        urgency = URGENCY_MEDIUM  # 默认中等
        for pattern, level in self.urgencies:
            if re.search(pattern, msg):
                urgency = level
                break
        return urgency

    def _detect_risk(self, msg: str) -> str:
        """根据领域和关键词推断风险等级"""
        high_risk_domains = {DOMAIN_FINANCE, DOMAIN_HEALTH, DOMAIN_LEGAL}
        for item in self.domains:
            if isinstance(item, tuple):
                p_str = item[0]
                domain = item[1]
            else:
                continue
            if re.search(p_str, msg) and domain in high_risk_domains:
                return RISK_HIGH
        risk_kw = [r"(投资|理财|处方|手术|诉讼|律师)", r"(建议|推荐|预测|判断)"]
        for pattern in risk_kw:
            if re.search(pattern, msg):
                return RISK_MEDIUM
        return RISK_LOW

    def _detect_expertise(self, msg: str) -> str:
        """推测用户专业度"""
        for indicators, level in EXPERTISE_INDICATORS:
            if re.search(indicators, msg):
                return level
        return "MEDIUM"  # 默认中等

    def _default_profile(self) -> Profile:
        """空输入返回默认画像"""
        return Profile(
            intent=INTENT_UNKNOWN,
            domain=DOMAIN_UNKNOWN,
            urgency=URGENCY_MEDIUM,
            risk_level=RISK_LOW,
            expertise="MEDIUM",
        )

    def scan_with_scores(self, message: str) -> Profile:
        """增强版扫描 — 返回带完整分数的画像 (供 cortex 深度决策使用)"""
        profile = self.scan(message)

        # 填充 intent_scores
        for item in self.intents:
            if isinstance(item, tuple):
                p_str = item[0]
                intent = item[1]
            else:
                continue
            matches = re.findall(p_str, message)
            if matches:
                profile.intent_scores[intent] = len(matches)

        # 填充 domain_scores (已在 _detect_domain 中计算，这里重新做一遍)
        for pattern, domain in self.domains:
            if isinstance(pattern, tuple):
                p_str = pattern[0]
            else:
                p_str = pattern
            matches = re.findall(p_str, message)
            if matches:
                profile.domain_scores[domain] = len(matches)

        # 收集关键词
        def extract_pattern(item):
            if isinstance(item, tuple):
                return item[0]
            return None

        keywords = []
        for item in self.intents + self.domains:
            p_str = extract_pattern(item)
            if not p_str:
                continue
            matched = re.findall(p_str, message)
            if matched:
                keywords.extend(matched)
        profile.raw_keywords = list(set(keywords))

        return profile


# ============================================================
# API (单例模式 — 全局共享)
# ============================================================

scanner = ConditionScanner()


def scan(message: str) -> Profile:
    """快捷函数：扫描用户消息返回画像"""
    return scanner.scan(message)


def scan_with_scores(message: str) -> Profile:
    """快捷函数：带分数的扫描（供 cortex 深度决策使用）"""
    return scanner.scan_with_scores(message)


if __name__ == "__main__":
    # 测试场景
    test_cases = [
        "帮我分析一下A股新能源板块的回调",
        "你好，吃了没",
        "Python代码报错: FileNotFoundError: [Errno 2] No such file or directory",
        "帮我写一首关于月亮的古诗",
        "这个股票该买还是卖？",
    ]

    print("=== FUXI Scanner Test ===\n")
    for msg in test_cases:
        p = scanner.scan_with_scores(msg)
        d = asdict(p)
        # 精简输出
        out = {k: v for k, v in d.items() 
               if k not in ('intent_scores', 'domain_scores', 'raw_keywords')
               or (v and isinstance(v, dict))}
        print(f"输入: {msg}")
        print(f"  intent={p.intent}, domain={p.domain}, urgency={p.urgency}, risk={p.risk_level}, expertise={p.expertise}")
        if p.intent_scores:
            print(f"  intent_scores={p.intent_scores}")
        if p.domain_scores:
            print(f"  domain_scores={p.domain_scores}")
        print()
