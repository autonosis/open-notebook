'use client'

import { useState } from 'react'
import { NotebookResponse } from '@/lib/types/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Archive, ArchiveRestore, Trash2, MoreHorizontal } from 'lucide-react'
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from '@/components/ui/dropdown-menu'
import { useUpdateNotebook } from '@/lib/hooks/use-notebooks'
import { NotebookDeleteDialog } from './NotebookDeleteDialog'
import { formatDistanceToNow } from 'date-fns'
import { getDateLocale } from '@/lib/utils/date-locale'
import { InlineEdit } from '@/components/common/InlineEdit'
import { useTranslation } from '@/lib/hooks/use-translation'

interface NotebookHeaderProps {
  notebook: NotebookResponse
}

export function NotebookHeader({ notebook }: NotebookHeaderProps) {
  const { t, language } = useTranslation()
  const dfLocale = getDateLocale(language)
  const [showDeleteDialog, setShowDeleteDialog] = useState(false)
  
  const updateNotebook = useUpdateNotebook()

  const handleUpdateName = async (name: string) => {
    if (!name || name === notebook.name) return
    
    await updateNotebook.mutateAsync({
      id: notebook.id,
      data: { name }
    })
  }

  const handleUpdateDescription = async (description: string) => {
    if (description === notebook.description) return
    
    await updateNotebook.mutateAsync({
      id: notebook.id,
      data: { description }
    })
  }

  const handleArchiveToggle = () => {
    updateNotebook.mutate({
      id: notebook.id,
      data: { archived: !notebook.archived }
    })
  }

  return (
    <>
      <header className="pb-3 sm:pb-4">
        <div className="flex min-w-0 items-start justify-between gap-3">
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex min-w-0 items-center gap-3">
              <InlineEdit id="notebook-name" name="notebook-name" value={notebook.name} onSave={handleUpdateName}
                className="min-w-0 font-display text-xl font-semibold tracking-tight break-normal [overflow-wrap:anywhere] sm:text-2xl"
                inputClassName="font-display text-xl font-semibold" placeholder={t('notebooks.namePlaceholder')} />
              {notebook.archived && <Badge variant="secondary">{t('notebooks.archived')}</Badge>}
            </div>
            <InlineEdit id="notebook-description" name="notebook-description" value={notebook.description || ''} onSave={handleUpdateDescription}
              className="text-xs text-muted-foreground break-normal [overflow-wrap:anywhere] sm:text-sm" inputClassName="text-sm" placeholder={t('notebooks.addDescription')} multiline emptyText={t('notebooks.addDescription')} />
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <span className="hidden text-xs text-muted-foreground lg:block">{t('common.updated', { time: formatDistanceToNow(new Date(notebook.updated), { addSuffix: true, locale: dfLocale }) })}</span>
            <DropdownMenu>
              <DropdownMenuTrigger asChild><Button variant="ghost" size="icon" aria-label="Notebook actions"><MoreHorizontal className="size-5" /></Button></DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={handleArchiveToggle}>{notebook.archived ? <ArchiveRestore className="mr-2 size-4" /> : <Archive className="mr-2 size-4" />}{notebook.archived ? t('notebooks.unarchive') : t('notebooks.archive')}</DropdownMenuItem>
                <DropdownMenuItem onClick={() => setShowDeleteDialog(true)} className="text-destructive focus:text-destructive"><Trash2 className="mr-2 size-4" />{t('common.delete')}</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </header>

      <NotebookDeleteDialog
        open={showDeleteDialog}
        onOpenChange={setShowDeleteDialog}
        notebookId={notebook.id}
        notebookName={notebook.name}
        redirectAfterDelete
      />
    </>
  )
}