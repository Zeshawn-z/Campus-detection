"""
LLM 链式推理模块 - AI Agent 循环
- 实现完整的 Agent 循环："计划-执行-观察-再计划"
- 支持真正的流式输出，每个步骤实时传输
- 集成模糊搜索工具，确保不编造ID
- 与前端步骤显示组件完全兼容
"""
from __future__ import annotations

from typing import List, Dict, Any, AsyncGenerator, Optional
import json
import logging
import asyncio

from langchain.schema import SystemMessage, HumanMessage, AIMessage, BaseMessage
from langchain.prompts import ChatPromptTemplate

from .utils import get_llm_client, stream_chat_response, run_llm_with_retry
from .prompts import get_chat_prompt_with_history, get_agent_planner_prompt
from .memory import ChatMemoryStore, normalize_frontend_history
from . import tools as campus_tools
from channels.db import database_sync_to_async

logger = logging.getLogger(__name__)


def _split_text(text: str, piece_size: int = 12) -> List[str]:
    """将文本切分为更小片段，提升前端可见的流式粒度。"""
    if not text:
        return []
    return [text[i:i + piece_size] for i in range(0, len(text), piece_size)]


def build_basic_chat_chain():
    """构建基础对话链（不带工具）"""
    llm = get_llm_client(temperature=0.6, model_type="fast")
    return llm


async def _get_available_tools_spec() -> str:
    """获取可用工具的规格说明"""
    tools_spec = """
**模糊搜索工具**：
- fuzzy_search_areas(query: str, category: str | None = None) -> List[Dict]: 模糊搜索区域，支持区域名、建筑名、楼层等关键词；可选按建筑类型过滤
- fuzzy_search_buildings(query: str) -> List[Dict]: 模糊搜索建筑
- fuzzy_search_terminals(query: str) -> List[Dict]: 模糊搜索终端

**精确查询工具**（需要确切ID）:
- get_area_status(area_id: int) -> Dict: 获取指定区域的综合状态（人流、环境、告警）
- get_terminal_status(terminal_id: int) -> Dict: 获取指定终端的状态（CPU、内存、磁盘）
- get_suggested_areas(limit: int = 5, category: str | None = None) -> List[Dict]: 获取推荐区域列表；可选按建筑类型过滤

**历史数据工具**：
- get_area_trend(area_id: int, hours: int = 6) -> List[Dict]: 获取区域人流趋势
- get_area_extremes(area_id: int, hours: int = 24) -> Dict: 获取区域极值数据
- get_recent_alerts(area_id: int = None, limit: int = 10) -> List[Dict]: 获取告警信息
- get_environment_snapshots(area_id: int, hours: int = 6) -> List[Dict]: 获取环境数据快照

**资源导航工具**：
- get_campus_resources(query: str = "") -> List[Dict]: 根据关键词获取校园服务资源链接
- get_general_campus_info() -> Dict: 获取AI助手身份信息和校园基础信息

【重要】工具是可选的：当用户问题不需要调用工具（如闲聊、一般咨询、与数据无关的问答）时，请选择 direct_response 并直接作答。
【自由问答】允许回答与校园无关的通用问题，不要因为超出领域而拒答（仅在内容受限时才拒绝）。

【可选建筑类型（category枚举）】：
- library, study, teaching, cafeteria, dorm, lab, office, sports, service, other
"""
    return tools_spec


