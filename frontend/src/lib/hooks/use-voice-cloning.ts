import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient from '@/lib/api/client'

export interface CloningModel {
  id: string
  name: string
  supported: boolean
  reason?: string
  language?: string
}
export interface ClonedVoice {
  id: string
  name: string
  duration_s: number
  archived: boolean
  created: number
}
export const CLONE_KEYS = {
  models: ['voice-cloning-models'],
  voices: (id: string) => ['voice-clones', id],
}
export function useCloningModels() {
  return useQuery<CloningModel[]>({
    queryKey: CLONE_KEYS.models,
    queryFn: async () =>
      (await apiClient.get('/podcasts/voice-cloning/models')).data,
    retry: false,
  })
}
export function useClonedVoices(modelId: string) {
  return useQuery<ClonedVoice[]>({
    queryKey: CLONE_KEYS.voices(modelId),
    queryFn: async () =>
      (
        await apiClient.get('/podcasts/voice-cloning/voices', {
          params: { model_id: modelId, archived: true },
        })
      ).data,
    enabled: Boolean(modelId),
    retry: false,
  })
}
export function useSaveClone(modelId: string) {
  const cache = useQueryClient()
  return useMutation({
    mutationFn: async ({ name, file }: { name: string; file: File }) => {
      const data = new FormData()
      data.append('model_id', modelId)
      data.append('name', name)
      data.append('file', file)
      return (
        await apiClient.post<ClonedVoice>(
          '/podcasts/voice-cloning/voices',
          data,
        )
      ).data
    },
    onSuccess: async () => {
      await cache.invalidateQueries({ queryKey: CLONE_KEYS.voices(modelId) })
      await cache.invalidateQueries({
        queryKey: ['tts-voice-catalog', modelId],
      })
    },
  })
}
export function useArchiveClone(modelId: string) {
  const cache = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, archived }: { id: string; archived: boolean }) =>
      (
        await apiClient.patch(
          `/podcasts/voice-cloning/voices/${id}`,
          { archived },
          { params: { model_id: modelId } },
        )
      ).data,
    onSuccess: async () => {
      await cache.invalidateQueries({ queryKey: CLONE_KEYS.voices(modelId) })
      await cache.invalidateQueries({
        queryKey: ['tts-voice-catalog', modelId],
      })
    },
  })
}
