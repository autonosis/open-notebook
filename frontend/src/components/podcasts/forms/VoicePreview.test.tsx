import { useState } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi, test, expect, beforeEach } from 'vitest'
import apiClient from '@/lib/api/client'
import { VoicePreview, voiceLabel } from './VoicePreview'

vi.mock('@/lib/api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
vi.mock('@/lib/hooks/use-translation', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(apiClient.get).mockResolvedValue({ data: [{ id: 'af_heart', name: 'Heart' }, { id: 'af_bella', name: 'Bella' }, { id: 'am_michael', name: 'Michael' }] })
  vi.mocked(apiClient.post).mockResolvedValue({ data: new Blob(['audio'], { type: 'audio/mpeg' }) })
  URL.createObjectURL = vi.fn(() => 'blob:preview')
  URL.revokeObjectURL = vi.fn()
})

test('requires a selected model and voice before generating', () => {
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={query}><VoicePreview modelId="" voiceId="" inputId="voices" onVoiceChange={vi.fn()} /></QueryClientProvider>)
  expect(screen.getByRole('button').hasAttribute('disabled')).toBe(true)
  expect(apiClient.post).not.toHaveBeenCalled()
})

test('previews the selected model/voice without submitting and clears stale audio when changed', async () => {
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const submit = vi.fn()
  const view = (voice: string) => <QueryClientProvider client={query}><form onSubmit={submit}><VoicePreview modelId="model:kokoro" voiceId={voice} inputId="voices" onVoiceChange={vi.fn()} /></form></QueryClientProvider>
  const { rerender } = render(view('af_heart'))
  fireEvent.click(screen.getByRole('button'))
  await waitFor(() => expect(screen.getByLabelText('voicePreview.sample')).toBeTruthy())
  expect(apiClient.post).toHaveBeenCalledWith('/podcasts/voices/preview', { model_id: 'model:kokoro', voice_id: 'af_heart' }, expect.objectContaining({ responseType: 'blob' }))
  expect(submit).not.toHaveBeenCalled()
  rerender(view('am_michael'))
  expect(screen.queryByLabelText('voicePreview.sample')).toBeNull()
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:preview')
})


test('all catalog voices stay selectable after repeated preview and change cycles', async () => {
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  function Form() {
    const [voice, setVoice] = useState('af_heart')
    return <VoicePreview modelId="model:kokoro" voiceId={voice} inputId="voices" onVoiceChange={setVoice} />
  }
  render(<QueryClientProvider client={query}><Form /></QueryClientProvider>)
  const picker = screen.getByRole('combobox') as HTMLSelectElement
  await waitFor(() => expect(picker.disabled).toBe(false))
  for (const voice of ['af_heart', 'af_bella', 'am_michael']) {
    fireEvent.change(picker, { target: { value: voice } })
    fireEvent.click(screen.getByRole('button'))
    await waitFor(() => expect(screen.getByLabelText('voicePreview.sample')).toBeTruthy())
    expect(picker.value).toBe(voice)
    expect([...picker.options].map(option => option.value)).toEqual(['', 'af_heart', 'af_bella', 'am_michael'])
    expect(picker.disabled).toBe(false)
  }
  expect(vi.mocked(apiClient.post).mock.calls.map(call => call[1])).toEqual([
    { model_id: 'model:kokoro', voice_id: 'af_heart' },
    { model_id: 'model:kokoro', voice_id: 'af_bella' },
    { model_id: 'model:kokoro', voice_id: 'am_michael' },
  ])
})

 test('voice labels consistently expose name, language and gender without changing IDs', () => {
  const t = (key: string) => ({ 'voicePreview.americanEnglish': 'American English', 'voicePreview.mandarinChinese': 'Mandarin Chinese', 'voicePreview.female': 'Female', 'voicePreview.male': 'Male' }[key] || key)
  expect(voiceLabel({ id: 'af_heart', name: 'af_heart' }, t)).toBe('Heart — American English · Female')
  expect(voiceLabel({ id: 'zm_yunxi', name: 'zm_yunxi' }, t)).toBe('Yunxi — Mandarin Chinese · Male')
  expect(voiceLabel({ id: 'af_v0bella', name: 'af_v0bella' }, t)).toBe('V0 Bella — American English · Female')
  expect(voiceLabel({ id: 'custom', name: 'Provider Voice' }, t)).toBe('Provider Voice')
})
