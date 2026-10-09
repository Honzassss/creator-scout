import { useEffect } from 'react'
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
import { SourcePopoverProvider } from './components/primitives'

/* Shell (spec 5, 6, 14): info strip + 64 px top bar, then a supporting guide column (288 px, 304 px on wide
   screens, 48 px collapsed) and the dominant results column on the light-gray workspace (24 px outer
   padding). Below 768 px: a Guide / Results switch shows one column at a time. MOCK is a small label in
   the info strip and the data-status pill, never a colored frame around the window. */
export default function App() {
  const { t, blur, view, setView, state, chatCollapsed, setChatCollapsed } = useApp()
  const subject = state.mode === 'subject'
  useBoardSize()

  return (
    <div className={`h-full flex flex-col bg-[var(--bg)] text-[var(--text)] ${blur ? 'blur-on' : ''}`}>
      {/* inside the blur root: the source popover (fixed position) is blurred with the rest */}
      <SourcePopoverProvider>
        <Header />

        {/* narrow screens: guide or results (two toggle buttons, not a half-built tab pattern) */}
        <nav aria-label={t('tabs.label')} className="md:hidden px-3 sm:px-4 py-1.5 border-b border-[var(--line)] bg-[var(--surface)]">
          <div className="grid grid-cols-2 gap-1 p-1 rounded-[10px] border border-[var(--line)] bg-[var(--surface)]" role="group">
            {(['chat', 'board'] as const).map((k) => (
              <button
                key={k}
                type="button"
                aria-pressed={view === k}
                onClick={() => setView(k)}
                className={`h-11 min-w-11 px-4 rounded-[var(--r-control)] text-[15px] leading-[22px] font-semibold transition-colors duration-[var(--dur-1)] ${
                  view === k
                    ? 'bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] active:bg-[var(--accent-press)]'
                    : 'bg-[var(--surface)] text-[var(--text)] hover:bg-[var(--neutral-tint)] active:bg-[var(--line)]'
                }`}
              >
                {k === 'chat' ? t('tabs.chat') : t('tabs.board')}
              </button>
            ))}
          </div>
        </nav>

        {/* one main landmark for both columns, so it exists on phones whichever column is shown.
            No width transition on collapse: animating column width would reflow text (motion contract). */}
        <main
          className={`flex-1 min-h-0 md:grid ${
            chatCollapsed ? 'md:grid-cols-[48px_minmax(0,1fr)]' : 'md:grid-cols-[288px_minmax(0,1fr)] xl:grid-cols-[304px_minmax(0,1fr)]'
          }`}
        >
          <section
            aria-labelledby="chat-h"
            className={`min-h-0 h-full md:border-r border-[var(--line)] bg-[var(--surface)] ${view === 'chat' ? 'flex' : 'hidden'} md:flex flex-col`}
          >
            <Chat collapsed={chatCollapsed} onCollapse={setChatCollapsed} visible={view === 'chat'} />
          </section>
          <div
            id="board"
            className={`relative min-h-0 h-full overflow-y-auto overflow-x-clip scroll-thin scroll-pb-12 bg-[var(--bg)] ${view === 'board' ? 'block' : 'hidden'} md:block`}
          >
            <div className="px-3 sm:px-4 md:px-6 pt-3 sm:pt-4 md:pt-6 flex flex-col gap-4 md:gap-6 min-h-full">
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
              <div className="flex-1 min-h-8" />
              <LiveLog />
            </div>
          </div>
        </main>

        <CandidateDrawer />
        <GoalModal />
        <Toasts />
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
