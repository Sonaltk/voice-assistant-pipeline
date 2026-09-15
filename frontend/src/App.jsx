import { useVoiceSession } from "./hooks/useVoiceSession";
import "./App.css";

function App() {
  const { connected, micReady, recording, log, connect, startTalking, stopTalking } =
    useVoiceSession();

  const handleTouchStart = (e) => {
    e.preventDefault(); // stops the synthetic mousedown that would double-trigger
    startTalking();
  };
  const handleTouchEnd = (e) => {
    e.preventDefault();
    stopTalking();
  };

  return (
    <div className="app">
      <h1>Voice pipeline</h1>
      <p>Hold the button to talk. Audio streams to the server as you speak.</p>

      <button onClick={connect} disabled={connected}>
        Connect
      </button>
      <button
        className={recording ? "talk recording" : "talk"}
        disabled={!micReady}
        onMouseDown={startTalking}
        onMouseUp={stopTalking}
        onMouseLeave={() => recording && stopTalking()}
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
      >
        Hold to talk
      </button>

      <pre className="log">{log.join("\n")}</pre>
    </div>
  );
}

export default App;