'use client'

import { PodcastEpisode } from '@/lib/types/podcasts'
import { useTranslation } from '@/lib/hooks/use-translation'

export function PodcastPipeline({ episode }: { episode: PodcastEpisode }) {
  const { t } = useTranslation()
  const p = episode.pipeline_progress
  const label = (stage: string) => t(`podcastProgress.${stage}`)
  const duration = (seconds: number) => `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`
  return <section aria-label={t('podcastProgress.title')} className="space-y-3 rounded-md border p-4 [overflow-wrap:anywhere]" aria-live="polite">
    <h4 className="text-sm font-semibold">{t('podcastProgress.title')}</h4>
    {!p ? <p className="text-sm text-muted-foreground">{t('podcastProgress.unavailable')}</p> : <>
      <p className="font-medium">{label(p.stage)}</p>
      <dl className="grid gap-2 text-sm sm:grid-cols-2">
        <div><dt className="text-muted-foreground">{t('podcastProgress.elapsed')}</dt><dd>{duration(p.elapsed_s)}</dd></div>
        <div><dt className="text-muted-foreground">{t('podcastProgress.stageElapsed')}</dt><dd>{duration(p.stage_elapsed_s)}</dd></div>
        {p.sections_total != null && <div><dt className="text-muted-foreground">{t('podcastProgress.sections')}</dt><dd>{p.sections_done ?? 0} / {p.sections_total}</dd></div>}
        {p.clips_total != null && <div><dt className="text-muted-foreground">{t('podcastProgress.clips')}</dt><dd>{p.clips_done ?? 0} / {p.clips_total}</dd></div>}
        {p.clips_reused != null && <div><dt className="text-muted-foreground">{t('transcriptEditor.clipsReused')}</dt><dd>{p.clips_reused}</dd></div>}
        {p.stage === 'speech'  && p.current_clip != null && <div><dt className="text-muted-foreground">{t('podcastProgress.currentClip')}</dt><dd>{p.current_clip}</dd></div>}
        <div><dt className="text-muted-foreground">{t('podcastProgress.updated')}</dt><dd>{new Date(p.updated_at * 1000).toLocaleTimeString()}</dd></div>
      </dl>
      {p.error_type && <p className="text-sm text-destructive">{t('podcastProgress.error')}: {p.error_type}</p>}
      {p.command_id && <p className="font-mono text-xs text-muted-foreground">{t('podcastProgress.job')}: {p.command_id}</p>}
      {p.timeline && p.timeline.length > 0 && <details><summary className="cursor-pointer text-sm">{t('podcastProgress.history')}</summary><ol className="mt-2 space-y-1 text-xs text-muted-foreground">{p.timeline.map((event,index) => <li key={`${event.at}-${index}`}>{new Date(event.at * 1000).toLocaleTimeString()} · {label(event.stage)}{event.duration_s != null ? ` · ${duration(event.duration_s)}` : ''}</li>)}</ol></details>}
      {!['completed','failed','error'].includes(episode.job_status ?? '') && <p className="text-xs text-muted-foreground">{t('podcastProgress.refresh')}</p>}
    </>}
  </section>
}
