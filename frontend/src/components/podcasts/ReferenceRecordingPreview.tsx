'use client'

import { useEffect, useRef, useState } from 'react'
import { Play, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/hooks/use-translation'

/** Decode untrusted reference bytes as audio; never interpret them as a URL or HTML. */
export function ReferenceRecordingPreview({
  file,
  disabled = false,
}: {
  file: File
  disabled?: boolean
}) {
  const { t } = useTranslation()
  const [playing, setPlaying] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)
  const [duration, setDuration] = useState<number | null>(null)
  const context = useRef<AudioContext | null>(null)
  const source = useRef<AudioBufferSourceNode | null>(null)
  const version = useRef(0)
  const stop = () => {
    version.current += 1
    source.current?.stop()
    source.current = null
    if (context.current) void context.current.close().catch(() => {})
    context.current = null
    setPlaying(false)
    setLoading(false)
  }
  useEffect(() => {
    version.current += 1
    setPlaying(false)
    setLoading(false)
    setError(false)
    setDuration(null)
    return () => {
      version.current += 1
      source.current?.stop()
      source.current = null
      if (context.current) void context.current.close().catch(() => {})
      context.current = null
    }
  }, [file, disabled])
  const play = async () => {
    stop()
    const current = version.current
    setLoading(true)
    setError(false)
    try {
      const audio = new AudioContext()
      context.current = audio
      await audio.resume()
      const buffer = await audio.decodeAudioData(await file.arrayBuffer())
      if (current !== version.current) return
      const node = audio.createBufferSource()
      node.buffer = buffer
      node.connect(audio.destination)
      source.current = node
      setDuration(buffer.duration)
      node.onended = () => {
        if (current === version.current) {
          source.current = null
          setPlaying(false)
          void audio.close().catch(() => {})
          context.current = null
        }
      }
      node.start()
      setPlaying(true)
    } catch {
      if (current === version.current) {
        setError(true)
        stop()
      }
    } finally {
      if (current === version.current) setLoading(false)
    }
  }
  return (
    <div
      role="group"
      aria-label={t('voiceCloning.referencePlayback')}
      className="space-y-2 rounded-md border p-3"
    >
      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled || loading}
          onClick={playing ? stop : play}
        >
          {playing ? (
            <Square className="mr-2 size-4" />
          ) : (
            <Play className="mr-2 size-4" />
          )}
          {t(
            playing
              ? 'voiceCloning.stopPlayback'
              : loading
                ? 'voiceCloning.loadingPlayback'
                : 'voiceCloning.playRecording',
          )}
        </Button>
        {duration !== null && (
          <span className="text-xs text-muted-foreground">
            {t('voiceCloning.recordingLength', {
              seconds: duration.toFixed(1),
            })}
          </span>
        )}
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {t('voiceCloning.playbackError')}
        </p>
      )}
    </div>
  )
}
