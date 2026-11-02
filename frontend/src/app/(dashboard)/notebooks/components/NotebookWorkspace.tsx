'use client'

import { ReactNode, useState } from 'react'
import { FileText, MessageSquare, StickyNote } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'
import { cn } from '@/lib/utils'

type NotebookView = 'chat' | 'sources' | 'notes'
interface NotebookWorkspaceProps {
  chat: ReactNode
  sources: ReactNode
  notes: ReactNode
  sourceCount: number
  noteCount: number
  activeView?: NotebookView
  onViewChange?: (view: NotebookView) => void
}

/** One workspace, three modes. Keep each mounted to preserve drafts and sessions. */
export function NotebookWorkspace({ chat, sources, notes, sourceCount, noteCount, activeView, onViewChange }: NotebookWorkspaceProps) {
  const { t } = useTranslation()
  const [localView, setLocalView] = useState<NotebookView>('chat')
  const view = activeView ?? localView
  const changeView = (next: NotebookView) => {
    setLocalView(next)
    onViewChange?.(next)
  }
  const tabs = [
    { id: 'chat' as const, label: t('common.chat'), icon: MessageSquare },
    { id: 'sources' as const, label: t('navigation.sources'), icon: FileText, count: sourceCount },
    { id: 'notes' as const, label: t('common.notes'), icon: StickyNote, count: noteCount },
  ]
  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col" data-testid="notebook-workspace">
      <div role="tablist" aria-label="Notebook workspace" className="flex shrink-0 gap-1 border-b px-3 sm:px-6">
        {tabs.map(({ id, label, icon: Icon, count }, index) => (
          <button
            key={id} type="button" role="tab" id={`notebook-tab-${id}`}
            aria-selected={view === id} aria-controls={`notebook-panel-${id}`} tabIndex={view === id ? 0 : -1}
            onClick={() => changeView(id)}
            onKeyDown={event => {
              const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null
              if (next != null) {
                event.preventDefault()
                changeView(tabs[next].id)
                document.getElementById(`notebook-tab-${tabs[next].id}`)?.focus()
              }
            }}
            className={cn('relative inline-flex min-h-12 items-center gap-2 px-3 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset sm:px-4', view === id ? 'font-semibold text-foreground after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:bg-primary' : 'text-muted-foreground hover:text-foreground')}
          >
            <Icon className="size-4 shrink-0" aria-hidden />{label}
            {count != null && <span className="text-xs tabular-nums text-muted-foreground">{count}</span>}
          </button>
        ))}
      </div>
      {tabs.map(({ id }) => (
        <section key={id} id={`notebook-panel-${id}`} role="tabpanel" aria-labelledby={`notebook-tab-${id}`} hidden={view !== id}
          className={cn('min-h-0 min-w-0 flex-1', view === id && 'flex flex-col')}>
          {id === 'chat' ? chat : <div className="mx-auto flex h-full min-h-0 w-full max-w-5xl flex-col p-3 sm:p-6">{id === 'sources' ? sources : notes}</div>}
        </section>
      ))}
    </div>
  )
}
