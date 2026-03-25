import { useEffect, useState, useRef, useCallback } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

const WS_URL = import.meta.env.VITE_WS_URL ?? "ws://localhost:18789";

type ConnectionStatus = "connecting" | "connected" | "disconnected" | "error";

interface EventItem {
  id: string;
  time: string;
  data: unknown;
}

export function EventStream() {
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [events, setEvents] = useState<EventItem[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttempts = useRef(0);
  const idCounter = useRef(0);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    setStatus("connecting");
    setErrorMessage(null);
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus("connected");
      reconnectAttempts.current = 0;
    };

    ws.onmessage = (e) => {
      try {
        const data = typeof e.data === "string" ? JSON.parse(e.data) : e.data;
        setEvents((prev) => [
          ...prev.slice(-199),
          {
            id: `ev-${++idCounter.current}`,
            time: new Date().toISOString(),
            data,
          },
        ]);
      } catch {
        setEvents((prev) => [
          ...prev.slice(-199),
          {
            id: `ev-${++idCounter.current}`,
            time: new Date().toISOString(),
            data: { raw: String(e.data) },
          },
        ]);
      }
    };

    ws.onclose = () => {
      setStatus("disconnected");
      wsRef.current = null;
      const delay = Math.min(1000 * 2 ** reconnectAttempts.current, 30000);
      reconnectAttempts.current += 1;
      reconnectTimeoutRef.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      setStatus("error");
      setErrorMessage("WebSocket error");
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (wsRef.current) wsRef.current.close();
      wsRef.current = null;
    };
  }, [connect]);

  const handleReconnect = () => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    reconnectAttempts.current = 0;
    connect();
  };

  const statusBadgeVariant =
    status === "connected"
      ? "default"
      : status === "connecting"
        ? "secondary"
        : "destructive";

  return (
    <Card className="w-full rounded-2xl shadow-lg">
      <CardHeader className="space-y-2 pb-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle className="text-lg">OpenClaw events</CardTitle>
            <CardDescription className="mt-1">WebSocket: {WS_URL}</CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={statusBadgeVariant} className={cn(status === "connecting" && "animate-pulse")}>
              {status === "connected" && "Connected"}
              {status === "connecting" && "Connecting…"}
              {(status === "disconnected" || status === "error") && "Disconnected"}
            </Badge>
            {(status === "disconnected" || status === "error") && (
              <Button size="sm" variant="outline" onClick={handleReconnect}>
                Reconnect
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {errorMessage && (
          <Alert variant="destructive" className="mb-4">
            <AlertDescription>{errorMessage}</AlertDescription>
          </Alert>
        )}
        <ScrollArea className="min-h-[40vh] max-h-[50vh] w-full rounded-md border p-4">
          <div className="space-y-2">
            {events.length === 0 && status === "connecting" && (
              <p className="text-sm text-muted-foreground">Connecting…</p>
            )}
            {events.length === 0 && status === "connected" && (
              <p className="text-sm text-muted-foreground">Waiting for events…</p>
            )}
            {events.map((ev) => (
              <div
                key={ev.id}
                className="rounded-md border bg-muted/30 p-3 font-mono text-xs break-all"
              >
                <span className="text-muted-foreground">{ev.time}</span>
                <pre className="mt-1 whitespace-pre-wrap">
                  {typeof ev.data === "object"
                    ? JSON.stringify(ev.data, null, 2)
                    : String(ev.data)}
                </pre>
              </div>
            ))}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
