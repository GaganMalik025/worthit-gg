"use client";
/** Full-bleed XMB-style wave. Fixed, unclipped, behind everything, always
 *  flowing from load. prefers-reduced-motion draws exactly one static frame. */
import { useEffect, useRef } from "react";

export function WaveBackdrop() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const prm = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let CW = 0, CH = 0, lean = 0, leanTarget = 0, raf = 0;
    const size = () => {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      CW = window.innerWidth; CH = window.innerHeight;
      cv.width = CW * dpr; cv.height = CH * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    const L = [
      { yc: .38, amp: 58, k1: .0038, k2: .0067, sp: .42, a: .15, sa: .30 },
      { yc: .55, amp: 44, k1: .0029, k2: .0053, sp: .62, a: .11, sa: .20 },
      { yc: .70, amp: 72, k1: .0022, k2: .0041, sp: .28, a: .08, sa: .12 },
    ];
    const draw = (t: number) => {
      ctx.clearRect(0, 0, CW, CH);
      lean += (leanTarget - lean) * 0.05;
      L.forEach((l, i) => {
        const amp = l.amp * (1 + .4 * lean);
        const ph = t * l.sp * (1 + .6 * lean) + i * 2.1;
        const yc = CH * l.yc + Math.sin(t * .22 + i) * 7;
        const pts: [number, number][] = [];
        for (let x = 0; x <= CW; x += 6)
          pts.push([x, yc + amp * Math.sin(x * l.k1 + ph) + amp * .5 * Math.sin(x * l.k2 - ph * .7)]);
        const g = ctx.createLinearGradient(0, yc - amp, 0, CH);
        g.addColorStop(0, `rgba(125,211,252,${l.a})`);
        g.addColorStop(1, "rgba(125,211,252,0)");
        ctx.fillStyle = g; ctx.beginPath(); ctx.moveTo(0, CH);
        pts.forEach(([x, y]) => ctx.lineTo(x, y));
        ctx.lineTo(CW, CH); ctx.closePath(); ctx.fill();
        ctx.strokeStyle = `rgba(125,211,252,${l.sa})`; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
        pts.forEach(([x, y]) => ctx.lineTo(x, y)); ctx.stroke();
      });
    };
    size();
    window.addEventListener("resize", size);
    const onScroll = () => { leanTarget = Math.min(1, Math.max(0, (window.scrollY - 40) / 460)); };
    if (prm) { draw(5); }
    else {
      addEventListener("scroll", onScroll, { passive: true });
      const frame = (ts: number) => { draw(ts / 1000); raf = requestAnimationFrame(frame); };
      raf = requestAnimationFrame(frame);
    }
    return () => {
      window.removeEventListener("resize", size);
      removeEventListener("scroll", onScroll);
      cancelAnimationFrame(raf);
    };
  }, []);
  return <div className="waves" aria-hidden="true"><canvas ref={ref} /></div>;
}
