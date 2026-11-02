'use client'

import { memo, useCallback, useState, useRef, useEffect, useId } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Bot, User, Send, Loader2, FileText, Lightbulb, StickyNote, Clock, ArrowDown, MessageSquarePlus } from 'lucide-react'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import {
  SourceChatMessage,
  SourceChatContextIndicator,
  BaseChatSession
} from '@/lib/types/api'
import { ModelSelector } from './ModelSelector'
import { ContextIndicator } from '@/components/common/ContextIndicator'
import { SessionManager } from '@/components/sources/SessionManager'
import { MessageActions } from '@/components/sources/MessageActions'
import { convertReferencesToCompactMarkdown, createCompactReferenceLinkComponent } from '@/lib/utils/source-references'
import { useModalManager } from '@/lib/hooks/use-modal-manager'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/hooks/use-translation'

interface NotebookContextStats {
  sourcesInsights: number
  sourcesFull: number
  notesCount: number
  tokenCount?: number
  charCount?: number
}

interface ChatPanelProps {
  isVisible?: boolean
  workspace?: boolean
  onEditContext?: () => void
  conversationTitle?: string
  messages: SourceChatMessage[]
  isStreaming: boolean
  contextIndicators: SourceChatContextIndicator | null
  onSendMessage: (message: string, modelOverride?: string) => void
  modelOverride?: string
  onModelChange?: (model?: string) => void
  // Session management props
  sessions?: BaseChatSession[]
  currentSessionId?: string | null
  onCreateSession?: (title: string) => void
  onSelectSession?: (sessionId: string) => void
  onDeleteSession?: (sessionId: string) => void
  onUpdateSession?: (sessionId: string, title: string) => void
  loadingSessions?: boolean
  // Generic props for reusability
  title?: string
  contextType?: 'source' | 'notebook'
  // Notebook context stats (for notebook chat)
  notebookContextStats?: NotebookContextStats
  // Notebook ID for saving notes
  notebookId?: string
}

