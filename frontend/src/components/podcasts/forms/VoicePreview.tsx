'use client'

import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import apiClient from '@/lib/api/client'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/hooks/use-translation'

const voiceLanguages: Record<string, string> = {
  a: 'voicePreview.americanEnglish', b: 'voicePreview.britishEnglish', z: 'voicePreview.mandarinChinese',
  j: 'voicePreview.japanese', e: 'voicePreview.spanish', f: 'voicePreview.french', h: 'voicePreview.hindi',
  i: 'voicePreview.italian', p: 'voicePreview.brazilianPortuguese',
}

export function voiceLabel(voice: { id: string; name: string }, t: (key: string) => string) {
  const match = /^([abzjefhip])([fm])_(.+)$/.exec(voice.id)
  if (!match) return voice.name || voice.id
  const name = match[3].replace(/^v0(?=[a-z])/, 'v0 ').split(/[_ ]+/)
    .map(part => part.charAt(0).toUpperCase() + part.slice(1)).join(' ')
  return `${name} — ${t(voiceLanguages[match[1]])} · ${t(match[2] === 'f' ? 'voicePreview.female' : 'voicePreview.male')}`
}

export function VoicePreview({ modelId, voiceId, inputId, onVoiceChange }: { modelId: string; voiceId: string; inputId: string; onVoiceChange: (voice: string) => void }) {
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
    <select id={inputId} aria-label={t('podcasts.voiceId')} value={voiceId || ''} disabled={!modelId || !voices?.length}
      onChange={event => onVoiceChange(event.target.value)}
      className="h-10 w-full min-w-0 rounded-md border border-input bg-background px-3 text-sm text-foreground disabled:opacity-50">
      <option value="" disabled>{t('voicePreview.chooseVoice')}</option>
      {voiceId && !voices?.some(voice => voice.id === voiceId) && <option value={voiceId}>{voiceId}</option>}
      {voices?.map(voice => <option key={voice.id} value={voice.id}>{voiceLabel(voice, t)}</option>)}
    </select>
    <details className="text-xs text-muted-foreground">
      <summary className="cursor-pointer">{t('voicePreview.customVoice')}</summary>
      <Input className="mt-2" aria-label={t('voicePreview.customVoice')} value={voiceId || ''} onChange={event => onVoiceChange(event.target.value)} autoComplete="off" />
    </details>
    <p className="text-xs text-muted-foreground">{modelId ? t('voicePreview.hint') : t('voicePreview.needsModel')}</p>
    <Button type="button" variant="outline" size="sm" disabled={!modelId || !voiceId?.trim() || loading} onClick={preview}>{loading ? t('voicePreview.loading') : t('voicePreview.preview')}</Button>
    {error && <p role="alert" className="text-xs text-destructive">{t('voicePreview.error')}</p>}
    {url && <audio aria-label={t('voicePreview.sample')} controls autoPlay src={url} className="w-full" />}
  </div>
}
