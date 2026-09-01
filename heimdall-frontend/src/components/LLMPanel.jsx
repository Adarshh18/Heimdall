import React from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Bot, Clock, Hash } from 'lucide-react'
import styles from './LLMPanel.module.css'

const PROVIDERS = [
  { key: 'gemini', label: 'Gemini',  color: 'var(--accent)',  dot: '#4285F4' },
  { key: 'groq',   label: 'Groq',    color: 'var(--green)',   dot: '#F55036' },
  { key: 'mistral',label: 'Mistral', color: 'var(--purple)',  dot: '#FF7000' },
]

function SkeletonCard({ delay }) {
  return (
    <motion.div
      className={styles.panel}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.3 }}
    >
      <div className={styles.panelHeader}>
        <div className={`${styles.skeleton} ${styles.skH}`} />
      </div>
      <div className={styles.panelBody}>
        <div className={`${styles.skeleton} ${styles.skL}`} />
        <div className={`${styles.skeleton} ${styles.skL} ${styles.skMed}`} />
        <div className={`${styles.skeleton} ${styles.skL} ${styles.skShort}`} />
      </div>
    </motion.div>
  )
}

function ProviderCard({ provider, response, delay }) {
  const isError = response?.error
  const text    = response?.text || ''
  const tokens  = response?.tokens
  const latency = response?.latency_ms

  return (
    <motion.div
      className={`${styles.panel} ${isError ? styles.panelError : ''}`}
      style={{ '--p-color': provider.color }}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
    >
      {/* Header */}
      <div className={styles.panelHeader}>
        <div className={styles.providerDot} style={{ background: provider.dot }} />
        <span className={styles.providerName} style={{ color: provider.color }}>
          {provider.label}
        </span>
        <div className={styles.panelMeta}>
          {latency != null && (
            <span className={styles.metaTag}>
              <Clock size={9} /> {Math.round(latency)}ms
            </span>
          )}
          {tokens != null && (
            <span className={styles.metaTag}>
              <Hash size={9} /> {tokens}
            </span>
          )}
        </div>
      </div>

      {/* Body */}
      <div className={styles.panelBody}>
        {isError ? (
          <span className={styles.errorText}>{response.error}</span>
        ) : (
          <p className={styles.responseText}>{text}</p>
        )}
      </div>
    </motion.div>
  )
}

export default function LLMPanel({ llmEvents = [], llmResponses = {}, loading }) {
  // Determine active providers from events or responses
  const activeKeys = Object.keys(llmResponses).length > 0
    ? Object.keys(llmResponses)
    : PROVIDERS.map(p => p.key)

  return (
    <div className={styles.wrap}>
      <div className={styles.header}>
        <Bot size={11} color="var(--text-dim)" />
        <span className={styles.headerLabel}>LLM RESPONSES</span>
      </div>
      <div className={styles.grid}>
        {PROVIDERS.map((p, i) => {
          if (!activeKeys.includes(p.key) && !loading) return null
          if (loading) return <SkeletonCard key={p.key} delay={i * 0.08} />
          return (
            <ProviderCard
              key={p.key}
              provider={p}
              response={llmResponses[p.key]}
              delay={i * 0.08}
            />
          )
        })}
      </div>
    </div>
  )
}
