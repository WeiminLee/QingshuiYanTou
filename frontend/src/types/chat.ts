/**
 * TDesign AI Chat 消息类型定义
 *
 * 参考：docs/TDesign参考设计文档.md
 * 官方文档：https://tdesign.tencent.com/chat/
 */

/**
 * 聊天消息项
 */
export interface ChatMessageItem {
  /** 消息唯一标识 */
  id: string;

  /** 消息角色：用户或助手 */
  role: "user" | "assistant";

  /** 消息内容 */
  content: string;

  /** 消息时间戳 */
  timestamp: number;

  /** 是否包含思考过程 */
  thinking?: boolean;

  /** 思考过程内容（支持换行） */
  thinkingContent?: string;

  /** 思考过程是否正在加载 */
  thinkingLoading?: boolean;

  /** 选项按钮列表 */
  suggestions?: SuggestionItem[];

  /** 工具调用列表 */
  toolCalls?: ToolCallItem[];
}

/**
 * 选项按钮项
 */
export interface SuggestionItem {
  /** 选项显示文本（primary） */
  content: string;

  /** 选项显示文本（兼容别名，模板中读取 s.text） */
  text: string;

  /** 选项值 */
  value: string;
}

/**
 * 工具调用项
 */
export interface ToolCallItem {
  /** 工具调用唯一标识 */
  id: string;

  /** 工具名称 */
  name: string;

  /** 工具状态 */
  status: "pending" | "running" | "done" | "error";

  /** 工具执行结果 */
  result?: string;

  /** 工具结果摘要预览（30-100字，由后端 build_preview 生成） */
  preview?: string;

  /** 工具参数 */
  args?: Record<string, any>;

  /** 执行时长（毫秒） */
  duration_ms?: number;

  /** 解析后的结果对象（由 useStreamParser.autoDetectParse 生成） */
  parsedResult?: unknown;
}

export type SSEEventType =
  | "reasoning_start"
  | "thinking"
  | "content"
  | "tool_called"
  | "tool_result"
  | "task_started"
  | "task_running"
  | "task_completed"
  | "task_failed"
  | "suggestions"
  | "stream_end"
  | "error"
  | "ping"
  | "clarification_request"
  | "clarification_resolved";

export interface ClarificationOption {
  label: string;
  description?: string;
}

export interface ClarificationItem {
  clarification_id: string;
  question: string;
  type: "missing_info" | "ambiguous" | "approach_choice" | "risk_confirmation";
  options?: ClarificationOption[];
  context?: string;
}

/**
 * SSE 事件类型
 */
export interface SSEEvent {
  type: SSEEventType;
  task_id: string;
  data?: any;
  timestamp: string;
  turn?: number;
  seq?: number;
}

/**
 * SSE 事件回调
 */
export interface SSECallbacks {
  onThinking?: (delta: string) => void;
  onContent?: (delta: string) => void;
  onToolCall?: (toolCall: ToolCallItem) => void;
  onToolResult?: (toolResult: ToolCallItem) => void;
  onSuggestions?: (suggestions: SuggestionItem[]) => void;
  onComplete?: () => void;
  onError?: (error: string) => void;
}
