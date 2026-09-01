import React, { useMemo } from 'react'
import { motion } from 'framer-motion'
import { Dna, AlertTriangle, Flame, Shield } from 'lucide-react'
import styles from './AttackDNA.module.css'

// Attack type color map
const ATTACK_COLORS = {
  INSTRUCTION_OVERRIDE: 'var(--red)',
  PERSONA_INJECTION:    'var(--amber)',
  SYSTEM_EXTRACTION:    'var(--purple)',
  JAILBREAK:            'var(--red)',
  ENCODING_EVASION:     'var(--accent)',
  CONTEXT_MANIPULATION: 'var(--purple)',
  INDIRECT_INJECTION:   'var(--amber)',
  CLEAN:                'var(--green)',
}

const LAYER_NAMES = {
  L0: 'Hot Cache',  L1: 'Pattern',   L2: 'Sanitizer',
  L3: 'ML Class',   L4: 'Intent',    L5: 'Agentic',
  O1: 'Warm Cache', O2: 'Leakage',   O3: 'Behavior',
  O4: 'Tool Valid', O5: 'Final',
}

export default function AttackDNA({ events = [], verdict, attackType, cacheTier }) {
  const scores = useMemo(() => {
    const map = {}
    for (const e of events) {
      if (e.event === 'layer' && e.status !== 'RUNNING') {
        map[e.layer] = { score: e.score || 0, status: e.status }
      }
    }
    return map
  }, [events])

  const highScoreLayers = Object.entries(scores)
    .filter(([, v]) => v.score > 0.3)
    .sort(([, a], [, b]) => b.score - a.score)
    .slice(0, 4)

  const attackColor = ATTACK_COLORS[attackType] || 'var(--red)'
  const isBlock     = verdict === 'BLOCK'

  return (
    <motion.div
      className={styles.card}
      style={{ '--dna-color': attackColor }}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
    >
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <Dna size={11} color={attackColor} />
          <span className={styles.title}>ATTACK DNA</span>
        </div>
        <div className={styles.badges}>
          {attackType && attackType !== 'CLEAN' && (
            <span className={styles.typeBadge} style={{ background: `${attackColor}18`, color: attackColor, borderColor: attackColor }}>
              {attackType.replace(/_/g, ' ')}
            </span>
          )}
          {cacheTier && (
            <span className={styles.cacheBadge}>
              {cacheTier === 'HOT' ? <Flame size={9} /> : <Shield size={9} />}
              {cacheTier} CACHE
            </span>
          )}
        </div>
      </div>

      {/* Evidence bars */}
      {highScoreLayers.length > 0 && (
        <div className={styles.evidence}>
          <div className={styles.evidenceLabel}>HIGHEST SIGNAL LAYERS</div>
          {highScoreLayers.map(([layer, { score, status }], i) => {
            const barColor = status === 'BLOCK' ? 'var(--red)'
              : status === 'FLAG' ? 'var(--amber)'
              : 'var(--accent)'
            return (
              <div key={layer} className={styles.evidenceRow}>
                <span className={styles.layerId} style={{ color: barColor }}>{layer}</span>
                <span className={styles.layerName}>{LAYER_NAMES[layer] || layer}</span>
                <div className={styles.barTrack}>
                  <motion.div
                    className={styles.barFill}
                    style={{ background: barColor }}
                    initial={{ width: 0 }}
                    animate={{ width: `${score * 100}%` }}
                    transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1], delay: i * 0.08 }}
                  />
                </div>
                <span className={styles.scoreNum}>{score.toFixed(2)}</span>
              </div>
            )
          })}
        </div>
      )}

      {/* Verdict summary */}
      <div className={`${styles.summary} ${isBlock ? styles.summaryBlock : styles.summaryPass}`}>
        {isBlock ? <AlertTriangle size={11} color="var(--red)" /> : <Shield size={11} color="var(--green)" />}
        <span style={{ color: isBlock ? 'var(--red)' : 'var(--green)' }}>
          {isBlock
            ? 'Attack intercepted before reaching LLM'
            : 'Input passed all gates — response inspected by G2'}
        </span>
      </div>
    </motion.div>
  )
}
