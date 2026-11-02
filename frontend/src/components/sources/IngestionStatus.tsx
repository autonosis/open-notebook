'use client'

import { useQuery } from '@tanstack/react-query'
import apiClient from '@/lib/api/client'

type Job = { id: string; name: string; status: string; duration_s?: number }
type SourceProgress = {
  warnings?: string[]; source_id: string; title: string; status: string; stage: string
  elapsed_s?: number; text_chars: number; embedded_chunks: number; insights_count: number
  pages_done?: number; pages_total?: number; page_batch_start?: number; page_batch_end?: number;
  chunks_done?: number; chunks_total?: number; transformation?: string; error?: string; jobs: Job[]
}

export function IngestionStatus() {
  const { data, error, dataUpdatedAt } = useQuery<{ sources: SourceProgress[] }>({
    queryKey: ['ingestion-observability'],
    queryFn: async () => (await apiClient.get('/observability/sources')).data,
    refetchInterval: 3000,
    refetchIntervalInBackground: false,
    retry: 1,
  })
  return (
    <section aria-label="Source processing activity" className="mb-4 rounded-md border p-4 flex-shrink-0 max-h-[40vh] overflow-y-auto [overflow-wrap:anywhere]">
      <div className="flex flex-wrap justify-between gap-2 mb-2">
        <h2 className="font-semibold">Processing activity</h2>
        <span className="text-xs text-muted-foreground">{error ? 'Status refresh failed — displayed data may be stale' : dataUpdatedAt ? 'Refreshes every 3 seconds' : 'Loading status…'}</span>
      </div>
      {data?.sources.map(source => (
        <details key={source.source_id} className="border-t py-2" open={source.status !== 'completed'}>
          <summary className="cursor-pointer">
            <span className="font-medium">{source.title}</span>
            <span className={source.status === 'failed' ? 'ml-3 text-destructive' : 'ml-3 text-muted-foreground'}>{source.stage}</span>
            {source.elapsed_s != null && <span className="ml-2 text-xs">{Math.floor(source.elapsed_s / 60)}m {Math.floor(source.elapsed_s % 60)}s elapsed</span>}
          </summary>
          <div className="mt-2 text-sm space-y-1 pl-4">
            <p>{source.text_chars.toLocaleString()} extracted characters · {source.embedded_chunks.toLocaleString()} indexed chunks · {source.insights_count} saved transformations</p>
            {source.chunks_total != null && <p>Embedding generation: {source.chunks_done ?? 0} / {source.chunks_total} chunks. Search becomes ready after all chunks are saved.</p>}
            {source.transformation && <p>Transformation: {source.transformation}</p>}
            {source.pages_total != null && <p>PDF extraction: {source.pages_done ?? 0} / {source.pages_total} pages completed{source.status === 'running' && (source.pages_done ?? 0) < source.pages_total && source.page_batch_start ? ` · current batch ${source.page_batch_start}–${source.page_batch_end}` : ''}.</p>}
            {source.stage.includes('Extract') && source.pages_total == null && <p>Text/OCR, formula and image analysis are running. Page count is not yet available.</p>}
            {source.warnings?.map(warning => <p key={warning} className="text-muted-foreground">{warning}</p>)}
            {source.error && <p className="text-destructive">{source.error}</p>}
            <ul className="font-mono text-xs text-muted-foreground" aria-label={`Jobs for ${source.title}`}>
              {source.jobs.map(job => <li key={job.id}>{job.name}: {job.status}{job.duration_s != null ? ` · ${job.duration_s.toFixed(1)}s` : ''} · {job.id}</li>)}
            </ul>
          </div>
        </details>
      ))}
    </section>
  )
}
