'use client'

import { useState, useEffect } from 'react'
import { useParams } from 'next/navigation'
import { AppShell } from '@/components/layout/AppShell'
import { NotebookHeader } from '../components/NotebookHeader'
import { SourcesColumn } from '../components/SourcesColumn'
import { NotesColumn } from '../components/NotesColumn'
import { ChatColumn } from '../components/ChatColumn'
import { useNotebook } from '@/lib/hooks/use-notebooks'
import { useNotebookSources } from '@/lib/hooks/use-sources'
import { useNotes } from '@/lib/hooks/use-notes'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { NotebookWorkspace } from '../components/NotebookWorkspace'
import { useTranslation } from '@/lib/hooks/use-translation'
import {
  applyBulkSourceContext,
  applyBulkNoteContext,
  computeSourceSelections,
  computeNoteSelections,
  type SourceContextDefault,
  type SourceBulkAction,
  type NoteContextDefault,
} from '@/lib/utils/source-context'

// Re-exported from the shared types module for backward compatibility; several
// components historically import these from this route file.
import type { ContextMode, ContextSelections, NoteContextMode } from '@/lib/types/notebook-context'
export type { ContextMode, ContextSelections, NoteContextMode }

export default function NotebookPage() {
  const params = useParams()
  const notebookId = params?.id ? decodeURIComponent(params.id as string) : ''
  return <NotebookDetail key={notebookId} notebookId={notebookId} />
}

function NotebookDetail({ notebookId }: { notebookId: string }) {
  const { t } = useTranslation()

  const { data: notebook, isLoading: notebookLoading } = useNotebook(notebookId)
  const {
    sources,
    isLoading: sourcesLoading,
    refetch: refetchSources,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useNotebookSources(notebookId)
  const { data: notes, isLoading: notesLoading } = useNotes(notebookId)

  const [activeView, setActiveView] = useState<'chat' | 'sources' | 'notes'>('chat')

  // Context selection state
  const [contextSelections, setContextSelections] = useState<ContextSelections>({
    sources: {},
    notes: {}
  })

  // The default context mode applied to sources as they load. A bulk
  // include/exclude updates this so sources loaded later via pagination follow
  // the same intent instead of reverting to "included" (#223/#915).
  const [sourceContextDefault, setSourceContextDefault] = useState<SourceContextDefault>('full')

  // Same idea for notes loaded later (notes are binary: included/off).
  const [noteContextDefault, setNoteContextDefault] = useState<NoteContextDefault>('include')

  const [contextLoaded, setContextLoaded] = useState(false)
  useEffect(() => {
    try {
      const saved = localStorage.getItem(`notebook-context:${notebookId}`)
      if (saved) {
        const parsed = JSON.parse(saved)
        const valid = (value: unknown): value is Record<string, ContextMode> => !!value && typeof value === 'object' && !Array.isArray(value) && Object.values(value).every(mode => ['off', 'full', 'insights'].includes(String(mode)))
        if (valid(parsed.sources) && valid(parsed.notes)) {
          setContextSelections(parsed)
        }
      }
    } catch { /* Storage unavailable or old malformed preferences: use safe defaults. */ }
    setContextLoaded(true)
  }, [notebookId])
  useEffect(() => {
    if (contextLoaded) {
      try { localStorage.setItem(`notebook-context:${notebookId}`, JSON.stringify(contextSelections)) } catch { /* Private browsing can deny storage. */ }
    }
  }, [notebookId, contextLoaded, contextSelections])

  // Initialize and update selections when sources load or change
  useEffect(() => {
    if (contextLoaded && sources && sources.length > 0) {
      setContextSelections(prev => ({
        ...prev,
        sources: computeSourceSelections(prev.sources, sources, sourceContextDefault),
      }))
    }
  }, [sources, sourceContextDefault, contextLoaded])

  useEffect(() => {
    if (contextLoaded && notes && notes.length > 0) {
      setContextSelections(prev => ({
        ...prev,
        notes: computeNoteSelections(prev.notes, notes, noteContextDefault),
      }))
    }
  }, [notes, noteContextDefault, contextLoaded])

  const handleSourceContextModeChange = (sourceId: string, mode: ContextMode) => {
    setContextSelections(prev => ({
      ...prev,
      sources: {
        ...prev.sources,
        [sourceId]: mode
      }
    }))
  }

  const handleNoteContextModeChange = (noteId: string, mode: NoteContextMode) => {
    setContextSelections(prev => ({
      ...prev,
      notes: {
        ...prev.notes,
        [noteId]: mode
      }
    }))
  }

  // Bulk-apply a context action (insights-only / full / exclude) to every
  // source at once (#223). Also records the action as the default for sources
  // loaded later (#915).
  const handleBulkSourceContext = (action: SourceBulkAction) => {
    setSourceContextDefault(action)
    setContextSelections(prev => ({
      ...prev,
      sources: applyBulkSourceContext(prev.sources, sources ?? [], action),
    }))
  }

  // Bulk include/exclude every note from the chat context at once (#223).
  const handleBulkNoteContext = (action: NoteContextDefault) => {
    setNoteContextDefault(action)
    setContextSelections(prev => ({
      ...prev,
      notes: applyBulkNoteContext(prev.notes, notes ?? [], action),
    }))
  }

  if (notebookLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  if (!notebook) {
    return (
      <AppShell>
        <div className="p-6">
          <h1 className="text-2xl font-bold mb-4">{t('notebooks.notFound')}</h1>
          <p className="text-muted-foreground">{t('notebooks.notFoundDesc')}</p>
        </div>
      </AppShell>
    )
  }

  return (
    <AppShell>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col" data-testid="notebook-page">
        <div className="shrink-0 px-4 pt-4 sm:px-6 sm:pt-5">
          <NotebookHeader notebook={notebook} />
        </div>
        <NotebookWorkspace
          activeView={activeView}
          onViewChange={setActiveView}
          sourceCount={sources?.length ?? 0}
          noteCount={notes?.length ?? 0}
          chat={<ChatColumn
            notebookId={notebookId}
            contextSelections={contextSelections}
            sources={sources}
            sourcesLoading={sourcesLoading || !contextLoaded}
            onEditContext={() => setActiveView('sources')}
            isVisible={activeView === 'chat'}
          />}
          sources={<SourcesColumn
            embedded
            sources={sources}
            isLoading={sourcesLoading}
            notebookId={notebookId}
            notebookName={notebook.name}
            onRefresh={refetchSources}
            contextSelections={contextSelections.sources}
            onContextModeChange={handleSourceContextModeChange}
            onBulkContextModeChange={handleBulkSourceContext}
            hasNextPage={hasNextPage}
            isFetchingNextPage={isFetchingNextPage}
            fetchNextPage={fetchNextPage}
          />}
          notes={<NotesColumn
            embedded
            notes={notes}
            isLoading={notesLoading}
            notebookId={notebookId}
            contextSelections={contextSelections.notes}
            onContextModeChange={handleNoteContextModeChange}
            onBulkContextModeChange={handleBulkNoteContext}
          />}
        />
      </div>
    </AppShell>
  )
}
