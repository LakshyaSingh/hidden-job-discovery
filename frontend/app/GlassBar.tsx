"use client";

import { Glass, type GlassOptics } from "@samasante/liquid-glass";
import type { ReactNode } from "react";

/**
 * The nav bar's glass material.
 *
 * This replaces a hand-rolled `backdrop-filter: url(#svgFilter)` that used two
 * static gradient displacement maps. That approach can only frost: the maps
 * know nothing about the element's shape, so there is no rim lensing and no
 * dispersion, and it degrades to plain blur outside Chromium. The library
 * generates a real signed-distance-field lens map per shape instead.
 *
 * The optics below are anisotropic on purpose. `strength` is a fraction of the
 * element's box applied to both axes, and this bar is roughly 1100x48, so a
 * single value that bends the top and bottom edges sanely would drag the
 * backdrop sideways by a hundred pixels. `scaleX` / `scaleY` set each axis to
 * about the same displacement in real pixels.
 *
 * Frost stays low. High frost with a weak bend is exactly what reads as
 * "everything behind it is blurry" rather than as glass; the lens is what
 * should be carrying the effect.
 */
const NAV_OPTICS: Partial<GlassOptics> = {
  mapSize: 256,
  clipToShape: true,
  softEdge: true,

  // Lensing. depth is high so the bend reaches most of the way across the
  // bar. Confining it to a rim band leaves the middle optically dead, and on
  // a surface only 48px tall the middle is nearly all of it.
  depth: 0.8,
  curvature: 0.18,
  bend: 0.75,
  bendWidth: 0.16,
  dispersion: 0.55,
  splay: 0.08,
  // ~8px of displacement on each axis, given the bar's aspect ratio.
  scaleX: 0.008,
  scaleY: 0.15,
  strength: 0.09, // fallback for any axis the overrides do not cover

  // Material. Frost stays low: it blurs the source BEFORE refraction, so
  // every extra pixel of it is displacement you paid for and cannot see.
  // The tint lives in CSS (.topbar-glass) so contrast is tunable separately.
  frost: 3,
  saturate: 1.5,
  brightness: 0,

  // Edge lights, replacing the CSS ::before specular the bar used to carry.
  specular: 1,
  sheen: 0.5,
  sheenWidth: 2.5,
  sheenFalloff: 1.5,
  sheenAngle: 48,
  sheenDark: false,
  glow: 0.15,
  glowSpread: 0.9,
  glowFalloff: 0.8,
};

export function GlassBar({ children }: { children: ReactNode }) {
  return (
    <header className="topbar">
      {/* Glass sets display:inline-block inline, which collapses a full-bleed
          bar to its content width. Overriding it in the style prop is the only
          way to win against an inline style. */}
      <Glass
        className="topbar-glass"
        optics={NAV_OPTICS}
        style={{ display: "block", width: "100%" }}
      >
        <div className="topbar-inner">{children}</div>
      </Glass>
    </header>
  );
}
