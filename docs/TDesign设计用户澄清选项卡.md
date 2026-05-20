# TDesign 实现 AI 澄清选项的完整最佳实践指南

基于行业通用标准、ChatGPT/Claude 等主流产品的交互设计，以及 TDesign 官方组件特性，我为你整理了一套生产级别的 `ask_clarification` 实现方案。

## 一、产品设计最佳实践

### 1.1 核心交互原则

| 原则 | 具体要求 | 数据支撑 |
|------|----------|----------|
| **≤3轮澄清** | 超过3轮必须提供转人工、保存进度或其他退出选项 | 任务完成率提升35-60%，用户满意度提升30-50%  |
| **一次一问** | 每个澄清请求只解决一个决策点，不要将多个问题合并 | 避免用户混淆，决策效率提升40%  |
| **能推断不询问** | 利用上下文、用户历史、系统数据推断信息，推断后必须确认 | 平均澄清轮次从3.2轮降至1.8轮  |
| **优先级驱动** | 先收集最关键的必填字段，再收集次要字段 | 任务中断率降低25%  |
| **批量确认** | 多个默认值或推断值一次性展示给用户确认 | 减少交互次数，提升效率  |

### 1.2 选项设计规范

**✅ 正确做法：**
- 选项数量控制在 **2-5个**（最佳3个），避免选择困难
- 每个选项必须是**完整、独立的答案**，不能有歧义
- 选项文本简洁明了，不超过15个字
- 按逻辑顺序排列（如时间从近到远、重要性从高到低）

**❌ 错误做法：**
- 提供"其他"或"请说明"选项（如果需要，应该使用自由文本输入）
- 选项之间有重叠或包含关系
- 选项过长，需要换行显示
- 选项数量超过5个

**示例：**
```
✅ 好：
您是想了解：
1. 技术架构
2. 商务报价
3. 实施周期

❌ 不好：
您是想了解：
1. 技术方面的问题
2. 商务方面的问题
3. 其他（请说明）
```

### 1.3 话术规范

- **澄清问题**：使用"我需要确认一下"、"为了更准确地回答您"等礼貌开头
- **推断确认**：使用"您是指...吗？"、"我理解的是...，对吗？"
- **执行前总结**：明确展示系统理解的所有信息，让用户一次性确认
- **兜底话术**：3轮未澄清时，提供多种解决方案，不要只说"我听不懂"

## 二、TDesign 技术实现最佳实践

### 2.1 组件选择与布局

TDesign 提供了专门的 AI Chat 组件库，推荐使用以下组合：

```tsx
import { Chat, Button, Space, Tag, Divider } from 'tdesign-react';
import { QuestionCircleIcon } from 'tdesign-icons-react';

// 澄清选项组件
const ClarificationOptions = ({ question, options, onSelect }) => {
  return (
    <div className="clarification-container" style={{
      marginTop: '16px',
      background: 'var(--td-bg-color-secondary)',
      padding: '16px',
      borderRadius: 'var(--td-radius-default)',
      border: '1px solid var(--td-border-color)',
    }}>
      <div style={{ 
        marginBottom: '12px', 
        display: 'flex', 
        alignItems: 'center', 
        gap: '8px' 
      }}>
        <QuestionCircleIcon size="18px" color="var(--td-brand-color)" />
        <span style={{ fontWeight: 500 }}>{question}</span>
      </div>
      
      <Space direction="vertical" style={{ width: '100%' }}>
        {options.map((option, index) => (
          <Button
            key={index}
            theme="default"
            variant="outline"
            size="large"
            onClick={() => onSelect(option)}
            block
            style={{ textAlign: 'left', paddingLeft: '16px' }}
          >
            <Tag theme="primary" variant="light" style={{ marginRight: '8px' }}>
              {index + 1}
            </Tag>
            {option}
          </Button>
        ))}
      </Space>
    </div>
  );
};
```

### 2.2 数据结构设计

**后端返回的澄清数据结构（推荐）：**
```typescript
interface ClarificationResponse {
  type: 'ask_clarification'; // 固定类型，用于前端识别
  runId: string; // 关联当前推理任务ID
  question: string; // 澄清问题
  options: string[]; // 选项列表
  slotName?: string; // 对应的词槽名称（可选）
  priority?: number; // 优先级（可选）
}
```

**前端状态管理：**
```typescript
interface ChatState {
  messages: Message[];
  isClarifying: boolean; // 核心状态锁
  currentClarification: ClarificationResponse | null;
  currentRunId: string | null; // 当前正在执行的推理任务ID
  isLoading: boolean;
}
```

### 2.3 AG-UI 协议集成（推荐）

TDesign Chat 内置支持业界标准的 **AG-UI 协议**，这是实现复杂 AI 交互的最佳选择 ：

