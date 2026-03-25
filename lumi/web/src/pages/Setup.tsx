import { useEffect, useMemo, useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Eye, EyeOff } from "lucide-react";
import { getNetworks, setupDevice } from "@/lib/api";
import type { ChannelType, NetworkItem } from "@/types";

export default function Setup() {
  const [searchParams] = useSearchParams();

  const channelParam = searchParams.get("channel");
  console.log(channelParam)
  const channel: ChannelType =
    channelParam === "slack" || channelParam === "discord" ? (channelParam as ChannelType) : "telegram";

  console.log(channelParam, "=", channel)

  // Prefill MQTT state from URL params once (so optional section shows them when expanded)
  useEffect(() => {
    setMqttEndpoint((prev) => prev || (searchParams.get("mqtt_endpoint") ?? ""));
    setMqttPort((prev) => prev || (searchParams.get("mqtt_port") ?? ""));
    setMqttUsername((prev) => prev || (searchParams.get("mqtt_username") ?? ""));
    setMqttPassword((prev) => prev || (searchParams.get("mqtt_password") ?? ""));
    setFaChannel((prev) => prev || (searchParams.get("fa_channel") ?? ""));
    setFdChannel((prev) => prev || (searchParams.get("fd_channel") ?? ""));
  }, [searchParams]);

  const urlParams = useMemo(
    () => ({
      // Telegram
      teleToken: searchParams.get("tele_token") ?? "",
      teleUserId: searchParams.get("tele_user_id") ?? "",
      // Slack
      slackBotToken: searchParams.get("slack_bot_token") ?? "",
      slackAppToken: searchParams.get("slack_app_token") ?? "",
      slackUserId: searchParams.get("slack_user_id") ?? "",
      // Discord
      discordBotToken: searchParams.get("discord_bot_token") ?? "",
      discordGuildId: searchParams.get("discord_guild_id") ?? "",
      discordUserId: searchParams.get("discord_user_id") ?? "",
      // Common
      llmApiKey: searchParams.get("llm_api_key") ?? "",
      llmUrl: searchParams.get("llm_url") ?? "",
      llmModel: searchParams.get("llm_model") ?? "",
      deviceId: searchParams.get("device_id") ?? "",
      // MQTT (optional)
      mqttEndpoint: searchParams.get("mqtt_endpoint") ?? "",
      mqttPort: searchParams.get("mqtt_port") ?? "",
      mqttUsername: searchParams.get("mqtt_username") ?? "",
      mqttPassword: searchParams.get("mqtt_password") ?? "",
      faChannel: searchParams.get("fa_channel") ?? "",
      fdChannel: searchParams.get("fd_channel") ?? "",
    }),
    [searchParams],
  );

  const [networks, setNetworks] = useState<NetworkItem[]>([]);
  const [ssid, setSsid] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingList, setLoadingList] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [setupWorking, setSetupWorking] = useState<boolean>(false);
  const [countdown, setCountdown] = useState(5);
  const [showPassword, setShowPassword] = useState(false);
  const togglePassword = useCallback(() => setShowPassword((v) => !v), []);
  // MQTT (optional): prefill from URL params, user can override
  const [mqttEndpoint, setMqttEndpoint] = useState("");
  const [mqttPort, setMqttPort] = useState("");
  const [mqttUsername, setMqttUsername] = useState("");
  const [mqttPassword, setMqttPassword] = useState("");
  const [faChannel, setFaChannel] = useState("");
  const [fdChannel, setFdChannel] = useState("");

  useEffect(() => {
    const maxAttempts = 4; // 1 initial + 3 retries
    let attempt = 0;

    function fetchNetworks(): Promise<void> {
      attempt += 1;
      return getNetworks()
        .then((networks) =>
          setNetworks((networks ?? []).filter((n) => n.ssid !== "")),
        )
        .catch(() => {
          if (attempt < maxAttempts) return fetchNetworks();
          setNetworks([]);
        });
    }

    fetchNetworks().finally(() => setLoadingList(false));
  }, []);

  useEffect(() => {
    if (!setupWorking) return;
    const closeAt = Date.now() + 5000;
    const id = setInterval(() => {
      const left = Math.max(0, Math.ceil((closeAt - Date.now()) / 1000));
      setCountdown(left);
      if (left <= 0) window.close();
    }, 500);
    return () => clearInterval(id);
  }, [setupWorking]);

  const uniqueNetworks = useMemo(
    () => [
      ...new Map(
        networks.filter((n) => n.ssid !== "").map((n) => [n.ssid, n]),
      ).values(),
    ],
    [networks],
  );

  const handleSubmit = async (e: { preventDefault(): void }) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      let channelCredentials: Record<string, string>;
      switch (channel) {
        case "telegram":
          channelCredentials = { telegram_bot_token: urlParams.teleToken, telegram_user_id: urlParams.teleUserId };
          break;
        case "slack":
          channelCredentials = { slack_bot_token: urlParams.slackBotToken, slack_app_token: urlParams.slackAppToken, slack_user_id: urlParams.slackUserId };
          break;
        default:
          channelCredentials = { discord_bot_token: urlParams.discordBotToken, discord_guild_id: urlParams.discordGuildId, discord_user_id: urlParams.discordUserId };
      }
      const body: Parameters<typeof setupDevice>[0] = {
        ssid: ssid.trim(),
        password,
        channel,
        ...channelCredentials,
        llm_base_url: urlParams.llmUrl,
        llm_api_key: urlParams.llmApiKey,
        llm_model: urlParams.llmModel,
        device_id: urlParams.deviceId,
      };
      const endpoint = mqttEndpoint || urlParams.mqttEndpoint;
      if (endpoint) {
        const port = mqttPort || urlParams.mqttPort;
        const mqtt = {
          mqtt_endpoint: endpoint,
          mqtt_port: port ? parseInt(port, 10) : 1883,
          mqtt_username: mqttUsername || urlParams.mqttUsername || undefined,
          mqtt_password: mqttPassword || urlParams.mqttPassword || undefined,
          fa_channel: faChannel || urlParams.faChannel || undefined,
          fd_channel: fdChannel || urlParams.fdChannel || undefined,
        }
        Object.assign(body, mqtt);
      }
      const result = await setupDevice(body);
      setSetupWorking(result);
      setCountdown(5);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Setup failed.");
    }
    setLoading(false);
  };

  return (
    <div className="min-h-screen flex flex-col bg-muted/30">
      <main className="flex-1 flex flex-col overflow-auto">
        <div className="max-w-sm sm:max-w-md mx-auto w-full px-4 py-6 pb-24">
          <div className="flex items-center justify-between mb-6">
            <h1 className="text-2xl font-bold tracking-tight"></h1>
            <ThemeToggle />
          </div>

          <Card className="w-full rounded-2xl shadow-lg mb-6">
            <CardHeader className="space-y-2">
              <CardTitle className="text-lg">
                {setupWorking ? "Setting up..." : "Setting up"}
              </CardTitle>
              <CardDescription>
                {setupWorking
                  ? `The page will close after ${countdown} seconds.`
                  : "Connect to your Wi-Fi. Enter SSID and password."}
              </CardDescription>
            </CardHeader>
            {!setupWorking && (
              <CardContent>
                <form onSubmit={handleSubmit} className="space-y-4">
                  {error && (
                    <Alert variant="destructive">
                      <AlertDescription>{error}</AlertDescription>
                    </Alert>
                  )}
                  <div className="space-y-2">
                    <Label htmlFor="ssid">SSID</Label>
                    {loadingList ? (
                      <Skeleton className="h-10 w-full rounded-md" />
                    ) : uniqueNetworks.length > 0 ? (
                      <Select value={ssid} onValueChange={setSsid}>
                        <SelectTrigger id="ssid" className="w-full">
                          <SelectValue placeholder="Select network" />
                        </SelectTrigger>
                        <SelectContent>
                          {uniqueNetworks.map((n) => (
                            <SelectItem key={n.bssid} value={n.ssid}>
                              {n.ssid}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <Input
                        id="ssid"
                        placeholder="Enter SSID"
                        value={ssid}
                        onChange={(e) => setSsid(e.target.value)}
                      />
                    )}
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="password">Password</Label>
                    <div className="relative">
                      <Input
                        id="password"
                        type={showPassword ? "text" : "password"}
                        placeholder="Wi-Fi password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        autoComplete="off"
                        className="pr-10"
                      />
                      <button
                        type="button"
                        onClick={togglePassword}
                        className="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:text-foreground transition-colors"
                        tabIndex={-1}
                        aria-label={showPassword ? "Hide password" : "Show password"}
                      >
                        {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                      </button>
                    </div>
                  </div>
                  <details className="space-y-3 rounded-md border p-3 hidden">
                    <summary className="cursor-pointer font-medium text-muted-foreground hover:text-foreground">
                      MQTT (optional)
                    </summary>
                    <div className="space-y-2 pt-2">
                      <Label htmlFor="mqtt_endpoint">Endpoint</Label>
                      <Input
                        id="mqtt_endpoint"
                        placeholder="mqtt.example.com"
                        value={mqttEndpoint}
                        onChange={(e) => setMqttEndpoint(e.target.value)}
                        autoComplete="off"
                      />
                      <Label htmlFor="mqtt_port">Port</Label>
                      <Input
                        id="mqtt_port"
                        type="number"
                        placeholder="1883"
                        value={mqttPort}
                        onChange={(e) => setMqttPort(e.target.value)}
                        autoComplete="off"
                      />
                      <Label htmlFor="mqtt_username">Username</Label>
                      <Input
                        id="mqtt_username"
                        placeholder="Optional"
                        value={mqttUsername}
                        onChange={(e) => setMqttUsername(e.target.value)}
                        autoComplete="off"
                      />
                      <Label htmlFor="mqtt_password">Password</Label>
                      <Input
                        id="mqtt_password"
                        type="password"
                        placeholder="Optional"
                        value={mqttPassword}
                        onChange={(e) => setMqttPassword(e.target.value)}
                        autoComplete="off"
                      />
                      <Label htmlFor="fa_channel">FA Channel</Label>
                      <Input
                        id="fa_channel"
                        placeholder="AiInternStg/f_a/device_id"
                        value={faChannel}
                        onChange={(e) => setFaChannel(e.target.value)}
                        autoComplete="off"
                      />
                      <Label htmlFor="fd_channel">FD Channel</Label>
                      <Input
                        id="fd_channel"
                        placeholder="AiInternStg/f_d/device_id"
                        value={fdChannel}
                        onChange={(e) => setFdChannel(e.target.value)}
                        autoComplete="off"
                      />
                    </div>
                  </details>
                  <Button type="submit" className="w-full" disabled={loading}>
                    {loading ? "Connecting…" : "Connect"}
                  </Button>
                </form>
              </CardContent>
            )}
          </Card>
        </div>
      </main>
    </div>
  );
}
