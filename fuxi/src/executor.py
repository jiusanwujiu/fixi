"""伏羲 executor v1 — OpenClaw Gateway API 适配层

职责:
- 接收动态prompt，通过 OpenClaw Gateway REST API 执行
- 使用 isolated session (mode="run") 最小化系统模板干扰
- 返回LLM响应结果

架构说明:
- OpenClaw 无 Python SDK → 直接调用 Gateway HTTP API
- Gateway 默认 http://127.0.0.1:1234，token 从环境变量读取
- isolated session 虽然仍会注入 SOUL.md/AGENTS.md/MEMORY.md，
  但不会混入主 session 的对话历史，prompt 可控性远高于 main session

替代方案（如果 Gateway API 不可用）:
- CLI fallback: openclaw run --file <tmp_prompt.txt>
"""


import sys
import os
import json
import time
from dataclasses import dataclass, asdict

try:
    from urllib.request import Request, urlopen
except ImportError:
    # Python 3.10+ fallback (Windows should have this)
    import http.client
    import ssl


# ============================================================
# Gateway HTTP API 客户端
# ============================================================

def _gateway_request(endpoint: str, method: str = "GET", body: dict = None, 
                      base_url=None, token=None, timeout=120) -> dict:
    """发送 Gateway HTTP 请求 → JSON 响应"""
    
    gateway_url = base_url or os.environ.get("OPENCLAW_GATEWAY_URL")
    gateway_token = token or os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")
    
    if not gateway_url:
        # 默认本地端口
        gateway_url = "http://127.0.0.1:1234"

    url = f"{gateway_url}{endpoint}"
    
    headers = {
        "Content-Type": "application/json",
    }
    if gateway_token:
        headers["Authorization"] = f"Bearer {gateway_token}"

    data = json.dumps(body).encode("utf-8") if body else None
    
    req = Request(url, data=data, headers=headers, method=method)

    try:
        resp = urlopen(req, timeout=timeout)
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw.strip() else {}
    except Exception as e:
        raise RuntimeError(f"Gateway request failed ({endpoint}): {e}")


# ============================================================
# 执行结果
# ============================================================

@dataclass
class ExecutionResult:
    """执行结果"""
    status: str                    # "success" | "failed" | "cancelled" | "timeout"
    response: str                  # LLM响应文本 (可能为空)
    session_key: str               # 使用的session标识
    latency_ms: int                # 耗时(毫秒)，-1如果未知
    error: str                     # 错误信息，成功时空

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# OpenClaw Gateway Executor
# ============================================================

class OpenClawExecutor:
    """通过 OpenClaw Gateway REST API 执行动态prompt"""

    def __init__(self, base_url=None, token=None):
        self.base_url = base_url or os.environ.get("OPENCLAW_GATEWAY_URL")
        self.token = token or os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")

    def execute(self, prompt_text: str, model=None, timeout_seconds=60) -> ExecutionResult:
        """
        通过 isolated session (agentTurn payload) 执行动态prompt。

        Args:
            prompt_text: DynamicPromptGenerator生成的完整prompt
            model: 可选的模型覆盖 (如"qwen3.6-35b")
            timeout_seconds: 超时秒数（Gateway会等待完成）

        Returns:
            ExecutionResult 实例
        """
        import time as _time
        start = _time.time()

        try:
            return self._execute_via_gateway(prompt_text, model, timeout_seconds)

        except Exception as e:
            latency_ms = int((_time.time() - start) * 1000)
            return ExecutionResult(
                status="failed",
                response="",
                session_key="",
                latency_ms=latency_ms,
                error=str(e)
            )

    def _execute_via_gateway(self, prompt_text: str, model=None, timeout_seconds=60) -> ExecutionResult:
        """通过 Gateway /api/sessions 创建 isolated agentTurn session"""
        import time as _time
        start = _time.time()

        # 构造 payload — isolated session + agentTurn
        payload = {
            "sessionTarget": "isolated",
            "payload": {
                "kind": "agentTurn",
                "message": prompt_text,
            }
        }

        if model:
            payload["payload"]["model"] = model

        # 尝试通过 /api/sessions/spawn 创建 session
        try:
            result = _gateway_request(
                "/api/sessions/spawn",
                method="POST",
                body=payload,
                base_url=self.base_url,
                token=self.token,
                timeout=timeout_seconds + 30  # 额外缓冲
            )

            latency_ms = int((_time.time() - start) * 1000)

            # Gateway spawn 返回格式可能是: { sessionId, sessionKey, ... }
            session_id = result.get("sessionId") or result.get("sessionKey", "")
            
            if not session_id and "error" in str(result):
                return ExecutionResult(
                    status="failed",
                    response="",
                    session_key="",
                    latency_ms=latency_ms,
                    error=json.dumps(result, ensure_ascii=False)
                )

            # 等待 session 完成 — 轮询状态（Gateway 可能不直接返回完整响应）
            response_text = self._wait_for_completion(session_id, timeout_seconds)

            return ExecutionResult(
                status="success" if response_text else "timeout",
                response=response_text or "",
                session_key=session_id,
                latency_ms=int((_time.time() - start) * 1000),
                error="" if response_text else f"Session returned but no content: {result}"
            )

        except RuntimeError as e:
            # Gateway API 不可达 → fallback
            return self._execute_via_cli_fallback(prompt_text, model)

    def _wait_for_completion(self, session_id: str, timeout_seconds: int) -> str:
        """轮询 session 状态直到完成并获取响应"""
        import time as _time
        
        # Gateway API 通常不直接提供 /api/sessions/{id}/status
        # isolated agentTurn 会在完成后通过 announce 机制推送结果
        # 
        # 由于我们无法真正等待异步事件，采用以下策略:
        # 1. 如果 spawn 返回了完整 response → 直接用
        # 2. 否则返回空字符串，由上层决定如何处理

        return ""  # async spawn, result handled by announce mechanism

    def _execute_via_cli_fallback(self, prompt_text: str, model=None) -> ExecutionResult:
        """CLI fallback — Gateway API 不可达时通过 openclaw CLI 执行"""
        import subprocess
        import tempfile
        import time

        try:
            # 写临时文件
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                f.write(prompt_text)
                tmp_path = f.name

            try:
                cmd = ["openclaw", "run", "--file", tmp_path]
                if model:
                    cmd.extend(["--model", model])

                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=120,
                    encoding='utf-8', errors='replace'
                )
                
                response = (result.stdout or result.stderr).strip()
                
                return ExecutionResult(
                    status="success" if response else "failed",
                    response=response[:5000],  # 截断超长响应
                    session_key="cli-fallback",
                    latency_ms=-1,
                    error="" if response else f"CLI exited with code {result.returncode}"
                )

            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return ExecutionResult(
                status="failed",
                response="",
                session_key="",
                latency_ms=-1,
                error=f"CLI fallback failed: {e}"
            )