```tsx
// 配置 AG-UI 协议
const chatServiceConfig = {
  endpoint: '/api/agui/chat',
  protocol: 'agui', // 启用AG-UI协议
  stream: true,
  onClarification: (clarification) => {
    // 自动处理澄清请求
    setIsClarifying(true);
    setCurrentClarification(clarification);
  },
};

// 后端返回 AG-UI 格式的澄清事件
data: {"type": "ASK_CLARIFICATION", "runId": "run_123", "question": "您想了解哪个方面？", "options": ["技术架构", "商务报价"]}
```

## 三、流程控制与阻塞机制最佳实践

### 3.1 状态锁实现（核心）

**绝对不能依赖模型自觉停止推理**，必须在前端和后端同时实现状态锁：

```tsx
// 前端状态锁
const callModel = async (userInput: string) => {
  // 如果正在澄清，直接返回
  if (isClarifying) {
    console.warn('正在等待用户澄清，无法发起新请求');
    return;
  }

  setIsLoading(true);
  const runId = generateUniqueId();
  setCurrentRunId(runId);

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: userInput,
        runId: runId,
      }),
    });

    // 处理流式响应
    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value);
      const lines = chunk.split('\n').filter(line => line.trim());

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = JSON.parse(line.slice(6));
          
          // 关键：如果收到澄清请求，立即设置状态锁
          if (data.type === 'ask_clarification') {
            setIsClarifying(true);
            setCurrentClarification(data);
            setIsLoading(false);
            // 不再继续处理后续流数据，直到用户澄清
            return;
          }
          
          // 处理正常消息
          if (data.type === 'text') {
            // 更新消息内容
          }
        }
      }
    }
  } catch (error) {
    console.error('请求失败:', error);
  } finally {
    setIsLoading(false);
  }
};
```

### 3.2 后端流程控制

后端也必须实现对应的阻塞逻辑：
```python
# 后端伪代码（Python）
def chat_handler(request):
    user_input = request.json['message']
    run_id = request.json['runId']
    
    # 第一步：意图识别和实体提取
    intent, entities, confidence = analyze_intent(user_input)
    
    # 第二步：检查是否需要澄清
    if confidence < 0.75 or missing_required_slots(entities):
        # 返回澄清请求，然后终止当前推理
        return sse_response({
            'type': 'ask_clarification',
            'runId': run_id,
            'question': '我需要确认一下您的需求',
            'options': ['选项A', '选项B', '选项C']
        })
    
    # 只有当不需要澄清时，才继续执行后续推理
    result = perform_inference(intent, entities)
    return sse_response({'type': 'text', 'content': result})
```

### 3.3 用户输入控制

澄清期间必须完全阻断用户的其他输入：
```tsx
<Input
  value={inputValue}
  onChange={setInputValue}
  placeholder={isClarifying ? "请先选择上方选项..." : "输入消息..."}
  disabled={isClarifying} // 禁用输入框
  suffix={
    <Button 
      theme="primary" 
      icon={<SendIcon />} 
      disabled={isClarifying || !inputValue} // 禁用发送按钮
      onClick={handleSend}
    />
  }
/>
```

## 四、边缘情况与异常处理最佳实践

### 4.1 网络异常处理

- 澄清请求发送失败时，自动重试最多2次
- 重试失败时，显示错误信息并提供"重新获取选项"按钮
- 允许用户刷新页面后继续之前的澄清流程

### 4.2 超时处理

- 设置合理的超时时间（建议30秒）
- 超时后显示"网络连接超时，请稍后再试"
- 提供"重新发送"按钮

### 4.3 多轮澄清处理

- 记录每一轮的澄清结果
- 支持用户返回上一步修改选择
- 达到3轮后，自动触发兜底策略

### 4.4 兜底策略（三级兜底）

**一级兜底：** 猜你想问（相似意图推荐）
**二级兜底：** 提供自由文本输入框
**三级兜底：** 转人工客服或保存进度

```tsx
// 3轮未澄清时的兜底组件
const ClarificationFallback = ({ onRetry, onTransferToHuman, onSaveProgress }) => {
  return (
    <div className="clarification-fallback">
      <div style={{ marginBottom: '16px', fontWeight: 500 }}>
        抱歉，我还是不太理解您的需求。您可以：
      </div>
      <Space direction="vertical" style={{ width: '100%' }}>
        <Button block onClick={onRetry}>重新描述您的问题</Button>
        <Button block variant="outline" onClick={onTransferToHuman}>转接人工客服</Button>
        <Button block variant="outline" onClick={onSaveProgress}>保存进度，稍后继续</Button>
      </Space>
    </div>
  );
};
```

## 五、性能与可扩展性最佳实践

### 5.1 组件懒加载

- 澄清选项组件按需加载
- 大量选项时使用虚拟滚动
- 避免不必要的重渲染

