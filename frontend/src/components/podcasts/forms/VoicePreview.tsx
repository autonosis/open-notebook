'use client'

import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import apiClient from '@/lib/api/client'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/hooks/use-translation'

export function VoicePreview({ modelId, voiceId, listId }: { modelId: string; voiceId: string; listId: string }) {
  const { t } = useTranslation()
  const [url, setUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)
  const request = useRef<AbortController | null>(null)
  const blobUrl = useRef<string | null>(null)
  const { data: voices } = useQuery<{ id: string; name: string }[]>({
    queryKey: ['tts-voice-catalog', modelId],
    queryFn: async () => (await apiClient.get('/podcasts/voices', { params: { model_id: modelId } })).data,
    enabled: Boolean(modelId), staleTime: 300000, retry: false,
  })
  useEffect(() => {
    setUrl(null); setError(false); setLoading(false)
    return () => {
      request.current?.abort()
      if (blobUrl.current) URL.revokeObjectURL(blobUrl.current)
      blobUrl.current = null
    }
  }, [modelId, voiceId])
  const preview = async () => {
    request.current?.abort()
    const controller = new AbortController()
    request.current = controller
    setLoading(true); setError(false)
    try {
      const result = await apiClient.post('/podcasts/voices/preview', { model_id: modelId, voice_id: voiceId }, { responseType: 'blob', signal: controller.signal })
      if (controller.signal.aborted) return
      if (blobUrl.current) URL.revokeObjectURL(blobUrl.current)
      blobUrl.current = URL.createObjectURL(result.data)
      setUrl(blobUrl.current)
    } catch {
      if (!controller.signal.aborted) setError(true)
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }
  return <div className="space-y-2">
    <datalist id={listId}>{voices?.map(voice => <option key={voice.id} value={voice.id}>{voice.name}</option>)}</datalist>
    <p className="text-xs text-muted-foreground">{modelId ? t('voicePreview.hint') : t('voicePreview.needsModel')}</p>
    <Button type="button" variant="outline" size="sm" disabled={!modelId || !voiceId?.trim() || loading} onClick={preview}>{loading ? t('voicePreview.loading') : t('voicePreview.preview')}</Button>
    {error && <p role="alert" className="text-xs text-destructive">{t('voicePreview.error')}</p>}
    {url && <audio aria-label={t('voicePreview.sample')} controls autoPlay src={url} className="w-full" />}
  </div>
}
