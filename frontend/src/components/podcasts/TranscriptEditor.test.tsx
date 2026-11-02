import { beforeEach, expect, test, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import apiClient from '@/lib/api/client'
import { TranscriptEditor } from './TranscriptEditor'
import type { PodcastEpisode } from '@/lib/types/podcasts'

vi.mock('@/lib/api/client',()=>({default:{put:vi.fn(),post:vi.fn()}}))
const episode={id:'episode:original',name:'Original',job_status:'completed',transcript:{transcript:[{speaker:'Host',dialogue:'p of h equals a product.'},{speaker:'Guest',dialogue:'MLE finds likely parameters.'}]}} as unknown as PodcastEpisode
const mount=()=>render(<QueryClientProvider client={new QueryClient()}><TranscriptEditor episode={episode} onDirtyChange={vi.fn()} onGoToEpisode={vi.fn()} /></QueryClientProvider>)
beforeEach(()=>vi.clearAllMocks())

test('save and generate sends edited script once, preserves speaker mapping and uses returned revision',async()=>{
 vi.mocked(apiClient.put).mockImplementation(async(_url,data)=>({data:{revision:1,entries:(data as {entries:unknown}).entries}}))
 vi.mocked(apiClient.post).mockResolvedValue({data:{episode_id:'episode:revised',name:'Revised'}})
 mount();fireEvent.click(screen.getByText('transcriptEditor.edit'))
 const input=screen.getAllByRole('textbox',{name:'transcriptEditor.turn'})[0]
 fireEvent.change(input,{target:{value:'Combine each variable’s conditional probability to describe the joint distribution.'}})
 fireEvent.click(screen.getByText('transcriptEditor.saveAndGenerate'))
 await waitFor(()=>expect(screen.getByRole('status')).toBeTruthy())
 expect(apiClient.put).toHaveBeenCalledTimes(1)
 expect(apiClient.put).toHaveBeenCalledWith('/podcasts/episodes/episode:original/transcript',expect.objectContaining({expected_revision:0,entries:[{speaker:'Host',dialogue:'Combine each variable’s conditional probability to describe the joint distribution.'},{speaker:'Guest',dialogue:'MLE finds likely parameters.'}]}))
 expect(apiClient.post).toHaveBeenCalledWith('/podcasts/episodes/episode:original/regenerate-audio',{expected_revision:1,reuse_unchanged:true})
 // A stale episode prop must not reset a newly saved draft while the list refetches.
 expect((screen.getAllByRole('textbox',{name:'transcriptEditor.turn'})[0] as HTMLTextAreaElement).value).toContain('Combine each variable')
 expect(episode.transcript).toEqual({transcript:[{speaker:'Host',dialogue:'p of h equals a product.'},{speaker:'Guest',dialogue:'MLE finds likely parameters.'}]})
})

test('failed save retains edits and does not submit an audio job',async()=>{
 vi.mocked(apiClient.put).mockRejectedValue({response:{data:{detail:'Changed elsewhere. Reload before saving.'}}})
 mount();fireEvent.click(screen.getByText('transcriptEditor.edit'))
 fireEvent.change(screen.getAllByRole('textbox',{name:'transcriptEditor.turn'})[0],{target:{value:'Human-readable replacement.'}})
 fireEvent.click(screen.getByText('transcriptEditor.saveAndGenerate'))
 await waitFor(()=>expect(screen.getByRole('alert').textContent).toContain('Changed elsewhere'))
 expect(apiClient.post).not.toHaveBeenCalled()
 expect((screen.getAllByRole('textbox',{name:'transcriptEditor.turn'})[0] as HTMLTextAreaElement).value).toBe('Human-readable replacement.')
})

test('search finds turns and empty dialogue cannot be saved',()=>{
 mount();fireEvent.change(screen.getByRole('textbox',{name:'transcriptEditor.search'}),{target:{value:'MLE'}})
 expect(screen.queryByText('p of h equals a product.')).toBeNull()
 fireEvent.click(screen.getByText('transcriptEditor.edit'))
 fireEvent.change(screen.getByRole('textbox',{name:'transcriptEditor.turn'}),{target:{value:''}})
 expect(screen.getByText('transcriptEditor.empty')).toBeTruthy()
 expect(screen.getByText('transcriptEditor.save').hasAttribute('disabled')).toBe(true)
})
