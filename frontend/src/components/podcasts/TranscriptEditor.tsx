'use client'

import { useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import apiClient from '@/lib/api/client'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { PodcastEpisode } from '@/lib/types/podcasts'

type Turn = { speaker: string; dialogue: string }
type Draft = { revision: number; entries: Turn[]; output_episode?: string }
function initial(episode: PodcastEpisode): Draft {
  const envelope = episode.transcript ?? {}
  const draft = envelope.draft as Draft | undefined
  const raw = envelope.transcript
  const turns = Array.isArray(raw) ? raw : (raw as { transcript?: Turn[] } | undefined)?.transcript ?? []
  return draft ?? { revision: Number(envelope.revision ?? 0), entries: turns as Turn[] }
}

export function TranscriptEditor({ episode, onDirtyChange, onGoToEpisode }: { episode: PodcastEpisode; onDirtyChange: (dirty: boolean) => void; onGoToEpisode: (id: string) => void }) {
  const { t } = useTranslation()
  const query = useQueryClient()
  const source = useMemo(() => initial(episode), [episode])
  const [saved, setSaved] = useState(source)
  const [turns, setTurns] = useState(source.entries)
  const [editing, setEditing] = useState(false)
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [output, setOutput] = useState<{ episode_id: string; name: string; status?: string } | null>(null)
  const [reuse, setReuse] = useState(true)
  const dirty = JSON.stringify(turns) !== JSON.stringify(saved.entries)
  const active = ['running', 'processing', 'pending', 'queued', 'submitted'].includes(episode.job_status ?? '')
  const invalid = turns.some(turn => !turn.dialogue.trim())

  useEffect(() => { onDirtyChange(dirty) }, [dirty, onDirtyChange])
  useEffect(() => {
    if (!dirty && source.revision > saved.revision) { setSaved(source); setTurns(source.entries) }
  }, [source, saved.revision, dirty])
  useEffect(() => {
    const guard = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = '' } }
    window.addEventListener('beforeunload', guard)
    return () => window.removeEventListener('beforeunload', guard)
  }, [dirty])

  const reportError = (cause: unknown) => {
    const detail = (cause as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    setError(typeof detail === 'string' ? detail : t('transcriptEditor.error'))
  }
  const save = async () => {
    const response = await apiClient.put<Draft>(`/podcasts/episodes/${episode.id}/transcript`, { expected_revision: saved.revision, entries: turns })
    setSaved(response.data); setTurns(response.data.entries); setOutput(null); onDirtyChange(false)
    await query.invalidateQueries({ queryKey: QUERY_KEYS.podcastEpisodes })
    return response.data
  }
  const perform = async (regenerate: boolean) => {
    setBusy(true); setError('')
    try {
      const draft = dirty ? await save() : saved
      if (regenerate) {
        const response = await apiClient.post<{ episode_id: string; name: string; status?: string }>(`/podcasts/episodes/${episode.id}/regenerate-audio`, { expected_revision: draft.revision, reuse_unchanged: reuse })
        await query.invalidateQueries({ queryKey: QUERY_KEYS.podcastEpisodes })
        setOutput(response.data)
      }
    } catch (cause) { reportError(cause) }
    finally { setBusy(false) }
  }

  if (!turns.length) return <p className="text-sm text-muted-foreground">{t('podcasts.noTranscript')}</p>
  return <div className="flex h-full min-h-0 flex-col gap-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div><p className="text-sm font-medium">{t('transcriptEditor.title')}</p><p className="text-xs text-muted-foreground">{dirty ? t('transcriptEditor.unsaved') : active ? t('transcriptEditor.processing') : !episode.audio_file ? t('transcriptEditor.noAudio') : (episode.transcript?.draft || saved.revision > Number(episode.transcript?.revision ?? 0)) ? t('transcriptEditor.savedDraft', { revision: saved.revision }) : t('transcriptEditor.audioMatches')}</p></div>
      <Button type="button" size="sm" variant="outline" disabled={busy || active} onClick={() => setEditing(!editing)}>{editing ? t('transcriptEditor.readMode') : t('transcriptEditor.edit')}</Button>
    </div>
    <Input aria-label={t('transcriptEditor.search')} placeholder={t('transcriptEditor.search')} value={search} onChange={event => setSearch(event.target.value)} />
    <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-2">
      {turns.map((turn,index) => {
        if (search && !`${turn.speaker} ${turn.dialogue}`.toLowerCase().includes(search.toLowerCase())) return null
        return <div key={index} className="space-y-2 rounded-md border p-3">
          <p className="text-xs font-semibold">{index+1}. {turn.speaker}</p>
          {editing ? <Textarea aria-label={t('transcriptEditor.turn', { number:index+1, speaker:turn.speaker })} value={turn.dialogue} rows={4} disabled={busy || active} className="resize-y [field-sizing:content] text-sm leading-relaxed" onChange={event => { setTurns(current => current.map((item,i) => i===index ? {...item,dialogue:event.target.value} : item)); setOutput(null) }} /> : <p className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">{turn.dialogue}</p>}
        </div>
      })}
      {search && !turns.some(turn => `${turn.speaker} ${turn.dialogue}`.toLowerCase().includes(search.toLowerCase())) && <p className="text-sm text-muted-foreground">{t('transcriptEditor.noMatches')}</p>}
    </div>
    <div className="shrink-0 space-y-2 border-t bg-background pt-3">
      <p className="text-xs text-muted-foreground">{t('transcriptEditor.hint')}</p>
      <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={reuse} disabled={busy || active} onChange={event=>setReuse(event.target.checked)} />{t('transcriptEditor.reuse')}</label>
      {invalid && <p role="alert" className="text-xs text-destructive">{t('transcriptEditor.empty')}</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {output && <p role="status" className="text-sm">{output.status === 'completed' ? t('transcriptEditor.ready') : t('transcriptEditor.queued')} <a className="font-medium underline" href={`#${encodeURIComponent(output.episode_id)}`} onClick={() => onGoToEpisode(output.episode_id)}>{t('transcriptEditor.goToEpisode')}</a></p>}
      <div className="flex flex-wrap justify-end gap-2">
        {dirty && <Button type="button" variant="ghost" disabled={busy} onClick={()=>{setTurns(saved.entries);setError('')}}>{t('transcriptEditor.discard')}</Button>}
        <Button type="button" variant="outline" disabled={!dirty || busy || active || invalid} onClick={()=>void perform(false)}>{t('transcriptEditor.save')}</Button>
        <Button type="button" disabled={busy || active || invalid || (!dirty && !episode.transcript?.draft && saved.revision===Number(episode.transcript?.revision ?? 0))} onClick={()=>void perform(true)}>{busy ? t('transcriptEditor.working') : dirty ? t('transcriptEditor.saveAndGenerate') : t('transcriptEditor.generate')}</Button>
      </div>
    </div>
  </div>
}
