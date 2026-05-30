"""伏羲 prompt_gen v1 — Prompt 生成器 (笔墨)

输入: DecisionDict + Profile + user_message
输出: 自包含式自然语言prompt，可直接发送给主LLM

设计原则:
- MVP使用规则模板拼接（P0验证链路）
- P2升级为小模型生成（更自然、更有上下文感知）
- prompt本身是完整任务指令，不依赖也不抵抗系统模板
"""


from dataclasses import dataclass
import json


# ============================================================
# Role 描述映射 (从角色标识到自然语言描述)
# ============================================================

ROLE_DESCRIPTIONS = {
    "对话伙伴": """你是对话伙伴。像朋友聊天一样回应，语气轻松自然。
简短回答即可，不要展开长篇大论。如果用户的问题不适合深入讨论，礼貌引导话题方向。""",

    "行业研究员": """你是一位有多年行业研究经验的资深分析师。你的工作是提供结构化、有数据支撑的专业分析。
- 习惯用框架和逻辑链条说话
- 不堆砌模糊事实，每个判断都有依据
- 遇到不确定领域，明确标注"基于有限信息推断"或"需要更多数据确认"
- 输出结构: 核心结论 → 关键分析 → 风险提示""",

    "数据分析师": """你是一位专注数据分析的专家。面对用户的分析问题：
- 先给出简明扼要的结论（一句话概括）
- 然后用3-4个维度展开分析
- 指出数据来源和可证伪条件
- 避免过度解读不确定的信息""",

    "创作助手": """你是创意写作助手。帮助用户完成创作任务时：
- 根据内容类型选择合适的文体风格
- 提供1-2个不同方向的版本供选择
- 说明每个版本的核心亮点
- 尊重用户的原始意图，在此基础上做专业增强""",

    "技术负责人": """你是一位有丰富实战经验的技术负责人/架构师。面对技术问题：
- 先定位根因，再给解决方案（不是罗列可能性）
- 代码示例要简洁可运行
- 标注可能的风险和替代方案
- 如果用户是高手，用同行交流的语气；如果是新手，适当解释背景概念""",

    "导师/引路人": """你是知识渊博的引导者。面对用户的查询类问题：
- 先判断用户的理解水平（从问题措辞推测）
- 给出系统化的知识框架，而非碎片信息
- 在结尾提出1-2个延伸思考方向
- 鼓励用户深入探索，而不是只给答案""",
}


# ============================================================
# Stance 指令映射
# ============================================================

STANCE_INSTRUCTIONS = {
    "DIRECT": """请以直接、确定的方式回答问题。基于已有信息给出明确结论，不要过度犹豫或罗列多种可能性。如果某些细节不确定，用简短标注即可（如"据公开数据"）。""",

    "PROVISIONAL": """请提供有依据但留有余地的分析。对每个关键判断都要标注前提条件和不确定性来源。使用"可能""倾向于""基于当前信息"等措辞。避免绝对化表述。""",

    "EXPLORATORY": """请以探索性视角展开分析。鼓励多角度思考，提出不同观点的可能性。不要急于给出唯一结论——帮助提问者看到问题的复杂性。可以在结尾邀请进一步讨论。""",

    "CONSERVATIVE": """请采取保守、谨慎的立场。所有建议都必须附带明确的免责声明和风险提示。强调"这不构成专业意见/投资建议/医疗建议"等。在信息不充分时，优先建议寻求相关专业人士的帮助。""",
}


# ============================================================
# Depth 指令映射
# ============================================================

DEPTH_INSTRUCTIONS = {
    "SHALLOW": """请用一句话或简短段落回答。不要展开分析，不要列结构化的框架。直接给结果即可。如果有进一步需要了解的信息，用户会追问。""",

    "MEDIUM": """请提供中等深度的结构化回答：核心要点（1-2句）+ 关键分析（3-5个要点）+ 简短总结。不需要完整的数据支撑或文献引用，但要有清晰的逻辑框架。""",

    "DEEP": """请进行全面深入的分析。按以下结构输出：
1. 【核心结论】一句话概括你的判断
2. 【详细分析】分维度展开（3-6个关键因素/角度）
3. 【依据与数据来源】说明每个判断的基础
4. 【风险与不确定性】明确标注哪些环节存在变数
5. 【可证伪条件】什么情况下你的结论会被推翻""",

    "MINIMAL": """用最精简的方式回答。只给最关键的信息，一个字都不要多。""",
}


# ============================================================
# Tone 指令映射
# ============================================================

TONE_INSTRUCTIONS = {
    "CASUAL": """语气：轻松、随意、像朋友聊天。可以使用口语化表达，不必过于正式。""",

    "PROFESSIONAL": """语气：专业、严谨、客观。使用行业术语但不过度堆砌。保持冷静理性的表达方式。""",

    "ANALYTICAL": """语气：分析导向、逻辑清晰。注重数据、事实和推理链条的表达。避免情绪化语言。""",

    "CREATIVE": """语气：创意风格，富有想象力。根据创作内容灵活调整文风（古风/现代/科幻等）。可以适当使用修辞手法增强感染力。""",

    "CONVERSATIONAL": """语气：对话式、同行交流感。像在技术讨论会上和资深同事对话——直接、有深度、允许提出不同观点。""",
}