# ============================================================
# 完整流水线入口 — scan → cortex → prompt_gen → execute
# ============================================================

def fuxi_pipeline(user_message: str, executor: OpenClawExecutor = None) -> ExecutionResult:
    """
    伏羲完整流水线 — 从用户消息到LLM响应。

    流程:
        user_message → scanner.scan() → cortex.decide()
            → prompt_gen.generate() → executor.execute()

    Args:
        user_message: 原始用户输入
        executor: OpenClawExecutor实例 (None=自动创建)

    Returns:
        ExecutionResult — LLM响应结果
    """
    from scanner import scan_with_scores, scanner as _scanner
    from cortex import cortex as _cortex
    from prompt_gen import prompt_gen as _prompt_gen

    # Step 1: 扫描 (条件画像)
    profile = _scanner.scan_with_scores(user_message)

    # Step 2: 裁量 (决策指令)
    decision = _cortex.decide(profile)

    # Step 3: Prompt生成 (笔墨)
    prompt_text = _prompt_gen.generate(decision.to_dict(), profile, user_message)

    # Step 4: 执行 (隔离session → LLM → 响应)
    if executor is None:
        executor = OpenClawExecutor()

    result = executor.execute(prompt_text)

    return result


if __name__ == "__main__":
    print("=== FUXI Executor Test ===\n")
    
    # 单元测试: 验证各步骤衔接 (不依赖Gateway服务)
    from scanner import scan_with_scores as _scan, scanner as _scanner
    from cortex import cortex as _cortex
    from prompt_gen import prompt_gen as _prompt_gen

    test_cases = [
        "帮我分析一下A股新能源板块的回调",
        "Python代码报错: FileNotFoundError: [Errno 2] No such file or directory",
        "你好，吃了没？今天心情不错。",
    ]

    for msg in test_cases:
        print(f"输入: {msg}")
        
        # Step 1-3: 扫描 + 裁量 + Prompt生成 (纯逻辑, 不需要Gateway)
        profile = _scanner.scan_with_scores(msg)
        decision = _cortex.decide(profile)
        prompt_text = _prompt_gen.generate(decision.to_dict(), profile, msg)

        print(f"  scanner: intent={profile.intent}, domain={profile.domain[0]}, risk={profile.risk_level}")
        print(f"  cortex: role={decision.role}, stance={decision.stance.value}, depth={decision.depth.value}")
        print(f"  prompt_gen: {len(prompt_text)} chars")

        # Step 4: executor (需要Gateway运行)
        try:
            executor = OpenClawExecutor()
            result = executor.execute(prompt_text, timeout_seconds=30)
            print(f"  executor: {result.status} ({result.latency_ms}ms)")
            if result.response:
                preview = result.response[:150].replace('\n', ' ').encode('utf-8', errors='ignore').decode('utf-8')
                print(f"    response: ...{preview}...")
        except Exception as e:
            print(f"  executor: Gateway不可用 ({e}) → CLI fallback 或模拟")

        print()
