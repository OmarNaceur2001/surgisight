import { useEffect, useState } from "react";

export default function App() {
  const [status, setStatus] = useState("loading...");

  useEffect(() => {
    fetch("http://127.0.0.1:8000/health")
      .then((r) => r.json())
      .then((d) => setStatus(d.status))
      .catch(() => setStatus("backend unreachable"));
  }, []);

  return (
    <>
      <div style={{ background: "#7a1f1f", color: "#fff", padding: 8 }}>
        Research prototype — not for clinical use
      </div>
      <h1>SurgiSight</h1>
      <p>Backend status: {status}</p>
    </>
  );
}