'use client'

import { useEffect, useState } from 'react'
import { usePathname } from 'next/navigation'
import { Menu } from 'lucide-react'
import { AppSidebar } from './AppSidebar'
import { SetupBanner } from './SetupBanner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from '@/components/ui/dialog'

interface AppShellProps { children: React.ReactNode }

export function AppShell({ children }: AppShellProps) {
  const [navigationOpen, setNavigationOpen] = useState(false)
  const pathname = usePathname()
  useEffect(() => { setNavigationOpen(false) }, [pathname])
  return (
    <div className="flex h-dvh min-w-0 overflow-hidden">
      <div className="hidden h-full shrink-0 lg:block"><AppSidebar /></div>
      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <div className="flex h-12 shrink-0 items-center gap-3 border-b px-3 lg:hidden">
          <Dialog open={navigationOpen} onOpenChange={setNavigationOpen}>
            <DialogTrigger asChild><Button variant="ghost" size="icon" aria-label="Open navigation"><Menu className="size-5" /></Button></DialogTrigger>
            <DialogContent className="!left-0 !top-0 !h-dvh !w-72 !max-w-[calc(100vw-2rem)] !translate-x-0 !translate-y-0 !rounded-none !border-0 !p-0" aria-describedby={undefined}>
              <DialogTitle className="sr-only">Navigation</DialogTitle>
              <div className="h-full min-h-0 overflow-y-auto" onClick={event => { if ((event.target as HTMLElement).closest('a')) setNavigationOpen(false) }}><AppSidebar /></div>
            </DialogContent>
          </Dialog>
          <span className="text-sm font-semibold">Open Notebook</span>
        </div>
        <SetupBanner />
        {children}
      </main>
    </div>
  )
}
