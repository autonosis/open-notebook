import { fireEvent, render, screen } from '@testing-library/react'
import { useEffect, useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { NotebookWorkspace } from './NotebookWorkspace'

vi.mock('@/lib/hooks/use-translation', () => ({
  useTranslation: () => ({ t: (key: string) => ({ 'common.chat': 'Chat', 'navigation.sources': 'Sources', 'common.notes': 'Notes' })[key] ?? key }),
}))

describe('Notebook research workspace', () => {
  it('lands in chat and preserves the exact composer instance and draft across reference views', () => {
    const mounted = vi.fn()
    function Conversation() {
      const [draft, setDraft] = useState('')
      useEffect(() => { mounted() }, [])
      return <input aria-label="Message" value={draft} onChange={event => setDraft(event.target.value)} />
    }
    render(<NotebookWorkspace chat={<Conversation />} sources={<p>Evidence library</p>} notes={<p>Saved research</p>} sourceCount={2} noteCount={0} />)
    const composer = screen.getByRole('textbox', { name: 'Message' })
    expect(screen.getByRole('tab', { name: 'Chat' })).toHaveAttribute('aria-selected', 'true')
    fireEvent.change(composer, { target: { value: 'My unfinished research question' } })
    fireEvent.click(screen.getByRole('tab', { name: 'Sources 2' }))
    expect(screen.queryByRole('textbox', { name: 'Message' })).not.toBeInTheDocument()
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Evidence library')
    fireEvent.click(screen.getByRole('tab', { name: 'Notes 0' }))
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Saved research')
    fireEvent.click(screen.getByRole('tab', { name: 'Chat' }))
    expect(screen.getByRole('textbox', { name: 'Message' })).toBe(composer)
    expect(composer).toHaveValue('My unfinished research question')
    expect(mounted).toHaveBeenCalledTimes(1)
  })

  it('supports keyboard tab navigation and exposes only the active panel', () => {
    render(<NotebookWorkspace chat={<p>Conversation</p>} sources={<p>Library</p>} notes={<p>Notes</p>} sourceCount={1} noteCount={0} />)
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Chat' }), { key: 'ArrowRight' })
    expect(screen.getByRole('tab', { name: 'Sources 1' })).toHaveFocus()
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Library')
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Sources 1' }), { key: 'End' })
    expect(screen.getByRole('tab', { name: 'Notes 0' })).toHaveFocus()
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Notes 0' }), { key: 'Home' })
    expect(screen.getByRole('tab', { name: 'Chat' })).toHaveFocus()
  })
})
