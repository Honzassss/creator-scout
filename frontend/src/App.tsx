import { useEffect, type CSSProperties } from 'react'
import { useApp } from './store'
import { Header } from './components/Header'
import { Chat } from './components/Chat'
import { CriteriaPanel } from './components/CriteriaPanel'
import { Funnel } from './components/Funnel'
import { Compare } from './components/Compare'
import { DiffView } from './components/DiffView'
import { LiveLog } from './components/LiveLog'
import { CandidateDrawer } from './components/CandidateDrawer'
import { SubjectBoard } from './components/SubjectBoard'
import { GoalModal } from './components/GoalModal'
import { Toasts } from './components/DemoBar'
import { SourcePopoverProvider, useMockMode } from './components/primitives'

export default function App() {
  const { t, blur, view, setView, state, chatCollapsed, setChatCollapsed } = useApp()
  const subject = state.mode === 'subject'
  const mock = useMockMode()
  useBoardSize()

  return (
    <div className={`h-full flex flex-col ${blur ? 'blur-on' : ''}`} style={{ '--mock-h': mock ? '28px' : '0px' } as CSSProperties}>
      {/* inside the blur root: the source popover (fixed position) is blurred with the rest */}
      <SourcePopoverProvider>
        <Header />

        {/* narrow screens: guide or results (two toggle buttons, not a half-built tab pattern) */}
        <nav aria-label={t('tabs.label')} className="md:hidden flex justify-center px-4 py-2 border-b border-rule bg-paper-2/70">
          <div className="seg" role="group">
            {(['chat', 'board'] as const).map((k) => (
              <button key={k} type="button" aria-pressed={view === k} onClick={() => setView(k)}>
                {k === 'chat' ? t('tabs.chat') : t('tabs.board')}
              </button>
            ))}
          </div>
        </nav>

        {/* one main landmark for both columns, so it exists on phones whichever column is shown */}
        <main
          className={`flex-1 min-h-0 md:grid ${chatCollapsed ? 'md:grid-cols-[48px_minmax(0,1fr)]' : 'md:grid-cols-[360px_minmax(0,1fr)]'}`}
          style={{ transition: 'grid-template-columns var(--dur-base) var(--ease)' }}
        >
          <section
            aria-labelledby="chat-h"
            className={`min-h-0 h-full border-r border-rule bg-paper-2/40 ${view === 'chat' ? 'flex' : 'hidden'} md:flex flex-col`}
          >
            <Chat collapsed={chatCollapsed} onCollapse={setChatCollapsed} visible={view === 'chat'} />
          </section>
          <div
            id="board"
            className={`relative min-h-0 h-full overflow-y-auto overflow-x-clip scroll-thin scroll-pb-12 ${view === 'board' ? 'block' : 'hidden'} md:block`}
          >
            <div className="px-4 pt-4 flex flex-col gap-4 min-h-full">
              <CriteriaPanel />
              {subject ? (
                <SubjectBoard />
              ) : (
                <>
                  <DiffView />
                  <Funnel />
                  <Compare />
                </>
              )}
              <div className="flex-1 min-h-12" />
              <LiveLog />
            </div>
          </div>
        </main>

        <CandidateDrawer />
        <GoalModal />
        <Toasts />
        {/* MOCK is a mode: a 3 px frame around the window, above the dossier and every dialog */}
        {mock && <div className="mock-frame" aria-hidden data-keep-active="true" />}
      </SourcePopoverProvider>
    </div>
  )
}

/** --board-h on #board (the results scroller's height), so sticky panels inside it can end above the run
 *  log (LiveLog sets --log-h) whatever banners sit above the board. */
function useBoardSize() {
  useEffect(() => {
    const board = document.getElementById('board')
    if (!board || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => board.style.setProperty('--board-h', `${board.clientHeight}px`))
    ro.observe(board)
    return () => ro.disconnect()
  }, [])
}