async def _execute_tool(tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """执行具体的工具调用"""
    try:
        if tool_name == "fuzzy_search_areas":
            result = await database_sync_to_async(campus_tools.fuzzy_search_areas, thread_sensitive=False)(
                parameters.get("query", ""), 
                parameters.get("category")
            )
        elif tool_name == "fuzzy_search_buildings":
            result = await database_sync_to_async(campus_tools.fuzzy_search_buildings, thread_sensitive=False)(parameters.get("query", ""))
        elif tool_name == "fuzzy_search_terminals":
            result = await database_sync_to_async(campus_tools.fuzzy_search_terminals, thread_sensitive=False)(parameters.get("query", ""))
        elif tool_name == "get_area_status":
            result = await database_sync_to_async(campus_tools.get_area_status, thread_sensitive=False)(parameters.get("area_id"))
        elif tool_name == "get_terminal_status":
            result = await database_sync_to_async(campus_tools.get_terminal_status, thread_sensitive=False)(parameters.get("terminal_id"))
        elif tool_name == "get_suggested_areas":
            result = await database_sync_to_async(campus_tools.get_suggested_areas, thread_sensitive=False)(
                limit=parameters.get("limit", 5),
                category=parameters.get("category")
            )
        elif tool_name == "get_area_trend":
            result = await database_sync_to_async(campus_tools.get_area_trend, thread_sensitive=False)(
                parameters.get("area_id"), parameters.get("hours", 6)
            )
        elif tool_name == "get_area_extremes":
            result = await database_sync_to_async(campus_tools.get_area_extremes, thread_sensitive=False)(
                parameters.get("area_id"), parameters.get("hours", 24)
            )
        elif tool_name == "get_recent_alerts":
            result = await database_sync_to_async(campus_tools.get_recent_alerts, thread_sensitive=False)(
                parameters.get("area_id"), parameters.get("limit", 10)
            )
        elif tool_name == "get_environment_snapshots":
            result = await database_sync_to_async(campus_tools.get_environment_snapshots, thread_sensitive=False)(
                parameters.get("area_id"), parameters.get("hours", 6)
            )
        elif tool_name == "get_campus_resources":
            result = await database_sync_to_async(campus_tools.get_campus_resources, thread_sensitive=False)(parameters.get("query", ""))
        elif tool_name == "get_general_campus_info":
            result = await database_sync_to_async(campus_tools.get_general_campus_info, thread_sensitive=False)()
        else:
            return {"error": f"Unknown tool: {tool_name}"}
        
        return {"success": True, "result": result}
    except Exception as e:
        logger.error(f"Tool execution error - {tool_name}: {e}")
        return {"error": str(e)}


async def _llm_plan_next_action_streaming(
    user_input: str, 
    history: str, 
    observations: str,
    planner_model: Optional[str] = None
) -> AsyncGenerator[tuple, None]:
    """使用流式LLM规划下一步行动，实时输出思考过程"""
    tools_spec = await _get_available_tools_spec()
    prompt = get_agent_planner_prompt(user_input, tools_spec, history, observations)
    
    messages = [
        SystemMessage(content="你是云小瞻的规划器，必须以标准JSON格式回复。若用户问题无需工具，请选择direct_response，但不要直接输出完整回答；请以outline给出回答大纲（3-6条）。允许自由问答，不限于校园领域；除非涉及受限内容，否则不要拒绝。"),
        HumanMessage(content=prompt)
    ]
    
    try:
        thinking_content = ""
        final_plan = {}
        
        # 使用较快模型进行规划（若未指定）
        model_for_planning = planner_model or "fast"

        # 增量 JSON 解析器状态（避免正则 O(n^2) 扫描与阻塞）
        in_string = False
        string_quote = ""
        escape = False
        depth = 0
        started = False
        json_buffer: list[str] = []

        # 流式获取LLM响应
        async for chunk in stream_chat_response(messages, temperature=0.1, model_type=model_for_planning):
            thinking_content += chunk
            if chunk.strip():
                yield ("thinking_chunk", chunk)

            # 增量扫描当前chunk，寻找首个平衡JSON
            for ch in chunk:
                if not started:
                    if ch == '{':
                        started = True
                        depth = 1
                        json_buffer = ['{']
                    # 未开始前忽略其它字符
                    continue

                # 已开始收集JSON
                json_buffer.append(ch)
                if escape:
                    escape = False
                    continue
                if in_string:
                    if ch == '\\':
                        escape = True
                    elif ch == string_quote:
                        in_string = False
                    continue
                else:
                    if ch == '"' or ch == "'":
                        in_string = True
                        string_quote = ch
                        continue
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            # 完整JSON收集完成
                            try:
                                plan_json = json.loads(''.join(json_buffer))
                                final_plan = plan_json
                            except Exception as _:
                                final_plan = {}
                            break
            if final_plan:
                break
        
        # 返回最终规划结果
        if final_plan:
            yield ("final_plan", final_plan)
        else:
            yield ("final_plan", {
                "reasoning": "LLM响应格式异常，使用默认处理",
                "action": "direct_response",
                "outline": ["请您提供更多上下文信息，例如具体问题或场景。"],
                "response": "抱歉，我在理解您的问题时遇到了困难。"
            })
    except Exception as e:
        logger.error(f"LLM规划失败: {e}")
        yield ("final_plan", {
            "reasoning": f"规划过程出错: {str(e)}",
            "action": "direct_response",
            "outline": ["稍后请重试，或换个问题描述。"],
            "response": "抱歉，处理您的请求时遇到了问题，请稍后重试。"
        })


async def _llm_plan_next_action(
    user_input: str, 
    history: str, 
    observations: str,
    planner_model: Optional[str] = None
) -> Dict[str, Any]:
    """使用 LLM 规划下一步行动（保留原始非流式接口用于兼容）"""
    tools_spec = await _get_available_tools_spec()
    prompt = get_agent_planner_prompt(user_input, tools_spec, history, observations)
    
    messages = [
        SystemMessage(content="你是云小瞻的规划器，必须以标准JSON格式回复。若用户问题无需工具，请选择direct_response，但不要直接输出完整回答；请以outline给出回答大纲（3-6条）。允许自由问答，不限于校园领域；除非涉及受限内容，否则不要拒绝。"),
        HumanMessage(content=prompt)
    ]
    
    try:
        # 使用较快模型进行规划（若未指定）
        model_for_planning = planner_model or "fast"

        result = await run_llm_with_retry(messages, temperature=0.1, model_type=model_for_planning)

        # 使用平衡括号的方式提取首个JSON，避免正则大文本阻塞
        def _extract_first_json(text: str) -> Optional[str]:
            in_string = False
            string_quote = ""
            escape = False
            depth = 0
            started = False
            buf: list[str] = []
            for ch in text:
                if not started:
                    if ch == '{':
                        started = True
                        depth = 1
                        buf = ['{']
                    continue
                buf.append(ch)
                if escape:
                    escape = False
                    continue
                if in_string:
                    if ch == '\\':
                        escape = True
                    elif ch == string_quote:
                        in_string = False
                    continue
                else:
                    if ch == '"' or ch == "'":
                        in_string = True
                        string_quote = ch
                        continue
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            return ''.join(buf)
            return None

        json_str = _extract_first_json(result or "")
        if json_str:
            return json.loads(json_str)
        else:
            return {
                "reasoning": "LLM响应格式异常，使用默认处理",
                "action": "direct_response",
                "outline": ["请您提供更多上下文信息，例如具体问题或场景。"],
                "response": "抱歉，我在理解您的问题时遇到了困难。"
            }
    except Exception as e:
        logger.error(f"LLM规划失败: {e}")
        return {
            "reasoning": f"规划过程出错: {str(e)}",
            "action": "direct_response",
            "outline": ["稍后请重试，或换个问题描述。"],
            "response": "抱歉，处理您的请求时遇到了问题，请稍后重试。"
        }


async def stream_route_and_respond(user_input: str, history: List[Dict] | None = None, model_type: Optional[str] = None) -> AsyncGenerator[str, None]:
    """
    AI Agent 流式循环：计划-执行-观察-再计划
    
    事件格式：
    - {"type": "chain_start", "message": "开始处理..."}
    - {"type": "agent_planning", "message": "AI正在分析和规划..."}
    - {"type": "thought", "content": "思考过程..."}
    - {"type": "plan", "action": "...", "tool_calls": [...]} 
    - {"type": "tool_execution", "tool": "工具名", "message": "执行工具..."}
    - {"type": "observation", "content": "观察结果...", "result_preview": "..."}
    - {"type": "agent_replanning", "message": "重新规划..."}
    - {"type": "final_generation", "message": "生成最终回答..."}
    - {"type": "content", "text": "实际内容"}
    - {"type": "chain_end", "message": "完成"}
    """
    
    try:
        # 步骤1: 开始处理
        yield json.dumps({
            "type": "chain_start", 
            "message": "正在处理您的请求..."
        }, ensure_ascii=False) + "\n"

        # 选择阶段模型：若前端指定非"default"，全程使用；否则按阶段选择
        use_custom = bool(model_type and model_type != "default")
        planner_model = model_type if use_custom else "fast"
        generation_model = model_type if use_custom else "analysis"

        # 准备历史信息
        history_text = ""
        if history:
            for msg in history[-5:]:  # 限制历史长度
                role = msg.get("role", "")
                content = msg.get("content", "")
                history_text += f"{role}: {content}\n"
        
        observations = ""
        max_iterations = 3  # 最大迭代次数，防止无限循环
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            
            # 步骤2: AI规划
            yield json.dumps({
                "type": "agent_planning", 
                "iteration": iteration,
                "message": "正在分析问题并规划执行步骤...",
                "model": planner_model  # 新增：标注使用的规划模型
            }, ensure_ascii=False) + "\n"
            
            # 规划阶段仅输出最终可读计划，避免把JSON草稿流式暴露给前端造成步骤噪声。
            plan = {}
            async for event_type, data in _llm_plan_next_action_streaming(user_input, history_text, observations, planner_model):
                if event_type == "final_plan":
                    plan = data
                    break
            
            # 步骤3: 展示思考过程
            yield json.dumps({
                "type": "thought",
                "content": plan.get("reasoning", "分析用户需求...")
            }, ensure_ascii=False) + "\n"

            # 步骤3.5: 输出规划详情（行动与工具调用计划）
            action = plan.get("action", "direct_response")
            tool_calls = plan.get("tool_calls", [])
            outline = plan.get("outline", None)
            yield json.dumps({
                "type": "plan",
                "iteration": iteration,
                "action": action,
                "tool_calls": tool_calls,
                "outline": outline,
                "model": planner_model  # 新增：标注规划输出所用模型
            }, ensure_ascii=False) + "\n"
            
            # 根据规划执行不同的行动
            if action == "call_tool":
                used_fuzzy = False
                
                for tool_call in tool_calls:
                    tool_name = tool_call.get("tool", "")
                    parameters = tool_call.get("parameters", {})
                    tool_reasoning = tool_call.get("reasoning", "")
                    
                    # 步骤4: 工具执行
                    yield json.dumps({
                        "type": "tool_execution",
                        "tool": tool_name,
                        "parameters": parameters,
                        "message": f"🔧 执行工具: {tool_name}",
                        "reasoning": tool_reasoning
                    }, ensure_ascii=False) + "\n"
                    
                    # 执行工具
                    result = await _execute_tool(tool_name, parameters)
                    
                    # 步骤5: 观察结果
                    if result.get("success"):
                        # 将结果序列化，提供预览内容（避免过长）
                        try:
                            result_json = json.dumps(result["result"], ensure_ascii=False)
                        except Exception:
                            result_json = str(result.get("result"))
                        preview = result_json if len(result_json) <= 1200 else (result_json[:1200] + "...")
                        observation = f"工具 {tool_name} 执行成功，结果: {preview}"
                        yield json.dumps({
                            "type": "observation",
                            "tool": tool_name,
                            "success": True,
                            "content": f"✅ {tool_name} 执行成功",
                            "result_preview": preview
                        }, ensure_ascii=False) + "\n"
                    else:
                        error_msg = result.get('error', '未知错误')
                        observation = f"工具 {tool_name} 执行失败: {error_msg}"
                        yield json.dumps({
                            "type": "observation", 
                            "tool": tool_name,
                            "success": False,
                            "content": f"❌ {tool_name} 执行失败: {error_msg}",
                            "error": error_msg
                        }, ensure_ascii=False) + "\n"
                        
                    observations += observation + "\n"
                    if tool_name.startswith("fuzzy_search"):
                        used_fuzzy = True
                
                # 判断是否需要继续规划
                if used_fuzzy and iteration < max_iterations:
                    # 如果执行了模糊搜索，可能需要进一步的精确查询
                    yield json.dumps({
                        "type": "agent_replanning",
                        "message": "🔄 基于搜索结果，重新规划下一步..."
                    }, ensure_ascii=False) + "\n"
                    continue
                else:
                    # 有了足够信息，生成最终回答
                    break
            
            elif action == "direct_response":
                # 不直接输出最终回答；进入统一最终生成阶段
                break
            
            else:
                observations += f"未知行动类型: {action}\n"
                break
        
        # 步骤6: 生成最终回答
        yield json.dumps({
            "type": "final_generation",
            "message": "生成最终回答...",
            "model": generation_model  # 新增：标注用于最终生成的模型
        }, ensure_ascii=False) + "\n"

        # 统一最终生成逻辑：融合大纲/草案/观察结果
        planner_outline = (plan.get("outline") or [])
        planner_response_hint = plan.get("response", "")
        # 统一上下文
        context_parts = [
            f"用户问题: {user_input}"
        ]
        if planner_outline:
            bullets = "\n".join(f"- {item}" for item in planner_outline if item)
            context_parts.append(f"规划器提供的大纲:\n{bullets}")
        if planner_response_hint:
            context_parts.append(f"规划器的一句话草案:\n{planner_response_hint}")
        if observations.strip():
            context_parts.append(f"获得的信息（工具/搜索观察）:\n{observations.strip()}")
        context_parts.append("请基于以上信息，生成结构清晰、简洁有用的最终回答。若信息不足，请明确说明并给出下一步建议。")
        context = "\n\n".join(context_parts)

        messages = [
            SystemMessage(content="你是校园智能助手“云小瞻”。请基于规划大纲与可用信息生成最终回答。允许自由问答，不限于校园领域；除非涉及受限内容，否则不要拒绝。"),
            HumanMessage(content=context)
        ]
        async for chunk in stream_chat_response(messages, temperature=0.5, model_type=generation_model):
            for piece in _split_text(chunk, piece_size=12):
                yield json.dumps({"type": "content", "text": piece}, ensure_ascii=False) + "\n"
                await asyncio.sleep(0)

        # 步骤8: 结束标识
        yield json.dumps({
            "type": "chain_end",
            "message": "完成"
        }, ensure_ascii=False) + "\n"
        
    except Exception as e:
        logger.error(f"Agent循环出错: {e}")
        yield json.dumps({
            "type": "error",
            "message": f"❌ 处理出错: {str(e)}"
        }, ensure_ascii=False) + "\n"

