/**
 * LLM 服务模块
 * 提供与 LLM 后端 API 通信的功能，支持对话持久化
 */
import { http } from '../network';
import { API_BASE_URL } from '../network/axios';

// 聊天消息格式
export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

// 聊天历史
export type ChatHistory = ChatMessage[];

// 会话信息
export interface ChatSessionInfo {
  id: number;
  session_id: string;
  title: string;
  model_type: string;
  created_at: string;
  updated_at: string;
  is_archived: boolean;
  message_count: number;
  last_message?: {
    role: string;
    content: string;
    created_at: string;
  };
}

// 会话详情（含消息列表）
export interface ChatSessionDetail extends ChatSessionInfo {
  messages: Array<{
    id: number;
    role: string;
    content: string;
    metadata: Record<string, any>;
    created_at: string;
  }>;
}

// API 响应类型
interface LLMChatResponse {
  response?: string;
  message?: string;
  status?: string;
}

interface LLMRecommendationResponse {
  data?: any[];
  message?: string;
  status?: string;
}

// LLM 基础 URL
const LLM_BASE_URL = API_BASE_URL + 'api/llm';

/**
 * 生成唯一的会话ID
 */
export function generateSessionId(): string {
  return 'sess_' + Date.now().toString(36) + '_' + Math.random().toString(36).substring(2, 10);
}

/**
 * 发送聊天消息（非流式）
 * @param message 用户消息
 * @param history 聊天历史
 * @returns Promise<string> AI响应
 */
export async function sendChatMessage(message: string, history: ChatHistory = []): Promise<string> {
  try {
    // 添加类型断言解决属性访问问题
    const response = await http.post<LLMChatResponse>(`${LLM_BASE_URL}/chat/`, { message, history });
    return response.response || '';
  } catch (error) {
    console.error('LLM API请求失败:', error);
    throw error;
  }
}

/**
 * 创建SSE流式聊天连接（支持会话持久化）
 */
