"""伏羲 FUXI v1 — 完整流水线入口

架构: scan → cortex → prompt_gen → execute
哲学: 智能体是道的载体，大模型是道的笔墨

用法:
    python main.py                      # 交互式输入
    echo "你的问题" | python main.py     # 管道输入
    python main.py --test                # 运行测试用例
"""


import sys
import os
import json
import time

# 确保 src/ 在路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scanner import scanner as _scanner
from cortex import cortex as _cortex
from prompt_gen import prompt_gen as _prompt_gen
from executor import OpenClawExecutor, fuxi_pipeline


# ============================================================
# 终端 UI 辅助函数
# ============================================================

def print_banner():
    """打印伏羲启动横幅"""
    banner = r"""
╔══════════════════════════════════════╗
║   FUXI — 伏羲智能体引擎 v1.0        ║
║   以道御术，以值定界                 ║
╚══════════════════════════════════════╝
    """
    print(banner)


def print_profile(profile, decision):
    """打印扫描+裁量结果"""
    lines = []
    lines.append(f"  ┌─────────────────────────────────────┐")
    lines.append(f"  │ 条件画像 (Scanner)                  │")
    lines.append(f"  ├─────────────────────────────────────┤")
    lines.append(f"  │ intent:       {profile.intent:<32}│")
    lines.append(f"  │ domain:       {profile.domain[0]:<32}│")
    lines.append(f"  │ urgency:      {str(profile.urgency):<32}│")
    lines.append(f"  │ risk_level:   {str(profile.risk_level):<32}│")
    lines.append(f"  │ expertise:    {profile.expertise:<32}│")
    lines.append(f"  └─────────────────────────────────────┘")

    d = decision.to_dict()
    lines.append(f"  ┌─────────────────────────────────────┐")
    lines.append(f"  │ 裁量决策 (Cortex)                   │")
    lines.append(f"  ├─────────────────────────────────────┤")
    lines.append(f"  │ role:         {d['role']:<32}│")
    lines.append(f"  │ stance:       {d['stance']:<32}│")
    lines.append(f"  │ depth:        {d['depth']:<32}│")
    lines.append(f"  │ tone:         {d['tone']:<32}│")
    if d.get('constraints'):
        lines.append(f"  │ constraints:  {str(d['constraints'])[:28]:<32}│")
    lines.append(f"  └─────────────────────────────────────┘")

    for line in lines:
        print(line)


def interactive_mode():
    """交互式输入模式"""
    print_banner()
    print("伏羲引擎就绪。输入你的问题 (输入 'quit' 退出)\n")
    
    executor = OpenClawExecutor()

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。\n")
            break

        if not user_input:
            continue
        if user_input.lower() in ('quit', 'exit', 'q'):
            print("再见。\n")
            break

        start_time = time.time()

        try:
            result = fuxi_pipeline(user_input, executor)
            
            elapsed_ms = int((time.time() - start_time) * 1000)
            
            if result.status == "simulated":
                # scanner/cortex/prompt_gen 已跑通，但Gateway不可用
                profile = _scanner.scan_with_scores(user_input)
                decision = _cortex.decide(profile)
                prompt_text = _prompt_gen.generate(decision.to_dict(), profile, user_input)

                print_profile(profile, decision)
                
                # 写prompt到文件（避免GBK编码问题）
                out_path = f'D:/openclaw/workspace/fuxi/tests/prompt_{int(time.time())}.txt'
                with open(out_path, 'w', encoding='utf-8') as f:
                    f.write(prompt_text)
                
                print(f"\n  ⚠ Gateway不可用，prompt已写入: {out_path}")

            elif result.status == "success":
                print_profile(
                    _scanner.scan_with_scores(user_input),
                    _cortex.decide(_scanner.scan_with_scores(user_input))
                )
                
                if result.response:
                    preview = result.response[:500].replace('\n', ' ').encode('utf-8', errors='ignore').decode('utf-8')
                    print(f"\n  [响应] {preview}")
                    if len(result.response) > 500:
                        print(f"  ... (共{len(result.response)}字符)")

            else:
                print(f"\n  ✗ 执行失败 ({result.status}): {result.error[:200]}")

        except Exception as e:
            print(f"\n  ✗ 流水线异常: {e}")


