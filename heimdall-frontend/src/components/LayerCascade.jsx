import React, { useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import styles from './LayerCascade.module.css'

// ── Status config ─────────────────────────────────────────
const STATUS_CONFIG = {
  RUNNING:  { color: 'var(--amber)',  label: 'RUNNING',  bg: 'var(--amber-dim)'  },
  PASS:     { color: 'var(--green)',  label: 'PASS',     bg: 'var(--green-dim)'  },
  BLOCK:    { color: 'var(--red)',    label: 'BLOCK',    bg: 'var(--red-dim)'    },
  FLAG:     { color: 'var(--amber)',  label: 'FLAG',     bg: 'var(--amber-dim)'  },
  SANITIZE: { color: 'var(--amber)',  label: 'SANITIZE', bg: 'var(--amber-dim)'  },
  SKIP:     { color: 'var(--text-muted)', label: 'SKIP', bg: 'transparent'      },
}

// Layer display names and ordering
const LAYER_META = {
  L0:   { name: 'Hot Cache',       gateway: 'G1' },
  L1:   { name: 'Pattern Engine',  gateway: 'G1' },
  L2:   { name: 'Sanitizer',       gateway: 'G1' },
  L3:   { name: 'ML Classifier',   gateway: 'G1' },
  L4:   { name: 'Intent Engine',   gateway: 'G1' },
  L5:   { name: 'Agentic Layer',   gateway: 'G1' },
  O1:   { name: 'Warm Cache',      gateway: 'G2' },
  O2:   { name: 'Leakage Check',   gateway: 'G2' },
  O3:   { name: 'Behavior Guard',  gateway: 'G2' },
  O4:   { name: 'Tool Validator',  gateway: 'G2' },
  O5:   { name: 'Final Verdict',   gateway: 'G2' },
}

// ── Framer variants ───────────────────────────────────────
const rowContainer = {
  hidden: {},
  show: { transition: { staggerChildren: 0.04 } },
}

const rowItem = {
  hidden: { opacity: 0, x: -16, height: 0 },
  show: {
    opacity: 1, x: 0, height: 'auto',
    transition: { type: 'spring', stiffness: 400, damping: 28, mass: 0.8 },
  },
  exit: {
    opacity: 0, height: 0,
    transition: { duration: 0.15 },
  },
}

// ── Progress bar ──────────────────────────────────────────
function ScoreBar({ score, color }) {
  const pct = Math.min(Math.max((score || 0) * 100, 0), 100)
  return (
    <div className={styles.barTrack}>
      <motion.div
        className={styles.barFill}
        style={{ background: color }}
        initial={{ width: 0 }}
        animate={{ width: `${pct}%` }}
        transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
      />
    </div>
  )
}

// ── Single layer row ──────────────────────────────────────
function LayerRow({ layer, status, score, latency_ms, flagged }) {
  const meta   = LAYER_META[layer] || { name: layer, gateway: '??' }
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.RUNNING

  return (
    <motion.div
      className={`${styles.row} ${status === 'BLOCK' ? styles.rowBlock : ''}`}
      variants={rowItem}
      style={{ '--row-color': config.color }}
    >
      {/* Connector dot */}
      <div className={styles.connDot} style={{ background: config.color }} />
      <div className={styles.connLine} />

      <div className={styles.rowContent}>
        {/* Left: layer ID + name */}
        <div className={styles.rowLeft}>
          <span className={styles.layerId}
            style={{ color: config.color, textShadow: `0 0 12px ${config.color}60` }}
          >
            {layer}
          </span>
          <span className={styles.layerName}>{meta.name}</span>
        </div>

        {/* Centre: score bar */}
        <div className={styles.rowCenter}>
          <ScoreBar score={score} color={config.color} />
          <span className={styles.scoreNum}>
            {status === 'RUNNING' ? '…' : (score || 0).toFixed(2)}
          </span>
        </div>

        {/* Right: status badge + latency */}
        <div className={styles.rowRight}>
          {latency_ms != null && latency_ms > 0 && (
            <span className={styles.latency}>{Math.round(latency_ms)}ms</span>
          )}
          <motion.span
            className={styles.badge}
            style={{ background: config.bg, color: config.color, borderColor: config.color }}
            initial={{ scale: 0.7, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ type: 'spring', stiffness: 500, damping: 22 }}
          >
            {config.label}
          </motion.span>
        </div>
      </div>
    </motion.div>
  )
}

// ── Verdict row ───────────────────────────────────────────
function VerdictRow({ event }) {
  const isBlock = event.verdict === 'BLOCK'
  const color = isBlock ? 'var(--red)' : 'var(--green)'
  return (
    <motion.div
      className={`${styles.verdictRow} ${isBlock ? styles.verdictBlock : styles.verdictPass}`}
      initial={{ opacity: 0, scaleX: 0.92, y: 8 }}
      animate={{ opacity: 1, scaleX: 1, y: 0 }}
      transition={{ type: 'spring', stiffness: 400, damping: 24 }}
    >
      <span className={styles.verdictLabel} style={{ color }}>
        {event.gateway} VERDICT
      </span>
      <span className={styles.verdictValue} style={{ color }}>
        {event.verdict}
      </span>
      {event.confidence != null && (
        <span className={styles.verdictConf}>
          {Math.round(event.confidence * 100)}% conf.
        </span>
      )}
    </motion.div>
  )
}

// ── Gateway section header ────────────────────────────────
function GatewayHeader({ label, color }) {
  return (
    <div className={styles.gwHeader}>
      <span style={{ color }}>{label}</span>
      <div className={styles.gwHeaderLine} style={{ background: color }} />
    </div>
  )
}

// ── Main component ────────────────────────────────────────
export default function LayerCascade({ events = [] }) {
  // Split into G1 and G2 events
  const { g1Layers, g2Layers, g1Verdict, g2Verdict } = useMemo(() => {
    const g1Layers = [], g2Layers = []
    let g1Verdict = null, g2Verdict = null

    for (const e of events) {
      if (e.event === 'layer') {
        const meta = LAYER_META[e.layer]
        if (!meta) continue
        if (meta.gateway === 'G1') g1Layers.push(e)
        else                       g2Layers.push(e)
      } else if (e.event === 'verdict') {
        if (e.gateway === 'G1') g1Verdict = e
        else                    g2Verdict = e
      }
    }

    return { g1Layers, g2Layers, g1Verdict, g2Verdict }
  }, [events])

  if (!events.length) return null

  return (
    <div className={styles.cascade}>
      {/* ── Gateway 1 ── */}
      {g1Layers.length > 0 && (
        <div className={styles.gateway}>
          <GatewayHeader label="GATEWAY 1" color="var(--amber)" />
          <motion.div
            className={styles.layerList}
            variants={rowContainer}
            initial="hidden"
            animate="show"
          >
            <AnimatePresence>
              {g1Layers.map((e, i) => (
                <LayerRow
                  key={`${e.layer}-${i}`}
                  layer={e.layer}
                  status={e.status}
                  score={e.score}
                  latency_ms={e.latency_ms}
                />
              ))}
            </AnimatePresence>
          </motion.div>
          {g1Verdict && <VerdictRow event={g1Verdict} />}
        </div>
      )}

      {/* ── Gateway 2 ── */}
      {g2Layers.length > 0 && (
        <div className={styles.gateway}>
          <GatewayHeader label="GATEWAY 2" color="var(--purple)" />
          <motion.div
            className={styles.layerList}
            variants={rowContainer}
            initial="hidden"
            animate="show"
          >
            <AnimatePresence>
              {g2Layers.map((e, i) => (
                <LayerRow
                  key={`${e.layer}-${i}`}
                  layer={e.layer}
                  status={e.status}
                  score={e.score}
                  latency_ms={e.latency_ms}
                />
              ))}
            </AnimatePresence>
          </motion.div>
          {g2Verdict && <VerdictRow event={g2Verdict} />}
        </div>
      )}
    </div>
  )
}