export function ChatPanel({
  messages,
  isStreaming,
  contextIndicators,
  onSendMessage,
  modelOverride,
  onModelChange,
  sessions = [],
  currentSessionId,
  onCreateSession,
  onSelectSession,
  onDeleteSession,
  onUpdateSession,
  loadingSessions = false,
  title,
  contextType = 'source',
  notebookContextStats,
  notebookId,
  workspace = false,
  isVisible = true,
  onEditContext,
  conversationTitle
}: ChatPanelProps) {
  const { t } = useTranslation()
  const [sessionManagerOpen, setSessionManagerOpen] = useState(false)
  const scrollAreaRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const followLatest = useRef(true)
  const [showLatest, setShowLatest] = useState(false)
  const scrollToLatest = useCallback(() => {
    const area = scrollAreaRef.current
    area?.scrollTo({ top: area.scrollHeight, behavior: 'smooth' })
    followLatest.current = true
    setShowLatest(false)
  }, [])
  const { openModal } = useModalManager()

  // Stable reference-click handler so memoized messages don't re-render on
  // composer keystrokes (which no longer re-render this component at all, since
  // the input state lives in the ChatComposer child).
  const handleReferenceClick = useCallback((type: string, id: string) => {
    const modalType = type === 'source_insight' ? 'insight' : type as 'source' | 'note' | 'insight'

    try {
      openModal(modalType, id)
      // Note: The modal system uses URL parameters and doesn't throw errors for missing items.
      // The modal component itself will handle displaying "not found" states.
      // This try-catch is here for future enhancements or unexpected errors.
    } catch {
      toast.error(t('common.noResults'))
    }
  }, [openModal, t])

  // Follow new answers only when already near the bottom. Reading older
  // messages must not be interrupted by a reply or a context refresh.
  useEffect(() => { followLatest.current = true }, [currentSessionId])
  useEffect(() => {
    if (isVisible && followLatest.current && scrollAreaRef.current) {
      scrollAreaRef.current.scrollTop = scrollAreaRef.current.scrollHeight
    }
  }, [messages, currentSessionId, isVisible])

  return (
    <>
    <Card className={cn("relative flex min-h-0 min-w-0 flex-col h-full flex-1 overflow-hidden", workspace && "border-0 rounded-none shadow-none bg-transparent gap-0 py-0")}>
      <CardHeader className={cn("pb-3 flex-shrink-0", workspace && "mx-auto w-full max-w-4xl px-4 pt-3 pb-2 sm:px-6")}>
        <div className="flex min-w-0 items-center justify-between gap-3">
          <CardTitle className={cn("flex min-w-0 items-center gap-2 text-xs font-semibold uppercase tracking-[0.13em] text-muted-foreground", workspace && "normal-case tracking-normal font-medium")}>
            {!workspace && <span aria-hidden className="h-3.5 w-[3px] rounded-full bg-teal" />}
            <span className="truncate">{(workspace && conversationTitle) || title || (contextType === 'source' ? t('chat.chatWith', { name: t('navigation.sources') }) : t('chat.chatWith', { name: t('common.notebook') }))}</span>
          </CardTitle>
          <div className="flex shrink-0 items-center gap-1">
          {workspace && onCreateSession && <Button variant="ghost" size="icon" aria-label="New conversation" title="New conversation" onClick={() => onCreateSession('New conversation')} disabled={isStreaming}><MessageSquarePlus className="size-4" /></Button>}
          {onSelectSession && onCreateSession && onDeleteSession && (
            <Dialog open={sessionManagerOpen} onOpenChange={setSessionManagerOpen}>
              <Button
                variant="ghost"
                size="sm"
                className="gap-2 text-muted-foreground"
                onClick={() => setSessionManagerOpen(true)}
                disabled={loadingSessions}
              >
                <Clock className="h-4 w-4" />
                <span className="text-xs">{t('chat.sessions')}</span>
              </Button>
              <DialogContent className="sm:max-w-[420px] p-0 overflow-hidden">
                <DialogTitle className="sr-only">{t('chat.sessionsTitle')}</DialogTitle>
                <SessionManager
                  sessions={sessions}
                  currentSessionId={currentSessionId ?? null}
                  onCreateSession={(title) => onCreateSession?.(title)}
                  onSelectSession={(sessionId) => {
                    onSelectSession(sessionId)
                    setSessionManagerOpen(false)
                  }}
                  onUpdateSession={(sessionId, title) => onUpdateSession?.(sessionId, title)}
                  onDeleteSession={(sessionId) => onDeleteSession?.(sessionId)}
                  loadingSessions={loadingSessions}
                />
              </DialogContent>
            </Dialog>
          )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex-1 flex flex-col min-h-0 min-w-0 p-0">
        {workspace && notebookContextStats && <div className="mx-auto flex w-full max-w-4xl shrink-0 flex-wrap items-center gap-x-3 border-b px-4 pb-2 sm:px-6">
          <ContextIndicator {...notebookContextStats} className="flex-1 border-0 bg-transparent px-0" />
          {onEditContext && <Button variant="ghost" size="sm" onClick={onEditContext} className="h-8 text-xs">Change sources</Button>}
        </div>}
        <div className="relative flex-1 min-h-0 min-w-0 overflow-y-auto overscroll-contain" ref={scrollAreaRef} data-testid="chat-messages" onScroll={() => {
          const area = scrollAreaRef.current
          if (area) {
            const nearBottom = area.scrollHeight - area.scrollTop - area.clientHeight < 120
            followLatest.current = nearBottom
            setShowLatest(!nearBottom)
          }
        }}>
          <div className={cn("space-y-6 px-4 py-5", workspace && "mx-auto w-full max-w-4xl sm:px-6 sm:py-8")}>
            {messages.length === 0 ? (
              <div className="text-center text-muted-foreground py-8">
                <Bot className="h-12 w-12 mx-auto mb-4 opacity-50" />
                <p className="text-sm">
                  {t('chat.startConversation', { type: contextType === 'source' ? t('navigation.sources') : t('common.notebook') })}
                </p>
                <p className="text-xs mt-2">{t('chat.askQuestions')}</p>
              </div>
            ) : (
              messages.map((message) => (
                <ChatMessage
                  key={message.id}
                  message={message}
                  notebookId={notebookId}
                  workspace={workspace}
                  onReferenceClick={handleReferenceClick}
                />
              ))
            )}
            {isStreaming && (
              <div className="flex gap-3 justify-start">
                <div className="flex-shrink-0">
                  <div className="h-8 w-8 rounded-full bg-teal-tint flex items-center justify-center">
                    <Bot className="h-4 w-4 text-teal" />
                  </div>
                </div>
                <div className="rounded-lg px-4 py-2 bg-card border">
                  <Loader2 className="h-4 w-4 animate-spin" />
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        </div>
        {showLatest && <div className="relative flex h-0 justify-center"><Button variant="secondary" size="sm" onClick={scrollToLatest} className="absolute bottom-3 z-10 gap-2 rounded-full shadow-sm"><ArrowDown className="size-3.5" />Latest message</Button></div>}

        {/* Context Indicators */}
        {contextIndicators && (
          <div className="border-t px-4 py-2">
            <div className="flex flex-wrap gap-2 text-xs">
              {contextIndicators.sources?.length > 0 && (
                <Badge variant="outline" className="gap-1">
                  <FileText className="h-3 w-3" />
                  {contextIndicators.sources.length} {t('navigation.sources')}
                </Badge>
              )}
              {contextIndicators.insights?.length > 0 && (
                <Badge variant="outline" className="gap-1">
                  <Lightbulb className="h-3 w-3" />
                  {contextIndicators.insights.length} {contextIndicators.insights.length === 1 ? t('common.insight') : t('common.insights')}
                </Badge>
              )}
              {contextIndicators.notes?.length > 0 && (
                <Badge variant="outline" className="gap-1">
                  <StickyNote className="h-3 w-3" />
                  {contextIndicators.notes.length} {contextIndicators.notes.length === 1 ? t('common.note') : t('common.notes')}
                </Badge>
              )}
            </div>
          </div>
        )}

        {/* Notebook Context Indicator */}
        {!workspace && notebookContextStats && (
          <ContextIndicator
            sourcesInsights={notebookContextStats.sourcesInsights}
            sourcesFull={notebookContextStats.sourcesFull}
            notesCount={notebookContextStats.notesCount}
            tokenCount={notebookContextStats.tokenCount}
            charCount={notebookContextStats.charCount}
          />
        )}

        {/* Input Area */}
        <ChatComposer
          workspace={workspace}
          onSendMessage={onSendMessage}
          isStreaming={isStreaming}
          modelOverride={modelOverride}
          onModelChange={onModelChange}
        />
      </CardContent>
    </Card>

    </>
  )
}

// Composer owns the input state so keystrokes (including IME composition) only
// re-render this small component instead of the whole message history.
interface ChatComposerProps {
  workspace?: boolean
  onSendMessage: (message: string, modelOverride?: string) => void
  isStreaming: boolean
  modelOverride?: string
  onModelChange?: (model?: string) => void
}

function ChatComposer({
  onSendMessage,
  isStreaming,
  modelOverride,
  onModelChange,
  workspace = false
}: ChatComposerProps) {
  const { t } = useTranslation()
  const chatInputId = useId()
  const [input, setInput] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    const field = textareaRef.current
    if (field) { field.style.height = '0px'; field.style.height = `${Math.min(field.scrollHeight, 180)}px` }
  }, [input])

  const handleSend = () => {
    if (input.trim() && !isStreaming) {
      onSendMessage(input.trim(), modelOverride)
      setInput('')
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.nativeEvent.isComposing) return
    // Detect platform for correct modifier key
    const isMac = typeof navigator !== 'undefined' && navigator.userAgent.toUpperCase().indexOf('MAC') >= 0
    const isModifierPressed = isMac ? e.metaKey : e.ctrlKey

    if (e.key === 'Enter' && isModifierPressed) {
      e.preventDefault()
      handleSend()
    }
  }

  // Detect platform for placeholder text
  const isMac = typeof navigator !== 'undefined' && navigator.userAgent.toUpperCase().indexOf('MAC') >= 0
  const keyHint = isMac ? '⌘+Enter' : 'Ctrl+Enter'

  return (
    <div className={cn("shrink-0 min-w-0 p-3 sm:p-4", workspace && "mx-auto w-full max-w-4xl sm:px-6 pb-[max(0.75rem,env(safe-area-inset-bottom))]")}>
      <div className="rounded-xl border bg-card p-3 shadow-sm transition-shadow focus-within:ring-1 focus-within:ring-ring">
        <label htmlFor={chatInputId} className="sr-only">Message</label>
        <Textarea ref={textareaRef} id={chatInputId} name="chat-message" autoComplete="off" value={input}
          onChange={event => setInput(event.target.value)} onKeyDown={handleKeyDown}
          placeholder={t('chat.sendPlaceholder')} disabled={isStreaming}
          className="min-h-[60px] max-h-[180px] w-full min-w-0 resize-none border-0 bg-transparent px-1 py-1 shadow-none focus-visible:ring-0 [field-sizing:fixed]"
          rows={2} />
        <div className="mt-2 flex min-w-0 items-center justify-between gap-2">
          <div className="min-w-0 max-w-[65%]">
            {onModelChange && <ModelSelector currentModel={modelOverride} onModelChange={onModelChange} disabled={isStreaming} />}
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <span className="hidden text-xs text-muted-foreground sm:inline">{keyHint}</span>
            <Button onClick={handleSend} disabled={!input.trim() || isStreaming} aria-label="Send message" className="gap-2">
              {isStreaming ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}<span>Send</span>
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

// Single chat message row. Memoized so historical messages don't re-render when
// unrelated state (e.g. the composer input) changes.
interface ChatMessageProps {
  workspace?: boolean
  message: SourceChatMessage
  notebookId?: string
  onReferenceClick: (type: string, id: string) => void
}

const ChatMessage = memo(function ChatMessage({
  message,
  notebookId,
  onReferenceClick,
  workspace = false
}: ChatMessageProps) {
  return (
    <div
      className={cn('flex min-w-0 gap-3', !workspace && message.type === 'human' ? 'justify-end' : 'justify-start')}
    >
      {message.type === 'ai' && (
        <div className={cn("flex-shrink-0", workspace && "hidden sm:block")}>
          <div className="h-8 w-8 rounded-full bg-teal-tint flex items-center justify-center">
            <Bot className="h-4 w-4 text-teal" />
          </div>
        </div>
      )}
      <div className={cn("flex min-w-0 flex-col gap-2 max-w-[85%]", workspace && "max-w-full flex-1")}>
        {workspace && <div className="text-xs font-semibold text-muted-foreground">{message.type === 'human' ? 'You' : 'Assistant'}</div>}
        <div
          className={cn('min-w-0 max-w-full rounded-lg px-4 py-2 border [overflow-wrap:anywhere] [&_pre]:max-w-full [&_pre]:overflow-x-auto [&_.katex-display]:overflow-x-auto [&_.katex-display]:overflow-y-hidden', message.type === 'human' ? 'bg-muted' : 'bg-card', workspace && message.type === 'ai' && 'border-0 bg-transparent px-0 py-0')}
        >
          {message.type === 'ai' ? (
            <AIMessageContent
              content={message.content}
              onReferenceClick={onReferenceClick}
            />
          ) : (
            <p className="text-sm whitespace-pre-wrap break-normal [overflow-wrap:anywhere] leading-7">{message.content}</p>
          )}
        </div>
        {message.type === 'ai' && (
          <MessageActions
            content={message.content}
            notebookId={notebookId}
          />
        )}
      </div>
      {message.type === 'human' && !workspace && (
        <div className={cn("flex-shrink-0", workspace && "hidden sm:block")}>
          <div className="h-8 w-8 rounded-full bg-muted border flex items-center justify-center">
            <User className="h-4 w-4 text-muted-foreground" />
          </div>
        </div>
      )}
    </div>
  )
})

// Helper component to render AI messages with clickable references
function AIMessageContent({
  content,
  onReferenceClick
}: {
  content: string
  onReferenceClick: (type: string, id: string) => void
}) {
  const { t } = useTranslation()
  // Convert references to compact markdown with numbered citations
  const markdownWithCompactRefs = convertReferencesToCompactMarkdown(content, t('common.references'))

  // Create custom link component for compact references
  const LinkComponent = createCompactReferenceLinkComponent(onReferenceClick)

  return (
    <MarkdownRenderer components={{
      a: LinkComponent
    }}>
      {markdownWithCompactRefs}
    </MarkdownRenderer>
  )
}
