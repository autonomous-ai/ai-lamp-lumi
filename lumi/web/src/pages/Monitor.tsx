import { useEffect, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/ThemeToggle";

const LELAMP_BASE = "/hw";
const STREAM_URL = `${LELAMP_BASE}/camera/stream`;
const SNAPSHOT_URL = `${LELAMP_BASE}/camera/snapshot`;
const HEALTH_URL = `${LELAMP_BASE}/health`;

interface HealthStatus {
  status: string;
  servo: boolean;
  led: boolean;
  camera: boolean;
  audio: boolean;
  sensing: boolean;
}

export default function Monitor() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [streaming, setStreaming] = useState(true);
  const imgRef = useRef<HTMLImageElement>(null);

  // Fetch health status
  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const res = await fetch(HEALTH_URL);
        if (res.ok) setHealth(await res.json());
      } catch {
        setHealth(null);
      }
    };
    fetchHealth();
    const interval = setInterval(fetchHealth, 5000);
    return () => clearInterval(interval);
  }, []);

  // Poll sensing events from Lumi Go (reuse the SSE/lifecycle concept)
  // For now, show camera + health. Events can be added when we have an SSE endpoint.

  const toggleStream = () => {
    setStreaming((prev) => !prev);
    if (imgRef.current && streaming) {
      imgRef.current.src = "";
    }
  };

  const takeSnapshot = async () => {
    try {
      const res = await fetch(SNAPSHOT_URL);
      if (!res.ok) return;
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `lumi-snapshot-${Date.now()}.jpg`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // ignore
    }
  };

  return (
    <div className="min-h-screen flex flex-col bg-muted/30">
      <main className="flex-1 flex flex-col overflow-auto">
        <div className="max-w-2xl mx-auto w-full px-4 py-6">
          <div className="flex items-center justify-between mb-6">
            <h1 className="text-2xl font-bold">Lumi Monitor</h1>
            <ThemeToggle />
          </div>

          {/* Camera Feed */}
          <Card className="w-full rounded-2xl shadow-lg mb-4">
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-lg">Camera</CardTitle>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" onClick={takeSnapshot}>
                    Snapshot
                  </Button>
                  <Button
                    variant={streaming ? "destructive" : "default"}
                    size="sm"
                    onClick={toggleStream}
                  >
                    {streaming ? "Stop" : "Start"}
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <div className="relative aspect-video bg-black rounded-lg overflow-hidden">
                {streaming ? (
                  <img
                    ref={imgRef}
                    src={STREAM_URL}
                    alt="Camera stream"
                    className="w-full h-full object-contain"
                    onError={() => setStreaming(false)}
                  />
                ) : (
                  <div className="flex items-center justify-center h-full text-muted-foreground">
                    Stream paused
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Hardware Status */}
          <Card className="w-full rounded-2xl shadow-lg">
            <CardHeader className="pb-2">
              <CardTitle className="text-lg">Hardware Status</CardTitle>
            </CardHeader>
            <CardContent>
              {health ? (
                <div className="flex flex-wrap gap-2">
                  <StatusBadge label="Servo" ok={health.servo} />
                  <StatusBadge label="LED" ok={health.led} />
                  <StatusBadge label="Camera" ok={health.camera} />
                  <StatusBadge label="Audio" ok={health.audio} />
                  <StatusBadge label="Sensing" ok={health.sensing} />
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  LeLamp not reachable
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  );
}

function StatusBadge({ label, ok }: { label: string; ok: boolean }) {
  return (
    <Badge variant={ok ? "default" : "secondary"} className="text-xs">
      <span
        className={`inline-block w-2 h-2 rounded-full mr-1.5 ${
          ok ? "bg-green-400" : "bg-red-400"
        }`}
      />
      {label}
    </Badge>
  );
}
