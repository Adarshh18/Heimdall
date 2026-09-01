import React, { useRef, useEffect, useCallback } from 'react'
import * as THREE from 'three'

// Attack type → arc color
const TYPE_COLORS = {
  JAILBREAK:            0xff4d6d,
  INSTRUCTION_OVERRIDE: 0xff4d6d,
  SYSTEM_EXTRACTION:    0xfbbf24,
  ENCODING_EVASION:     0x00f5ff,
  PERSONA_INJECTION:    0xa78bfa,
  CONTEXT_MANIPULATION: 0xa78bfa,
  CLEAN:                0x22d3a5,
  DEFAULT:              0x00f5ff,
}

function latLngToVec3(lat, lng, radius) {
  const phi   = (90 - lat)  * (Math.PI / 180)
  const theta = (lng + 180) * (Math.PI / 180)
  return new THREE.Vector3(
    -radius * Math.sin(phi) * Math.cos(theta),
     radius * Math.cos(phi),
     radius * Math.sin(phi) * Math.sin(theta),
  )
}

function makeArc(src, dst, color, segments = 48) {
  const mid = new THREE.Vector3().addVectors(src, dst).multiplyScalar(0.5)
  mid.normalize().multiplyScalar(src.length() * 1.35)

  const curve = new THREE.QuadraticBezierCurve3(src, mid, dst)
  const points = curve.getPoints(segments)

  const geo = new THREE.BufferGeometry().setFromPoints(points)
  const mat = new THREE.LineBasicMaterial({
    color,
    transparent: true,
    opacity: 0.8,
    linewidth: 1,
  })
  const line = new THREE.Line(geo, mat)
  line._createdAt = Date.now()
  return line
}

export default function ThreatGlobe({ attacks = [] }) {
  const mountRef  = useRef(null)
  const stateRef  = useRef({})

  const init = useCallback(() => {
    const el = mountRef.current
    if (!el) return

    const W = el.clientWidth  || 220
    const H = el.clientHeight || 200

    // Scene
    const scene    = new THREE.Scene()
    const camera   = new THREE.PerspectiveCamera(45, W / H, 0.1, 1000)
    camera.position.set(0, 0, 3)

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setSize(W, H)
    renderer.setClearColor(0x000000, 0)
    el.appendChild(renderer.domElement)

    // Globe sphere
    const globeGeo = new THREE.SphereGeometry(1, 48, 48)
    const globeMat = new THREE.MeshPhongMaterial({
      color: 0x0d1117,
      emissive: 0x001a1a,
      specular: 0x00f5ff,
      shininess: 15,
      transparent: true,
      opacity: 0.9,
    })
    const globe = new THREE.Mesh(globeGeo, globeMat)
    scene.add(globe)

    // Wireframe overlay
    const wireGeo = new THREE.SphereGeometry(1.002, 24, 24)
    const wireMat = new THREE.MeshBasicMaterial({
      color: 0x00f5ff,
      wireframe: true,
      transparent: true,
      opacity: 0.06,
    })
    scene.add(new THREE.Mesh(wireGeo, wireMat))

    // Atmosphere glow
    const atmosGeo = new THREE.SphereGeometry(1.12, 32, 32)
    const atmosMat = new THREE.MeshBasicMaterial({
      color: 0x00f5ff,
      transparent: true,
      opacity: 0.04,
      side: THREE.BackSide,
    })
    scene.add(new THREE.Mesh(atmosGeo, atmosMat))

    // Particles
    const particleCount = 200
    const pPositions    = new Float32Array(particleCount * 3)
    for (let i = 0; i < particleCount; i++) {
      const theta = Math.random() * Math.PI * 2
      const phi   = Math.acos(2 * Math.random() - 1)
      const r     = 1.08 + Math.random() * 0.12
      pPositions[i * 3]     = r * Math.sin(phi) * Math.cos(theta)
      pPositions[i * 3 + 1] = r * Math.cos(phi)
      pPositions[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta)
    }
    const pGeo = new THREE.BufferGeometry()
    pGeo.setAttribute('position', new THREE.BufferAttribute(pPositions, 3))
    const pMat = new THREE.PointsMaterial({
      color: 0x00f5ff,
      size: 0.016,
      transparent: true,
      opacity: 0.5,
    })
    scene.add(new THREE.Points(pGeo, pMat))

    // Lighting
    scene.add(new THREE.AmbientLight(0x112244, 1.5))
    const dirLight = new THREE.DirectionalLight(0x00f5ff, 0.8)
    dirLight.position.set(5, 3, 5)
    scene.add(dirLight)

    // Pivot for rotation
    const pivot = new THREE.Group()
    pivot.add(globe)
    scene.add(pivot)

    // Arc group
    const arcGroup = new THREE.Group()
    scene.add(arcGroup)

    // Store refs
    stateRef.current = { scene, camera, renderer, pivot, arcGroup, animId: null }

    // Resize observer
    const ro = new ResizeObserver(() => {
      const W2 = el.clientWidth
      const H2 = el.clientHeight
      renderer.setSize(W2, H2)
      camera.aspect = W2 / H2
      camera.updateProjectionMatrix()
    })
    ro.observe(el)
    stateRef.current.ro = ro

    // Animation loop
    const animate = () => {
      stateRef.current.animId = requestAnimationFrame(animate)
      pivot.rotation.y += 0.003

      // Fade out old arcs
      const now = Date.now()
      arcGroup.children.slice().forEach(arc => {
        const age = (now - arc._createdAt) / 3000
        if (age > 1) {
          arcGroup.remove(arc)
          arc.geometry.dispose()
          arc.material.dispose()
        } else {
          arc.material.opacity = Math.max(0, 0.8 * (1 - age))
        }
      })

      renderer.render(scene, camera)
    }
    animate()
  }, [])

  const addArc = useCallback((attackType) => {
    const { arcGroup } = stateRef.current
    if (!arcGroup) return

    const color = TYPE_COLORS[attackType] || TYPE_COLORS.DEFAULT
    const src = latLngToVec3(
      (Math.random() - 0.5) * 140,
      (Math.random() - 0.5) * 340,
      1.01,
    )
    const dst = latLngToVec3(
      (Math.random() - 0.5) * 140,
      (Math.random() - 0.5) * 340,
      1.01,
    )
    arcGroup.add(makeArc(src, dst, color))
  }, [])

  // Init on mount
  useEffect(() => {
    init()
    return () => {
      const { renderer, animId, ro } = stateRef.current
      if (animId)   cancelAnimationFrame(animId)
      if (ro)       ro.disconnect()
      if (renderer) {
        renderer.dispose()
        mountRef.current?.removeChild(renderer.domElement)
      }
    }
  }, [init])

  // New attack → draw arc
  const prevLen = useRef(0)
  useEffect(() => {
    if (attacks.length > prevLen.current) {
      const latest = attacks[attacks.length - 1]
      addArc(latest?.attackType || 'DEFAULT')
    }
    prevLen.current = attacks.length
  }, [attacks, addArc])

  return (
    <div
      ref={mountRef}
      style={{ width: '100%', height: '100%', minHeight: 200 }}
      aria-label="3D threat globe"
    />
  )
}