export function createChatStream(
  message: string,
  history: ChatHistory = [],
  onMessage: (data: any) => void,
  onError: (error: any) => void,
  onEnd: () => void,
  modelType?: string,
  sessionId?: string
): AbortController {
  // 创建中止控制器
  const controller = new AbortController();
  const signal = controller.signal;

  // 发送请求
  (async () => {
    try {
      console.log('发送LLM请求', { message, history, modelType, sessionId });

      const bodyPayload: any = { message, history };
      if (modelType) bodyPayload.model_type = modelType;
      if (sessionId) bodyPayload.session_id = sessionId;

      const response = await fetch(`${LLM_BASE_URL}/chat/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
        },
        body: JSON.stringify(bodyPayload),
        credentials: 'include',
        signal
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      // 使用ReadableStream处理流式响应
      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error('无法读取响应流');
      }

      const decoder = new TextDecoder('utf-8');
      let buffer = '';
      
      // 处理流式响应
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        
        // 解码二进制数据
        buffer += decoder.decode(value, { stream: true });
        
        // 按换行符逐行切分，最后一行可能不完整需保留
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        
        for (const line of lines) {
          const trimmed = line.trim();
          
          // 空行 / 注释行跳过（SSE 标准）
          if (!trimmed || trimmed.startsWith(':')) continue;
          
          // 识别SSE数据行
          if (trimmed.startsWith('data:')) {
            const data = trimmed.substring(5).trim();
            
            // 空 data 域跳过
            if (!data) continue;
            
            // 检查是否为结束标记
            if (data === '[DONE]') {
              onEnd();
              return;
            }
            
            try {
              // 解析JSON数据并处理
              const parsedData = JSON.parse(data);
              
              // 特殊处理思考过程数据，确保前端能有效展示
              if (parsedData.type === 'thought' && parsedData.data) {
                try {
                  if (typeof parsedData.data === 'string') {
                    const jsonData = JSON.parse(parsedData.data);
                    parsedData.data = jsonData;
                  }
                } catch (e) {
                  // 保持原始字符串格式
                }
              }
              
              // 添加步骤类型或状态的提示消息
              if (!parsedData.message && parsedData.type) {
                switch (parsedData.type) {
                  case 'chain_start':
                    parsedData.message = '开始处理请求...';
                    break;
                  case 'chain_end':
                    parsedData.message = '处理完成';
                    break;
                  case 'thought':
                    parsedData.message = '思考中...';
                    break;
                }
              }
              
              // 立即调用回调，确保前端能实时更新
              onMessage(parsedData);
            } catch (e) {
              console.warn('SSE数据解析失败', e, data);
              // 非 JSON 数据作为内容文本传递
              onMessage({ type: 'content', text: data });
            }
          }
        }
      }
      
      // 处理 buffer 中可能残留的最后一条消息
      if (buffer.trim()) {
        const trimmed = buffer.trim();
        if (trimmed.startsWith('data:')) {
          const data = trimmed.substring(5).trim();
          if (data && data !== '[DONE]') {
            try {
              onMessage(JSON.parse(data));
            } catch (e) {
              onMessage({ type: 'content', text: data });
            }
          }
        }
      }
      
      // 流已读取完毕
      onEnd();
    } catch (error) {
      // 忽略中止错误
      if ((error as Error).name !== 'AbortError') {
        console.error('SSE流处理错误:', error);
        onError(error);
      }
    }
  })();

  return controller;
}

// ============ 对话会话管理 API ============

/**
 * 获取用户的对话会话列表
 */
export async function getChatSessions(): Promise<ChatSessionInfo[]> {
  try {
    const response = await http.get<ChatSessionInfo[]>(`${LLM_BASE_URL}/sessions/`);
    return response || [];
  } catch (error) {
    console.error('获取会话列表失败:', error);
    return [];
  }
}

/**
 * 获取单个会话的详细信息（含消息历史）
 */
export async function getChatSessionDetail(sessionId: string): Promise<ChatSessionDetail | null> {
  try {
    return await http.get<ChatSessionDetail>(`${LLM_BASE_URL}/sessions/${sessionId}/`);
  } catch (error) {
    console.error('获取会话详情失败:', error);
    return null;
  }
}

/**
 * 删除对话会话
 */
export async function deleteChatSession(sessionId: string): Promise<boolean> {
  try {
    await http.delete(`${LLM_BASE_URL}/sessions/${sessionId}/`);
    return true;
  } catch (error) {
    console.error('删除会话失败:', error);
    return false;
  }
}

/**
 * 更新会话标题
 */
export async function updateChatSessionTitle(sessionId: string, title: string): Promise<ChatSessionInfo | null> {
  try {
    return await http.patch<ChatSessionInfo>(`${LLM_BASE_URL}/sessions/${sessionId}/`, { title });
  } catch (error) {
    console.error('更新会话标题失败:', error);
    return null;
  }
}

// ============ 其他 API ============

/**
 * 获取区域信息
 */
export async function getAreaInfo(areaId: number): Promise<any> {
  try {
    return await http.get(`/api/areas/${areaId}/`);
  } catch (error) {
    console.error('获取区域信息失败:', error);
    throw error;
  }
}

/**
 * 获取推荐区域
 */
export async function getSuggestedAreas(limit: number = 5): Promise<any[]> {
  try {
    const response = await http.get<LLMRecommendationResponse>(`${LLM_BASE_URL}/recommendations/user/`, { limit });
    return response.data || [];
  } catch (error) {
    console.error('获取推荐区域失败:', error);
    throw error;
  }
}

/**
 * 获取LLM模型信息
 */
export async function getModelInfo(): Promise<any> {
  try {
    return await http.get(`${LLM_BASE_URL}/model-info/`);
  } catch (error) {
    console.error('获取模型信息失败:', error);
    throw error;
  }
}