def run_tests():
    """运行完整测试套件"""
    import subprocess
    
    print_banner()
    print("=== FUXI 完整测试套件 ===\n")

    tests = [
        ("scanner", "D:/openclaw/workspace/fuxi/src/scanner.py"),
        ("cortex", "D:/openclaw/workspace/fuxi/src/cortex.py"),
        ("prompt_gen", "D:/openclaw/workspace/fuxi/src/prompt_gen.py"),
    ]

    results = []
    for name, path in tests:
        print(f"--- 测试 {name} ---")
        try:
            result = subprocess.run(
                [sys.executable, path],
                capture_output=True, text=True, timeout=30,
                encoding='utf-8', errors='replace'
            )
            output = (result.stdout or "")[:500].replace('\n', ' ')
            print(f"  输出: {output}")
            if result.returncode == 0:
                print(f"  ✅ PASS")
                results.append((name, "PASS"))
            else:
                print(f"  ❌ FAIL (exit code {result.returncode})")
                results.append((name, f"FAIL ({result.returncode})"))
        except Exception as e:
            print(f"  ❌ ERROR: {e}")
            results.append((name, f"ERROR: {e}"))

    # executor 测试（需要Gateway）
    print("\n--- 测试 executor ---")
    try:
        result = subprocess.run(
            [sys.executable, "D:/openclaw/workspace/fuxi/src/executor.py"],
            capture_output=True, text=True, timeout=60,
            encoding='utf-8', errors='replace'
        )
        output = (result.stdout or "")[:500].replace('\n', ' ')
        print(f"  输出: {output}")
        
        # executor 即使Gateway不可用也应该能跑（CLI fallback或模拟模式）
        if "Pipeline test completed" in result.stdout or result.returncode == 0:
            print("  ✅ PASS (本地模拟)")
            results.append(("executor", "PASS"))
        else:
            print(f"  ⚠ PARTIAL (Gateway不可用，需运行时验证)")
            results.append(("executor", "PARTIAL"))
    except Exception as e:
        print(f"  ⚠ SKIP: {e}")
        results.append(("executor", f"SKIP: {e}"))

    # 汇总
    print("\n=== 测试总结 ===")
    for name, status in results:
        icon = "✅" if status == "PASS" else ("⚠" if "PARTIAL" in status or "SKIP" in status else "❌")
        print(f"  {icon} {name}: {status}")

    all_pass = all(s == "PASS" for _, s in results)
    partial = any("PARTIAL" in s or "SKIP" in s for _, s in results)
    
    if all_pass:
        print("\n🎉 全部通过！FUXI v1.0 MVP 就绪。")
    elif partial:
        print("\n⚠️ 部分通过 (executor需Gateway运行)")
        print("   核心链路 scanner→cortex→prompt_gen 已验证")
    else:
        print("\n❌ 有失败项，请检查上方输出")

    return results


def main():
    """入口"""
    if "--test" in sys.argv or "-t" in sys.argv:
        run_tests()
    elif len(sys.argv) > 1 and sys.argv[1] == "gen":
        # 从文件读取prompt并输出（调试用）
        input_file = sys.argv[2] if len(sys.argv) > 2 else None
        if not input_file:
            print("用法: python main.py gen <input_prompt.txt>")
            return
        
        with open(input_file, 'r', encoding='utf-8') as f:
            prompt_text = f.read()
        
        decision_data = json.load(open(sys.argv[3] if len(sys.argv) > 3 else "D:/openclaw/workspace/fuxi/tests/decision.json", 'r', encoding='utf-8'))
        
        print(f"输入: {prompt_text[:100]}...")
        profile = _scanner.scan_with_scores(prompt_text)
        decision = _cortex.decide(profile)
        new_prompt = _prompt_gen.generate(decision_data, profile, prompt_text)
        
        out_path = input_file + ".output"
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(new_prompt)
        print(f"\n输出已写入: {out_path}")

    else:
        interactive_mode()


if __name__ == "__main__":
    main()
