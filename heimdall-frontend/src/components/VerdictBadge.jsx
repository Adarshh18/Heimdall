import React from 'react'
import { motion } from 'framer-motion'
import { ShieldCheck, ShieldX, ShieldAlert, AlertTriangle } from 'lucide-react'
import styles from './VerdictBadge.module.css'

const CONFIG = {
  PASS:     { icon: ShieldCheck,  color: 'var(--green)',  bg: 'var(--green-dim)',  glow: 'var(--green-glow)',  label: 'PASS'     },
  BLOCK:    { icon: ShieldX,      color: 'var(--red)',    bg: 'var(--red-dim)',    glow: 'var(--red-glow)',    label: 'BLOCKED'  },
  SANITIZE: { icon: ShieldAlert,  color: 'var(--amber)',  bg: 'var(--amber-dim)',  glow: 'var(--amber-glow)',  label: 'SANITIZED'},
  FLAG:     { icon: AlertTriangle,color: 'var(--amber)',  bg: 'var(--amber-dim)',  glow: 'var(--amber-glow)',  label: 'FLAGGED'  },
}

export default function VerdictBadge({ verdict = 'PASS', confidence }) {
  const cfg = CONFIG[verdict] || CONFIG.PASS
  const Icon = cfg.icon

  return (
    <motion.div
      className={styles.badge}
      style={{
        background: cfg.bg,
        borderColor: cfg.color,
        boxShadow: `0 0 12px ${cfg.glow}`,
      }}
      initial={{ scale: 0, opacity: 0, rotate: -8 }}
      animate={{ scale: 1, opacity: 1, rotate: 0 }}
      transition={{ type: 'spring', stiffness: 500, damping: 22, delay: 0.05 }}
    >
      <Icon size={11} color={cfg.color} />
      <span className={styles.label} style={{ color: cfg.color }}>
        {cfg.label}
      </span>
      {confidence != null && (
        <span className={styles.conf} style={{ color: cfg.color, opacity: 0.6 }}>
          {Math.round(confidence * 100)}%
        </span>
      )}
    </motion.div>
  )
}
