import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { vi, test, expect, beforeEach } from 'vitest'
import { VoiceCloningTab } from './VoiceCloningTab'

const state = vi.hoisted(() => ({
  save: vi.fn(),
  archive: vi.fn(),
  reset: vi.fn(),
  rows: [] as {
    id: string
    name: string
    duration_s: number
    archived: boolean
    created: number
  }[],
}))
vi.mock('@/lib/hooks/use-translation', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))
vi.mock('@/lib/hooks/use-voice-cloning', () => ({
  useCloningModels: () => ({
    data: [
      { id: 'm:c', name: 'chatterbox', supported: true },
      { id: 'm:k', name: 'kokoro', supported: false },
    ],
    isLoading: false,
  }),
  useClonedVoices: () => ({ data: state.rows, isLoading: false }),
  useSaveClone: () => ({
    mutateAsync: state.save,
    isPending: false,
    reset: state.reset,
  }),
  useArchiveClone: () => ({ mutate: state.archive, isPending: false }),
}))
vi.mock('./forms/VoicePreview', () => ({
  VoiceAudition: ({ voiceId }: { voiceId: string }) => <div>{voiceId}</div>,
}))
vi.mock('./forms/SpeakerProfileFormDialog', () => ({
  SpeakerProfileFormDialog: ({
    open,
    initialData,
  }: {
    open: boolean
    initialData?: { voice_model: string; speakers: { voice_id: string }[] }
  }) =>
    open ? (
      <div data-testid="profile">
        {initialData?.voice_model} {initialData?.speakers[0].voice_id}
      </div>
    ) : null,
}))
beforeEach(() => {
  vi.clearAllMocks()
  state.rows = []
  state.save.mockResolvedValue({ name: 'My voice' })
  URL.createObjectURL = vi.fn(() => `blob:${window.location.origin}/reference`)
  URL.revokeObjectURL = vi.fn()
})

test('only capable models are selectable; uploads are saved with a name and can be auditioned first', async () => {
  render(<VoiceCloningTab />)
  expect(screen.queryByRole('option', { name: 'kokoro' })).toBeNull()
  fireEvent.change(screen.getByLabelText('voiceCloning.name'), {
    target: { value: 'My voice' },
  })
  const file = new File(['recording'], 'speech.wav', { type: 'audio/wav' })
  fireEvent.change(screen.getByLabelText('voiceCloning.reference'), {
    target: { files: [file] },
  })
  expect(
    await screen.findByLabelText('voiceCloning.referencePlayback'),
  ).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'voiceCloning.save' }))
  await waitFor(() =>
    expect(state.save).toHaveBeenCalledWith({ name: 'My voice', file }),
  )
})

test('saved voice pre-fills a new speaker profile and archive is reversible', () => {
  state.rows = [
    {
      id: 'clone_test',
      name: 'My voice',
      duration_s: 10,
      archived: false,
      created: 1,
    },
  ]
  const { rerender } = render(<VoiceCloningTab />)
  fireEvent.click(screen.getByRole('button', { name: 'voiceCloning.use' }))
  expect(screen.getByTestId('profile').textContent).toContain('m:c clone_test')
  fireEvent.click(screen.getByRole('button', { name: 'voiceCloning.archive' }))
  expect(state.archive).toHaveBeenCalledWith({
    id: 'clone_test',
    archived: true,
  })
  state.rows = [{ ...state.rows[0], archived: true }]
  rerender(<VoiceCloningTab />)
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button', { name: 'voiceCloning.restore' }))
  expect(state.archive).toHaveBeenCalledWith({
    id: 'clone_test',
    archived: false,
  })
})

test('microphone permission failure offers an upload fallback without saving', async () => {
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: vi.fn().mockRejectedValue(new Error('denied')) },
  })
  vi.stubGlobal(
    'MediaRecorder',
    class {
      static isTypeSupported() {
        return true
      }
    },
  )
  render(<VoiceCloningTab />)
  fireEvent.click(screen.getByRole('button', { name: 'voiceCloning.record' }))
  expect(await screen.findByRole('alert')).toHaveProperty(
    'textContent',
    'voiceCloning.recordError',
  )
  expect(state.save).not.toHaveBeenCalled()
})

test('microphone stream is released if the user leaves while permission is pending', async () => {
  const stop = vi.fn()
  let resolve: (value: unknown) => void = () => {}
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia: vi.fn(
        () =>
          new Promise((r) => {
            resolve = r
          }),
      ),
    },
  })
  const { unmount } = render(<VoiceCloningTab />)
  fireEvent.click(screen.getByRole('button', { name: 'voiceCloning.record' }))
  unmount()
  resolve({ getTracks: () => [{ stop }] })
  await waitFor(() => expect(stop).toHaveBeenCalled())
})

test('recording produces a playable upload and stops all microphone tracks', async () => {
  const stop = vi.fn()
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop }] }),
    },
  })
  class Recorder {
    static isTypeSupported() {
      return true
    }
    mimeType = 'audio/webm'
    state = 'inactive'
    ondataavailable: ((event: { data: Blob }) => void) | null = null
    onstop: (() => void) | null = null
    start() {
      this.state = 'recording'
    }
    stop() {
      this.state = 'inactive'
      this.ondataavailable?.({ data: new Blob(['synthetic audio']) })
      this.onstop?.()
    }
  }
  vi.stubGlobal('MediaRecorder', Recorder)
  render(<VoiceCloningTab />)
  fireEvent.click(screen.getByRole('button', { name: 'voiceCloning.record' }))
  fireEvent.click(
    await screen.findByRole('button', { name: 'voiceCloning.stop' }),
  )
  expect(
    await screen.findByLabelText('voiceCloning.referencePlayback'),
  ).toBeTruthy()
  expect(stop).toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText('voiceCloning.name'), {
    target: { value: 'Recorded voice' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'voiceCloning.save' }))
  await waitFor(() =>
    expect(state.save).toHaveBeenCalledWith({
      name: 'Recorded voice',
      file: expect.any(File),
    }),
  )
})

test('reference playback rejects unexpected non-blob resource URLs', async () => {
  URL.createObjectURL = vi.fn(() => 'javascript:alert(1)')
  render(<VoiceCloningTab />)
  fireEvent.change(screen.getByLabelText('voiceCloning.reference'), {
    target: { files: [new File(['audio'], 'recording.wav')] },
  })
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(screen.queryByLabelText('voiceCloning.referencePlayback')).toBeNull()
})
