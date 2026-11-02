import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi, test, expect, beforeEach } from 'vitest'
import apiClient from '@/lib/api/client'
import { VoicePreview } from './VoicePreview'

vi.mock('@/lib/api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
vi.mock('@/lib/hooks/use-translation', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(apiClient.get).mockResolvedValue({ data: [{ id: 'af_heart', name: 'Heart' }] })
  vi.mocked(apiClient.post).mockResolvedValue({ data: new Blob(['audio'], { type: 'audio/mpeg' }) })
  URL.createObjectURL = vi.fn(() => 'blob:preview')
  URL.revokeObjectURL = vi.fn()
})

test('requires a selected model and voice before generating', () => {
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={query}><VoicePreview modelId="" voiceId="" listId="voices" /></QueryClientProvider>)
  expect(screen.getByRole('button').hasAttribute('disabled')).toBe(true)
  expect(apiClient.post).not.toHaveBeenCalled()
})

test('previews the selected model/voice without submitting and clears stale audio when changed', async () => {
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const submit = vi.fn()
  const view = (voice: string) => <QueryClientProvider client={query}><form onSubmit={submit}><VoicePreview modelId="model:kokoro" voiceId={voice} listId="voices" /></form></QueryClientProvider>
  const { rerender } = render(view('af_heart'))
  fireEvent.click(screen.getByRole('button'))
  await waitFor(() => expect(screen.getByLabelText('voicePreview.sample')).toBeTruthy())
  expect(apiClient.post).toHaveBeenCalledWith('/podcasts/voices/preview', { model_id: 'model:kokoro', voice_id: 'af_heart' }, expect.objectContaining({ responseType: 'blob' }))
  expect(submit).not.toHaveBeenCalled()
  rerender(view('am_michael'))
  expect(screen.queryByLabelText('voicePreview.sample')).toBeNull()
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:preview')
})