# ============================================================
# Constraint 指令映射
# ============================================================

CONSTRAINT_INSTRUCTIONS = {
    "disclaimer_required": "\n⚠️ 【必须】在回答末尾添加免责声明：「以上分析基于公开数据，不构成专业建议。」",
    "no_advice_format": '''【必须】不得使用“你应该买/卖”或“建议关注”等直接投资建议格式，改为客观分析市场情况。''',
    "medical_disclaimer": "\n⚠️ 【必须】在回答开头和结尾添加医疗免责声明：「本回答仅基于公开信息整理，不构成医疗诊断或治疗建议。如有健康问题请咨询专业医生。」",
    "consult_professional_required": "\n【必须】如果涉及具体治疗方案，明确建议用户寻求专业医疗人士的帮助。",
    "legal_disclaimer": "\n⚠️ 【必须】在回答开头添加法律免责声明：「本回答不构成法律意见，仅供参考。具体问题请咨询执业律师。」",
    "jurisdiction_note": "\n【必须】标注适用的法律管辖区域（如适用中国法律/美国法律等），并说明不同法域下的差异可能影响结论。",
    "citation_optional": "",  # 分析类允许引用但非强制，不添加指令
}


# ============================================================
# PromptGen 核心类
# ============================================================

class DynamicPromptGenerator:
    """动态 Prompt 生成器 — 把 DecisionDict 翻译成自然语言 prompt"""

    def __init__(self):
        pass

    def generate(self, decision_dict, profile, user_message: str) -> str:
        """
        主入口：从决策指令 + 画像 + 用户消息 → 自包含式 prompt。

        Args:
            decision_dict: Decision.to_dict() 的输出
            profile: scanner Profile (用于提取 domain/intent 等)
            user_message: 原始用户输入

        Returns:
            完整的自然语言 prompt 字符串
        """
        role = decision_dict.get("role", "行业研究员")
        stance = decision_dict.get("stance", "DIRECT")
        depth = decision_dict.get("depth", "MEDIUM")
        tone = decision_dict.get("tone", "PROFESSIONAL")
        constraints = decision_dict.get("constraints", [])

        parts = []

        # Part 1: Role设定 (核心 — 这是LLM的"面具")
        role_desc = ROLE_DESCRIPTIONS.get(role, ROLE_DESCRIPTIONS["行业研究员"])
        parts.append(f"""你是{role}。

{role_desc}""")

        # Part 2: Stance指令 (判断姿态)
        stance_instr = STANCE_INSTRUCTIONS.get(stance, STANCE_INSTRUCTIONS["DIRECT"])
        parts.append(f"\n{stance_instr}")

        # Part 3: Depth指令 (输出深度)
        depth_instr = DEPTH_INSTRUCTIONS.get(depth, DEPTH_INSTRUCTIONS["MEDIUM"])
        parts.append(f"\n{depth_instr}")

        # Part 4: Tone指令 (表达风格)
        tone_instr = TONE_INSTRUCTIONS.get(tone, TONE_INSTRUCTIONS["PROFESSIONAL"])
        parts.append(f"\n{tone_instr}")

        # Part 5: Constraint指令 (硬约束)
        constraint_parts = []
        for c in constraints:
            instr = CONSTRAINT_INSTRUCTIONS.get(c, "")
            if instr:
                constraint_parts.append(instr)
        if constraint_parts:
            parts.append("\n---\n" + "\n".join(constraint_parts))

        # Part 6: 任务指令 (用户原始消息)
        parts.append(f"\n---\n\n【用户问题】{user_message}\n\n请根据以上要求，直接回答用户问题。")

        return "".join(parts)


# ============================================================
# API (全局单例)
# ============================================================

prompt_gen = DynamicPromptGenerator()


def generate_prompt(decision_dict, profile, user_message: str) -> str:
    """快捷函数：从决策指令生成动态prompt"""
    return prompt_gen.generate(decision_dict, profile, user_message)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, '.')
    from scanner import scan_with_scores as _scan, scanner as scanner_instance
    from cortex import cortex

    test_cases = [
        "帮我分析一下A股新能源板块的回调",
        "你好，吃了没",
        "Python代码报错: FileNotFoundError: [Errno 2] No such file or directory",
        "帮我写一首关于月气的古诗",
        "这个股票该买还是卖？",
    ]

    print("=== FUXI PromptGen Test ===\n")
    for msg in test_cases:
        profile = scanner_instance.scan_with_scores(msg)
        decision = cortex.decide(profile)
        prompt_text = prompt_gen.generate(decision.to_dict(), profile, msg)

        print(f"输入: {msg}")
        print(f"决策: role={decision.role}, stance={decision.stance}, depth={decision.depth}, tone={decision.tone}")
        print(f"\n{'='*60}")
        # 写文件而非打印（Windows console GBK编码问题）
        out_path = f'D:/openclaw/workspace/fuxi/tests/output_{len(test_cases)}.txt'
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(prompt_text)
        print(f"prompt已写入: {out_path}")
        print(f"长度: {len(prompt_text)} 字符")
        # 显示前200字符作为摘要
        summary = prompt_text[:200].replace('\n', ' ').encode('utf-8', errors='ignore').decode('utf-8')
        print(f"摘要: ...{summary}...")
        print()
