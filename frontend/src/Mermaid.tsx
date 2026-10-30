import { useEffect, useRef, useState } from "react";

let counter = 0;

/** Renders Mermaid text. The library is loaded on demand (large). */
export default function Mermaid({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const m = (await import("mermaid")).default;
        const dark = document.documentElement.dataset.theme === "dark";
        m.initialize({ startOnLoad: false, theme: dark ? "dark" : "default", securityLevel: "strict" });
        const { svg } = await m.render(`mmd${counter++}`, code);
        if (live && ref.current) { ref.current.innerHTML = svg; setErr(""); }
      } catch (e) { if (live) setErr(String(e)); }
    })();
    return () => { live = false; };
  }, [code]);

  return err ? <pre className="out">{err}{"\n\n"}{code}</pre> : <div ref={ref} className="mermaid-box" />;
}
