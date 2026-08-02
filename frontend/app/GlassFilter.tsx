/**
 * The SVG displacement filter the nav bar references through
 * `backdrop-filter: url(#liquidGlass)`.
 *
 * The two maps are neutral grey (rgb 128,128,128 = zero offset) across the
 * middle band and saturated at the edges, so the backdrop is displaced only
 * near the rim and not at all through the centre. That is what a real lens
 * does; a uniform map just smears the whole surface. Two passes are chained
 * because one feDisplacementMap can only read two channels: X, then Y.
 *
 * Bend only, no chromatic dispersion. Splitting the channels along the bar's
 * long straight bottom edge would separate them into a visible coloured
 * streak, which reads as a rendering bug.
 *
 * Chromium only. Safari and Firefox skip the @supports block in globals.css
 * and keep the plain blurred material, which is a perfectly good outcome.
 * Server component; width/height 0 keeps it out of layout.
 */
export function GlassFilter() {
  return (
    <svg
      aria-hidden="true"
      width="0"
      height="0"
      style={{ position: "absolute", overflow: "hidden" }}
    >
      <defs>
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
            href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='100' height='100' preserveAspectRatio='none'%3E%3Cdefs%3E%3ClinearGradient id='x' x1='0' y1='0' x2='1' y2='0'%3E%3Cstop offset='0' stop-color='rgb(255,128,128)'/%3E%3Cstop offset='0.26' stop-color='rgb(128,128,128)'/%3E%3Cstop offset='0.74' stop-color='rgb(128,128,128)'/%3E%3Cstop offset='1' stop-color='rgb(0,128,128)'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='100' height='100' fill='url(%23x)'/%3E%3C/svg%3E"
          />
          <feImage
            result="my"
            preserveAspectRatio="none"
            x="0"
            y="0"
            width="100%"
            height="100%"
            href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='100' height='100' preserveAspectRatio='none'%3E%3Cdefs%3E%3ClinearGradient id='y' x1='0' y1='0' x2='0' y2='1'%3E%3Cstop offset='0' stop-color='rgb(128,255,128)'/%3E%3Cstop offset='0.26' stop-color='rgb(128,128,128)'/%3E%3Cstop offset='0.74' stop-color='rgb(128,128,128)'/%3E%3Cstop offset='1' stop-color='rgb(128,0,128)'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='100' height='100' fill='url(%23y)'/%3E%3C/svg%3E"
          />
          {/* Gentler than the stock scale of 15: the bar is only 48px tall,
              so the bend zone is about 10px at each edge and a large offset
              would tear rather than refract. */}
          <feDisplacementMap
            in="SourceGraphic"
            in2="mx"
            scale={11}
            xChannelSelector="R"
            yChannelSelector="B"
            result="dx"
          />
          <feDisplacementMap
            in="dx"
            in2="my"
            scale={11}
            xChannelSelector="R"
            yChannelSelector="G"
          />
        </filter>
      </defs>
    </svg>
  );
}
