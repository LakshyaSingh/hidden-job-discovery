/**
 * The two things every glass surface on the page depends on, mounted once in
 * the root layout:
 *
 *  1. The ambient bloom field. Glass only reads as glass when there is
 *     something behind it worth refracting; over a flat background a perfect
 *     material is invisible. Styling lives in globals.css (.ambient).
 *  2. The SVG displacement filters referenced by `backdrop-filter: url(...)`.
 *     Chromium only; Safari and Firefox skip the @supports block in
 *     globals.css and keep the plain frosted material.
 *
 * Server component. width/height 0 keeps the <svg> out of layout.
 */
export function GlassBackdrop() {
  return (
    <>
      <div className="ambient" aria-hidden="true">
        <span className="blob b1" />
        <span className="blob b2" />
        <span className="blob b3" />
        <span className="blob b4" />
      </div>

      <svg
        aria-hidden="true"
        width="0"
        height="0"
        style={{ position: "absolute", overflow: "hidden" }}
      >
        <defs>
          {/*
            Bend only, no chromatic dispersion. The displacement maps are
            neutral grey (rgb 128,128,128 = zero offset) across the middle 56%
            and saturated at the edges, so the backdrop is pushed hardest at
            the rim and not at all in the centre, which is what a real lens
            does. A uniform map just smears the whole panel.

            Two feDisplacementMap passes are chained because one pass can only
            read two channels: the first handles X, the second Y.
          */}
          <filter
            id="liquidGlass"
            x="-12%"
            y="-12%"
            width="124%"
            height="124%"
            colorInterpolationFilters="sRGB"
          >
            <feImage
              result="mx"
              preserveAspectRatio="none"
              x="0"
              y="0"
              width="100%"
              height="100%"
              href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='100' height='100' preserveAspectRatio='none'%3E%3Cdefs%3E%3ClinearGradient id='x' x1='0' y1='0' x2='1' y2='0'%3E%3Cstop offset='0' stop-color='rgb(255,128,128)'/%3E%3Cstop offset='0.22' stop-color='rgb(128,128,128)'/%3E%3Cstop offset='0.78' stop-color='rgb(128,128,128)'/%3E%3Cstop offset='1' stop-color='rgb(0,128,128)'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='100' height='100' fill='url(%23x)'/%3E%3C/svg%3E"
            />
            <feImage
              result="my"
              preserveAspectRatio="none"
              x="0"
              y="0"
              width="100%"
              height="100%"
              href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='100' height='100' preserveAspectRatio='none'%3E%3Cdefs%3E%3ClinearGradient id='y' x1='0' y1='0' x2='0' y2='1'%3E%3Cstop offset='0' stop-color='rgb(128,255,128)'/%3E%3Cstop offset='0.22' stop-color='rgb(128,128,128)'/%3E%3Cstop offset='0.78' stop-color='rgb(128,128,128)'/%3E%3Cstop offset='1' stop-color='rgb(128,0,128)'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='100' height='100' fill='url(%23y)'/%3E%3C/svg%3E"
            />
            <feDisplacementMap
              in="SourceGraphic"
              in2="mx"
              scale={15}
              xChannelSelector="R"
              yChannelSelector="B"
              result="dx"
            />
            <feDisplacementMap
              in="dx"
              in2="my"
              scale={15}
              xChannelSelector="R"
              yChannelSelector="G"
            />
          </filter>
        </defs>
      </svg>
    </>
  );
}