### 5.2 状态持久化

- 将澄清状态保存到 localStorage
- 页面刷新后可以恢复之前的澄清流程
- 会话结束后自动清理状态

### 5.3 可扩展性设计

- 使用插件化架构，支持不同类型的澄清组件
- 支持自定义选项渲染
- 预留扩展接口，方便未来添加新的澄清类型

## 六、完整生产级代码示例

```tsx
import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Chat, Button, Space, Input, Tag, message } from 'tdesign-react';
import { SendIcon, QuestionCircleIcon, RefreshIcon } from 'tdesign-icons-react';

// 类型定义
interface Message {
  role: 'user' | 'assistant';
  content: string;
  timestamp?: number;
}

interface ClarificationResponse {
  type: 'ask_clarification';
  runId: string;
  question: string;
  options: string[];
  slotName?: string;
}

const App: React.FC = () => {
  // 状态管理
  const [messages, setMessages] = useState<Message[]>([]);
  const [isClarifying, setIsClarifying] = useState(false);
  const [currentClarification, setCurrentClarification] = useState<ClarificationResponse | null>(null);
  const [clarificationRound, setClarificationRound] = useState(0);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [currentRunId, setCurrentRunId] = useState<string | null>(null);
  
  const chatEndRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // 生成唯一ID
  const generateUniqueId = () => {
    return `run_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  };

  // 滚动到底部
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isClarifying]);

  // 处理用户选择选项
  const handleSelectOption = useCallback(async (option: string) => {
    if (!currentClarification) return;

    // 将用户选择添加到消息列表
    const userChoiceMsg: Message = {
      role: 'user',
      content: `我选择：${option}`,
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, userChoiceMsg]);

    // 重置澄清状态
    setIsClarifying(false);
    const runId = currentRunId;
    setCurrentClarification(null);
    setCurrentRunId(null);

    // 继续后续推理
    await continueInference(option, runId);
  }, [currentClarification, currentRunId]);

  // 继续推理
  const continueInference = async (selectedOption: string, runId: string) => {
    setIsLoading(true);
    abortControllerRef.current = new AbortController();

    try {
      const response = await fetch('/api/chat/continue', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          clarification: selectedOption,
          runId: runId,
        }),
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        throw new Error('请求失败');
      }

      // 处理流式响应
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let assistantMessage = '';

      // 添加空的助手消息
      setMessages((prev) => [...prev, { role: 'assistant', content: '' }]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n').filter(line => line.trim());

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = JSON.parse(line.slice(6));
            
            if (data.type === 'text') {
              assistantMessage += data.content;
              // 更新助手消息
              setMessages((prev) => {
                const newMessages = [...prev];
                newMessages[newMessages.length - 1].content = assistantMessage;
                return newMessages;
              });
            }
            
            // 如果又需要澄清
            if (data.type === 'ask_clarification') {
              setIsClarifying(true);
              setCurrentClarification(data);
              setClarificationRound((prev) => prev + 1);
              setCurrentRunId(data.runId);
              // 移除空的助手消息
              setMessages((prev) => prev.slice(0, -1));
              return;
            }
          }
        }
      }
    } catch (error) {
      if (error.name !== 'AbortError') {
        console.error('推理失败:', error);
        message.error('网络请求失败，请稍后重试');
      }
    } finally {
      setIsLoading(false);
      abortControllerRef.current = null;
    }
  };

  // 初始调用模型
  const callModel = async (userInput: string) => {
    if (isClarifying || isLoading || !userInput.trim()) return;

    // 取消之前的请求
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    // 添加用户消息
    const userMsg: Message = {
      role: 'user',
      content: userInput,
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInputValue('');

    setIsLoading(true);
    const runId = generateUniqueId();
    setCurrentRunId(runId);
    setClarificationRound(0);
    abortControllerRef.current = new AbortController();

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: userInput,
          runId: runId,
        }),
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        throw new Error('请求失败');
      }

      // 处理流式响应
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let assistantMessage = '';

      // 添加空的助手消息
      setMessages((prev) => [...prev, { role: 'assistant', content: '' }]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n').filter(line => line.trim());

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = JSON.parse(line.slice(6));
            
            // 关键：收到澄清请求，立即设置状态锁并终止当前流处理
            if (data.type === 'ask_clarification') {
              setIsClarifying(true);
              setCurrentClarification(data);
              setClarificationRound((prev) => prev + 1);
              setCurrentRunId(data.runId);
              // 移除空的助手消息
              setMessages((prev) => prev.slice(0, -1));
              setIsLoading(false);
              return;
            }
            
            if (data.type === 'text') {
              assistantMessage += data.content;
              // 更新助手消息
              setMessages((prev) => {
                const newMessages = [...prev];
                newMessages[newMessages.length - 1].content = assistantMessage;
                return newMessages;
              });
            }
          }
        }
      }
    } catch (error) {
      if (error.name !== 'AbortError') {
        console.error('请求失败:', error);
        message.error('网络请求失败，请稍后重试');
        // 移除空的助手消息
        setMessages((prev) => prev.slice(0, -1));
      }
    } finally {
      setIsLoading(false);
      abortControllerRef.current = null;
    }
  };

  // 处理发送
  const handleSend = () => {
    if (inputValue.trim() && !isClarifying && !isLoading) {
      callModel(inputValue);
    }
  };

  // 处理回车键
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // 3轮未澄清时显示兜底
  const renderFallback = () => {
    if (clarificationRound >= 3) {
      return (
        <div style={{ marginTop: '16px', padding: '16px', background: '#fff3e0', borderRadius: '8px' }}>
          <div style={{ marginBottom: '12px', fontWeight: 500 }}>
            抱歉，经过多次沟通我还是不太理解您的需求。您可以：
          </div>
          <Space direction="vertical" style={{ width: '100%' }}>
            <Button 
              block 
              onClick={() => {
                setIsClarifying(false);
                setCurrentClarification(null);
                setClarificationRound(0);
              }}
            >
              重新描述您的问题
            </Button>
            <Button block variant="outline">转接人工客服</Button>
            <Button block variant="outline">保存进度，稍后继续</Button>
          </Space>
        </div>
      );
    }
    return null;
  };

  return (
    <div style={{ 
      width: '600px', 
      margin: '50px auto', 
      height: '80vh', 
      display: 'flex', 
      flexDirection: 'column',
      border: '1px solid var(--td-border-color)',
      borderRadius: 'var(--td-radius-default)',
      overflow: 'hidden',
    }}>
      {/* 聊天区域 */}
      <div style={{ 
        flex: 1, 
        overflowY: 'auto', 
        padding: '20px',
        background: 'var(--td-bg-color-page)',
      }}>
        <Chat messages={messages} />
        
        {/* 澄清选项 */}
        {isClarifying && currentClarification && clarificationRound < 3 && (
          <div style={{
            marginTop: '16px',
            background: 'var(--td-bg-color-secondary)',
            padding: '16px',
            borderRadius: 'var(--td-radius-default)',
            border: '1px solid var(--td-border-color)',
          }}>
            <div style={{ 
              marginBottom: '12px', 
              display: 'flex', 
              alignItems: 'center', 
              gap: '8px' 
            }}>
              <QuestionCircleIcon size="18px" color="var(--td-brand-color)" />
              <span style={{ fontWeight: 500 }}>{currentClarification.question}</span>
            </div>
            
            <Space direction="vertical" style={{ width: '100%' }}>
              {currentClarification.options.map((option, index) => (
                <Button
                  key={index}
                  theme="default"
                  variant="outline"
                  size="large"
                  onClick={() => handleSelectOption(option)}
                  block
                  style={{ textAlign: 'left', paddingLeft: '16px' }}
                >
                  <Tag theme="primary" variant="light" style={{ marginRight: '8px' }}>
                    {index + 1}
                  </Tag>
                  {option}
                </Button>
              ))}
            </Space>
          </div>
        )}
        
        {/* 兜底组件 */}
        {isClarifying && renderFallback()}
        
        {/* 加载状态 */}
        {isLoading && !isClarifying && (
          <div style={{ marginTop: '16px', textAlign: 'center', color: 'var(--td-text-color-secondary)' }}>
            正在思考中...
          </div>
        )}
        
        <div ref={chatEndRef} />
      </div>

      {/* 底部输入框 */}
      <div style={{ 
        padding: '10px 20px', 
        borderTop: '1px solid var(--td-border-color)',
        background: 'var(--td-bg-color-container)',
      }}>
        <Input
          value={inputValue}
          onChange={setInputValue}
          onKeyDown={handleKeyDown}
          placeholder={isClarifying ? "请先选择上方选项..." : "输入消息..."}
          disabled={isClarifying || isLoading}
          suffix={
            <Button 
              theme="primary" 
              icon={<SendIcon />} 
              disabled={isClarifying || isLoading || !inputValue.trim()}
              onClick={handleSend}
            />
          }
        />
      </div>
    </div>
  );
};

export default App;
```

## 七、关键指标监控

上线后需要持续监控以下指标，不断优化澄清体验：

- **意图识别准确率**：目标 >90%
- **平均澄清轮次**：目标 ≤2轮
- **任务完成率**：目标 >85%
- **用户放弃率**：目标 <15%
- **转人工率**：目标 <10%
- **用户满意度**：目标 >4/5分

需要我帮你把这个方案适配成 **Vue 3 + TDesign Vue Next** 版本，或者补充 **AG-UI 协议的完整后端实现示例** 吗？