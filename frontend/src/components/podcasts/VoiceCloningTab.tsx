'use client'

import { useEffect, useRef, useState } from 'react'
import { Mic, Square, Upload, AudioLines } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useTranslation } from '@/lib/hooks/use-translation'
import {
  useCloningModels,
  useClonedVoices,
  useSaveClone,
  useArchiveClone,
  type ClonedVoice,
} from '@/lib/hooks/use-voice-cloning'
import { VoiceAudition } from './forms/VoicePreview'
import { ReferenceRecordingPreview } from './ReferenceRecordingPreview'
import { SpeakerProfileFormDialog } from './forms/SpeakerProfileFormDialog'
import type { SpeakerProfile } from '@/lib/types/podcasts'

function message(error: unknown, fallback: string) {
  return (
    (error as { response?: { data?: { detail?: string } } })?.response?.data
      ?.detail || fallback
  )
}

export function VoiceCloningTab() {
  const { t } = useTranslation()
  const models = useCloningModels()
  const [selection, setSelection] = useState('')
  const modelId = selection || models.data?.find((m) => m.supported)?.id || ''
  const requiresReferenceText = Boolean(
    models.data?.find((m) => m.id === modelId)?.requires_reference_text,
  )
  const voices = useClonedVoices(modelId)
  const save = useSaveClone(modelId)
  const archive = useArchiveClone(modelId)
  const [name, setName] = useState('')
  const [referenceText, setReferenceText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [recording, setRecording] = useState(false)
  const [seconds, setSeconds] = useState(0)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [showArchived, setShowArchived] = useState(false)
  const [profile, setProfile] = useState<SpeakerProfile | undefined>()
  const recorder = useRef<MediaRecorder | null>(null)
  const stream = useRef<MediaStream | null>(null)
  const upload = useRef<HTMLInputElement | null>(null)
  const alive = useRef(true)
  const busy = save.isPending || recording || starting
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
      if (recorder.current?.state === 'recording') recorder.current.stop()
      stream.current?.getTracks().forEach((track) => track.stop())
    }
  }, [])
  useEffect(() => {
    if (!recording) return
    const timer = setInterval(
      () =>
        setSeconds((n) => {
          if (n >= 29) recorder.current?.stop()
          return n + 1
        }),
      1000,
    )
    return () => clearInterval(timer)
  }, [recording])
  const choose = (next?: File) => {
    setSuccess('')
    setError('')
    save.reset()
    if (next && next.size > 10 * 1024 * 1024) {
      setError(t('voiceCloning.tooLarge'))
      setFile(null)
      return
    }
    setFile(next || null)
  }
  const record = async () => {
    setError('')
    setSuccess('')
    setStarting(true)
    try {
      if (
        !navigator.mediaDevices?.getUserMedia ||
        typeof MediaRecorder === 'undefined'
      )
        throw new Error('unsupported')
      const media = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (!alive.current) {
        media.getTracks().forEach((track) => track.stop())
        return
      }
      stream.current = media
      const type = [
        'audio/webm;codecs=opus',
        'audio/mp4',
        'audio/ogg;codecs=opus',
      ].find((v) => MediaRecorder.isTypeSupported(v))
      const rec = new MediaRecorder(
        media,
        type ? { mimeType: type } : undefined,
      )
      recorder.current = rec
      const chunks: Blob[] = []
      rec.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data)
      }
      rec.onstop = () => {
        media.getTracks().forEach((track) => track.stop())
        if (alive.current) {
          choose(new File(chunks, 'voice-recording', { type: rec.mimeType }))
          setRecording(false)
        }
      }
      rec.onerror = () => {
        media.getTracks().forEach((track) => track.stop())
        if (alive.current) {
          setRecording(false)
          setError(t('voiceCloning.recordError'))
        }
      }
      setSeconds(0)
      rec.start()
      setRecording(true)
    } catch {
      stream.current?.getTracks().forEach((track) => track.stop())
      setError(t('voiceCloning.recordError'))
    } finally {
      if (alive.current) setStarting(false)
    }
  }
  const create = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!file) return
    setError('')
    setSuccess('')
    try {
      const voice = await save.mutateAsync({
        name: name.trim(),
        file,
        ...(requiresReferenceText
          ? { referenceText: referenceText.trim() }
          : {}),
      })
      setSuccess(t('voiceCloning.saved', { name: voice.name }))
      setFile(null)
      setName('')
      setReferenceText('')
      if (upload.current) upload.current.value = ''
    } catch (err) {
      setError(message(err, t('voiceCloning.saveError')))
    }
  }
  const createProfileForVoice = (voice: ClonedVoice) =>
    setProfile({
      id: '',
      name: voice.name,
      description: '',
      voice_model: modelId,
      speakers: [
        {
          name: voice.name,
          voice_id: voice.id,
          backstory: t('voiceCloning.defaultBackstory'),
          personality: t('voiceCloning.defaultPersonality'),
        },
      ],
    })
  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h2 className="font-display text-xl font-semibold">
          {t('voiceCloning.title')}
        </h2>
        <p className="max-w-2xl text-sm text-muted-foreground">
          {t('voiceCloning.description')}
        </p>
      </header>
      {models.isLoading ? (
        <p role="status">{t('common.loading')}</p>
      ) : models.isError ? (
        <div role="alert">
          <p>{t('voiceCloning.modelsError')}</p>
          <Button variant="outline" onClick={() => models.refetch()}>
            {t('common.retry')}
          </Button>
        </div>
      ) : (
        <>
          <div className="grid min-w-0 items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <form
              onSubmit={create}
              className="min-w-0 space-y-5 rounded-lg border bg-card p-5"
            >
              <h3 className="font-medium">{t('voiceCloning.create')}</h3>
              <div className="space-y-2">
                <Label htmlFor="clone-model">{t('podcasts.voiceModel')}</Label>
                <select
                  id="clone-model"
                  value={modelId}
                  disabled={busy}
                  onChange={(event) => {
                    setSelection(event.target.value)
                    setError('')
                    setSuccess('')
                  }}
                  className="h-10 w-full min-w-0 rounded-md border bg-background px-3 text-sm"
                >
                  {!modelId && (
                    <option value="">{t('voiceCloning.noModel')}</option>
                  )}
                  {models.data
                    ?.filter((m) => m.supported)
                    .map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                </select>
                <p className="text-xs text-muted-foreground">
                  {t('voiceCloning.local')}
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="clone-name">{t('voiceCloning.name')}</Label>
                <Input
                  id="clone-name"
                  maxLength={80}
                  value={name}
                  disabled={busy || !modelId}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={t('voiceCloning.namePlaceholder')}
                  required
                />
              </div>
              {requiresReferenceText && (
                <div className="space-y-2">
                  <Label htmlFor="clone-reference-text">
                    {t('voiceCloning.referenceText')}
                  </Label>
                  <Textarea
                    id="clone-reference-text"
                    value={referenceText}
                    onChange={(event) => setReferenceText(event.target.value)}
                    maxLength={4000}
                    required
                    disabled={busy}
                    placeholder={t('voiceCloning.referenceTextPlaceholder')}
                  />
                  <p className="text-xs text-muted-foreground">
                    {t('voiceCloning.referenceTextHint')}
                  </p>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() =>
                      setReferenceText(
                        t('voiceCloning.referenceTextSuggestion'),
                      )
                    }
                  >
                    {t('voiceCloning.useSuggestedText')}
                  </Button>
                </div>
              )}
              <div className="space-y-3">
                <Label htmlFor="clone-file">
                  {t('voiceCloning.reference')}
                </Label>
                <p className="text-sm text-muted-foreground">
                  {t('voiceCloning.sampleHint')}
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    disabled={!modelId || save.isPending || starting}
                    onClick={
                      recording ? () => recorder.current?.stop() : record
                    }
                  >
                    {recording ? (
                      <Square className="mr-2 size-4" />
                    ) : (
                      <Mic className="mr-2 size-4" />
                    )}
                    {recording
                      ? t('voiceCloning.stop', { seconds })
                      : starting
                        ? t('voiceCloning.starting')
                        : t('voiceCloning.record')}
                  </Button>
                  {recording && (
                    <span
                      role="status"
                      className="text-sm text-muted-foreground"
                    >
                      {t('voiceCloning.recording', { seconds })}
                    </span>
                  )}
                </div>
                <div className="rounded-md border border-dashed p-3">
                  <Label
                    htmlFor="clone-file"
                    className="mb-2 flex items-center gap-2"
                  >
                    <Upload className="size-4" />
                    {t('voiceCloning.upload')}
                  </Label>
                  <input
                    ref={upload}
                    id="clone-file"
                    type="file"
                    accept="audio/*,.m4a,.wav,.mp3,.flac,.ogg,.webm"
                    disabled={!modelId || busy}
                    onChange={(e) => choose(e.target.files?.[0])}
                    className="block w-full min-w-0 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-muted file:px-3 file:py-2 file:text-foreground"
                  />
                </div>
                {file && (
                  <p className="break-all text-xs text-muted-foreground">
                    {file.name}
                  </p>
                )}
                {file && (
                  <ReferenceRecordingPreview
                    file={file}
                    disabled={recording || starting}
                  />
                )}
              </div>
              {error && (
                <p role="alert" className="text-sm text-destructive">
                  {error}
                </p>
              )}
              {success && (
                <p role="status" className="text-sm text-teal">
                  {success}
                </p>
              )}
              <Button
                type="submit"
                disabled={
                  !modelId ||
                  !name.trim() ||
                  !file ||
                  busy ||
                  (requiresReferenceText && !referenceText.trim())
                }
              >
                {save.isPending
                  ? t('voiceCloning.saving')
                  : t('voiceCloning.save')}
              </Button>
            </form>
            <section className="min-w-0 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="font-medium">{t('voiceCloning.library')}</h3>
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={showArchived}
                    onChange={(e) => setShowArchived(e.target.checked)}
                  />
                  {t('voiceCloning.showArchived')}
                </label>
              </div>
              {voices.isError && (
                <p role="alert">{t('voiceCloning.libraryError')}</p>
              )}
              {voices.isLoading && <p role="status">{t('common.loading')}</p>}
              {!voices.isLoading &&
                !voices.isError &&
                !voices.data?.some((v) => showArchived || !v.archived) && (
                  <div className="space-y-2 rounded-lg border border-dashed p-6">
                    <AudioLines className="size-6 text-muted-foreground" />
                    <p className="font-medium">{t('voiceCloning.empty')}</p>
                    <p className="text-sm text-muted-foreground">
                      {t('voiceCloning.emptyHint')}
                    </p>
                  </div>
                )}
              {voices.data
                ?.filter((v) => showArchived || !v.archived)
                .map((voice) => (
                  <article
                    key={voice.id}
                    className="min-w-0 space-y-3 rounded-lg border bg-card p-4"
                  >
                    <div>
                      <h4 className="break-words font-medium">
                        {voice.name}
                        {voice.archived
                          ? ` · ${t('voiceCloning.archived')}`
                          : ''}
                      </h4>
                      <p className="text-xs text-muted-foreground">
                        {t('voiceCloning.referenceLength', {
                          seconds: voice.duration_s,
                        })}
                      </p>
                    </div>
                    <VoiceAudition modelId={modelId} voiceId={voice.id} />
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={voice.archived}
                        onClick={() => createProfileForVoice(voice)}
                      >
                        {t('voiceCloning.use')}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={archive.isPending}
                        onClick={() =>
                          archive.mutate({
                            id: voice.id,
                            archived: !voice.archived,
                          })
                        }
                      >
                        {t(
                          voice.archived
                            ? 'voiceCloning.restore'
                            : 'voiceCloning.archive',
                        )}
                      </Button>
                    </div>
                  </article>
                ))}
              {archive.isError && (
                <p role="alert" className="text-sm text-destructive">
                  {t('voiceCloning.archiveError')}
                </p>
              )}
              <p className="text-xs text-muted-foreground">
                {t('voiceCloning.useHint')}
              </p>
            </section>
          </div>
          <details className="rounded-lg border px-4 py-3 text-sm">
            <summary className="cursor-pointer font-medium">
              {t('voiceCloning.support')}
            </summary>
            <ul className="mt-3 space-y-2 text-muted-foreground">
              {models.data?.map((model) => (
                <li key={model.id}>
                  <span className="text-foreground">{model.name}</span>
                  {' — '}
                  {t(
                    model.supported
                      ? 'voiceCloning.supported'
                      : model.reason === 'preset_only'
                        ? 'voiceCloning.presetOnly'
                        : model.reason === 'unavailable'
                          ? 'voiceCloning.unavailable'
                          : 'voiceCloning.unsupported',
                  )}
                </li>
              ))}
            </ul>
          </details>
        </>
      )}
      <SpeakerProfileFormDialog
        mode="create"
        open={Boolean(profile)}
        onOpenChange={(open) => {
          if (!open) setProfile(undefined)
        }}
        initialData={profile}
      />
    </div>
  )
}
