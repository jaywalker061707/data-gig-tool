import React, { useRef } from 'react'
import { useStore } from './store'
import UploadSidebar from './components/UploadSidebar'
import ChatPanel     from './components/ChatPanel'
import MapTab        from './tabs/MapTab'
import BatchTab      from './tabs/BatchTab'
import ReconTab      from './tabs/ReconTab'
import StatusTab     from './tabs/StatusTab'
import CountTab      from './tabs/CountTab'
import QualityTab    from './tabs/QualityTab'
import ReviewTab     from './tabs/ReviewTab'

const TABS = [
  { id: 'map',     label: 'Site Map',       icon: '🗺️' },
  { id: 'batch',   label: 'Batch Summary',  icon: '📋' },
  { id: 'recon',   label: 'Reconciliation', icon: '⚖️' },
  { id: 'status',  label: 'Status Overview',icon: '📊' },
  { id: 'count',   label: 'Count Comparison',icon:'📈' },
  { id: 'quality', label: 'Data Quality',   icon: '🔍' },
  { id: 'review',  label: 'Manual Review',  icon: '🔬' },
]

export default function App() {
  const { activeTab, setActiveTab, results, activeSite } = useStore()
  const hasResults = !!results

  return (
    <div className="shell">
      <UploadSidebar />

      <div className="main">
        {/* Top bar showing active site */}
        <div className="main-header">
          <span className="main-title">Foreseer vs LinX Asset Reconciliation</span>
          {activeSite && <span className="site-chip">{activeSite}</span>}
          {hasResults && (
            <span style={{ fontSize: 11, color: 'var(--gray-400)', marginLeft: 'auto' }}>
              {Object.keys(results).length} site{Object.keys(results).length !== 1 ? 's' : ''} loaded
            </span>
          )}
        </div>

        {/* Tab nav */}
        <div style={{
          background: 'white', borderBottom: '1px solid var(--gray-200)',
          display: 'flex', padding: '0 24px', gap: 2, flexShrink: 0,
        }}>
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              disabled={t.id !== 'map' && !hasResults}
              style={{
                padding: '10px 16px',
                border: 'none', background: 'none', cursor: hasResults || t.id === 'map' ? 'pointer' : 'not-allowed',
                fontSize: 12, fontWeight: activeTab === t.id ? 700 : 500,
                color: activeTab === t.id ? 'var(--comcast-blue)' : hasResults ? 'var(--gray-500)' : 'var(--gray-300)',
                borderBottom: `2px solid ${activeTab === t.id ? 'var(--comcast-blue)' : 'transparent'}`,
                marginBottom: -2, display: 'flex', alignItems: 'center', gap: 6,
                transition: 'color .12s',
                whiteSpace: 'nowrap',
              }}
            >
              <span style={{ fontSize: 13 }}>{t.icon}</span>
              {t.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="main-content">
          {activeTab === 'map'     && <MapTab />}
          {activeTab === 'batch'   && <BatchTab />}
          {activeTab === 'recon'   && <ReconTab />}
          {activeTab === 'status'  && <StatusTab />}
          {activeTab === 'count'   && <CountTab />}
          {activeTab === 'quality' && <QualityTab />}
          {activeTab === 'review'  && <ReviewTab />}
        </div>
      </div>

      <ChatPanel />
    </div>
  )
}
