import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
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
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Eye, EyeOff, ArrowLeft, Info } from "lucide-react";
import { toast } from "sonner";
import { getDeviceConfig, updateDeviceConfig } from "@/lib/api";
import type { DeviceConfig } from "@/lib/api";
import type { ChannelType } from "@/types";

export default function EditConfig() {
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // WiFi
  const [ssid, setSsid] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const togglePassword = useCallback(() => setShowPassword((v) => !v), []);

  // Device
  const [deviceId, setDeviceId] = useState("");

  // LLM
  const [llmApiKey, setLlmApiKey] = useState("");
  const [llmUrl, setLlmUrl] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const [llmDisableThinking, setLlmDisableThinking] = useState(false);

  // Deepgram
  const [deepgramApiKey, setDeepgramApiKey] = useState("");

  // Channel
  const [channel, setChannel] = useState<ChannelType>("telegram");
  const [teleToken, setTeleToken] = useState("");
  const [teleUserId, setTeleUserId] = useState("");
  const [slackBotToken, setSlackBotToken] = useState("");
  const [slackAppToken, setSlackAppToken] = useState("");
  const [slackUserId, setSlackUserId] = useState("");
  const [discordBotToken, setDiscordBotToken] = useState("");
  const [discordGuildId, setDiscordGuildId] = useState("");
  const [discordUserId, setDiscordUserId] = useState("");

  // MQTT
  const [mqttEndpoint, setMqttEndpoint] = useState("");
  const [mqttPort, setMqttPort] = useState("");
  const [mqttUsername, setMqttUsername] = useState("");
  const [mqttPassword, setMqttPassword] = useState("");
  const [faChannel, setFaChannel] = useState("");
  const [fdChannel, setFdChannel] = useState("");

  // Load current config on mount
  useEffect(() => {
    getDeviceConfig()
      .then((cfg: DeviceConfig) => {
        setSsid(cfg.network_ssid ?? "");
        setDeviceId(cfg.device_id ?? "");
        setLlmApiKey(cfg.llm_api_key ?? "");
        setLlmUrl(cfg.llm_base_url ?? "");
        setLlmModel(cfg.llm_model ?? "");
        setLlmDisableThinking(cfg.llm_disable_thinking ?? false);
        setDeepgramApiKey(cfg.deepgram_api_key ?? "");
        const ch = (cfg.channel as ChannelType) || "telegram";
        setChannel(ch);
        setTeleToken(cfg.telegram_bot_token ?? "");
        setTeleUserId(cfg.telegram_user_id ?? "");
        setSlackBotToken(cfg.slack_bot_token ?? "");
        setSlackAppToken(cfg.slack_app_token ?? "");
        setSlackUserId(cfg.slack_user_id ?? "");
        setDiscordBotToken(cfg.discord_bot_token ?? "");
        setDiscordGuildId(cfg.discord_guild_id ?? "");
        setDiscordUserId(cfg.discord_user_id ?? "");
        setMqttEndpoint(cfg.mqtt_endpoint ?? "");
        setMqttPort(cfg.mqtt_port ? String(cfg.mqtt_port) : "");
        setMqttUsername(cfg.mqtt_username ?? "");
        setMqttPassword(cfg.mqtt_password ?? "");
        setFaChannel(cfg.fa_channel ?? "");
        setFdChannel(cfg.fd_channel ?? "");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const handleSubmit = async (e: { preventDefault(): void }) => {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      let channelCredentials: Record<string, string> = {};
      switch (channel) {
        case "telegram":
          channelCredentials = {
            telegram_bot_token: teleToken,
            telegram_user_id: teleUserId,
          };
          break;
        case "slack":
          channelCredentials = {
            slack_bot_token: slackBotToken,
            slack_app_token: slackAppToken,
            slack_user_id: slackUserId,
          };
          break;
        case "discord":
          channelCredentials = {
            discord_bot_token: discordBotToken,
            discord_guild_id: discordGuildId,
            discord_user_id: discordUserId,
          };
          break;
      }

      const body: Record<string, unknown> = {
        ssid: ssid.trim(),
        ...(password ? { password } : {}),
        channel,
        ...channelCredentials,
        llm_base_url: llmUrl,
        llm_api_key: llmApiKey,
        llm_model: llmModel,
        llm_disable_thinking: llmDisableThinking,
        deepgram_api_key: deepgramApiKey,
        device_id: deviceId,
        mqtt_endpoint: mqttEndpoint,
        mqtt_username: mqttUsername,
        mqtt_password: mqttPassword,
        mqtt_port: mqttPort ? parseInt(mqttPort, 10) : 0,
        fa_channel: faChannel,
        fd_channel: fdChannel,
      };

      await updateDeviceConfig(body as Parameters<typeof updateDeviceConfig>[0]);
      toast.success("Config saved. Restart Lumi for all changes to take effect.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed.");
    }
    setSaving(false);
  };

  return (
    <div className="min-h-screen flex flex-col bg-muted/30">
      <main className="flex-1 flex flex-col overflow-auto">
        <div className="max-w-sm sm:max-w-md mx-auto w-full px-4 py-6 pb-24">
          <div className="flex items-center justify-between mb-6">
            <button
              onClick={() => navigate(-1)}
              className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              <ArrowLeft className="size-4" />
              Back
            </button>
            <ThemeToggle />
          </div>

          {loading ? (
            <Card className="w-full rounded-2xl shadow-lg">
              <CardHeader className="space-y-2">
                <Skeleton className="h-5 w-32" />
                <Skeleton className="h-4 w-48" />
              </CardHeader>
              <CardContent className="space-y-4">
                {[...Array(6)].map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full rounded-md" />
                ))}
              </CardContent>
            </Card>
          ) : (
            <Card className="w-full rounded-2xl shadow-lg mb-6">
              <CardHeader className="space-y-2">
                <CardTitle className="text-lg">Edit Config</CardTitle>
                <CardDescription>Update device settings. Leave fields blank to keep current values.</CardDescription>
              </CardHeader>
              <CardContent>
                <form onSubmit={handleSubmit} className="space-y-4">
                  {error && (
                    <Alert variant="destructive">
                      <AlertDescription>{error}</AlertDescription>
                    </Alert>
                  )}

                  <Alert>
                    <Info className="size-4" />
                    <AlertDescription className="text-xs">
                      Restart Lumi after saving for LLM and channel changes to take effect.
                    </AlertDescription>
                  </Alert>

                  {/* WiFi */}
                  <details className="space-y-3 rounded-md border p-3" open>
                    <summary className="cursor-pointer font-medium text-muted-foreground hover:text-foreground">
                      Wi-Fi
                    </summary>
                    <div className="space-y-2 pt-2">
                      <Label htmlFor="ssid">SSID</Label>
                      <Input
                        id="ssid"
                        placeholder="Network name"
                        value={ssid}
                        onChange={(e) => setSsid(e.target.value)}
                        autoComplete="off"
                      />
                      <Label htmlFor="password">Password</Label>
                      <div className="relative">
                        <Input
                          id="password"
                          type={showPassword ? "text" : "password"}
                          placeholder="Leave blank to keep current"
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
                  </details>

                  {/* Device ID */}
                  <div className="space-y-2">
                    <Label htmlFor="device_id">Device ID</Label>
                    <Input
                      id="device_id"
                      placeholder="lumi-001"
                      value={deviceId}
                      onChange={(e) => setDeviceId(e.target.value)}
                      autoComplete="off"
                    />
                  </div>

                  {/* LLM */}
                  <details className="space-y-3 rounded-md border p-3" open>
                    <summary className="cursor-pointer font-medium text-muted-foreground hover:text-foreground">
                      LLM
                    </summary>
                    <div className="space-y-2 pt-2">
                      <Label htmlFor="llm_api_key">API Key</Label>
                      <Input
                        id="llm_api_key"
                        placeholder="sk-..."
                        value={llmApiKey}
                        onChange={(e) => setLlmApiKey(e.target.value)}
                        autoComplete="off"
                      />
                      <Label htmlFor="llm_url">Base URL</Label>
                      <Input
                        id="llm_url"
                        placeholder="https://api.openai.com/v1"
                        value={llmUrl}
                        onChange={(e) => setLlmUrl(e.target.value)}
                        autoComplete="off"
                      />
                      <Label htmlFor="llm_model">Model</Label>
                      <Input
                        id="llm_model"
                        placeholder="gpt-4o-mini"
                        value={llmModel}
                        onChange={(e) => setLlmModel(e.target.value)}
                        autoComplete="off"
                      />
                      <label htmlFor="llm_disable_thinking" className="flex items-center gap-2 pt-1 cursor-pointer select-none">
                        <input
                          id="llm_disable_thinking"
                          type="checkbox"
                          checked={llmDisableThinking}
                          onChange={(e) => setLlmDisableThinking(e.target.checked)}
                          className="size-4 accent-primary"
                        />
                        <span className="text-sm text-muted-foreground">Disable extended thinking (faster responses)</span>
                      </label>
                    </div>
                  </details>

                  {/* Deepgram */}
                  <details className="space-y-3 rounded-md border p-3">
                    <summary className="cursor-pointer font-medium text-muted-foreground hover:text-foreground">
                      Deepgram STT
                    </summary>
                    <div className="space-y-2 pt-2">
                      <Label htmlFor="deepgram_api_key">API Key</Label>
                      <Input
                        id="deepgram_api_key"
                        placeholder="dg-..."
                        value={deepgramApiKey}
                        onChange={(e) => setDeepgramApiKey(e.target.value)}
                        autoComplete="off"
                      />
                    </div>
                  </details>

                  {/* Channel */}
                  <details className="space-y-3 rounded-md border p-3" open>
                    <summary className="cursor-pointer font-medium text-muted-foreground hover:text-foreground">
                      Messaging Channel
                    </summary>
                    <div className="space-y-2 pt-2">
                      <Label htmlFor="channel">Channel</Label>
                      <Select value={channel} onValueChange={(v) => setChannel(v as ChannelType)}>
                        <SelectTrigger id="channel" className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="telegram">Telegram</SelectItem>
                          <SelectItem value="slack">Slack</SelectItem>
                          <SelectItem value="discord">Discord</SelectItem>
                        </SelectContent>
                      </Select>

                      {channel === "telegram" && (
                        <>
                          <Label htmlFor="tele_token">Bot Token</Label>
                          <Input
                            id="tele_token"
                            placeholder="123456:ABC-DEF..."
                            value={teleToken}
                            onChange={(e) => setTeleToken(e.target.value)}
                            autoComplete="off"
                          />
                          <Label htmlFor="tele_user_id">User ID</Label>
                          <Input
                            id="tele_user_id"
                            placeholder="123456789"
                            value={teleUserId}
                            onChange={(e) => setTeleUserId(e.target.value)}
                            autoComplete="off"
                          />
                        </>
                      )}
                      {channel === "slack" && (
                        <>
                          <Label htmlFor="slack_bot_token">Bot Token</Label>
                          <Input
                            id="slack_bot_token"
                            placeholder="xoxb-..."
                            value={slackBotToken}
                            onChange={(e) => setSlackBotToken(e.target.value)}
                            autoComplete="off"
                          />
                          <Label htmlFor="slack_app_token">App Token</Label>
                          <Input
                            id="slack_app_token"
                            placeholder="xapp-..."
                            value={slackAppToken}
                            onChange={(e) => setSlackAppToken(e.target.value)}
                            autoComplete="off"
                          />
                          <Label htmlFor="slack_user_id">User ID</Label>
                          <Input
                            id="slack_user_id"
                            placeholder="U0123456789"
                            value={slackUserId}
                            onChange={(e) => setSlackUserId(e.target.value)}
                            autoComplete="off"
                          />
                        </>
                      )}
                      {channel === "discord" && (
                        <>
                          <Label htmlFor="discord_bot_token">Bot Token</Label>
                          <Input
                            id="discord_bot_token"
                            placeholder="Bot token"
                            value={discordBotToken}
                            onChange={(e) => setDiscordBotToken(e.target.value)}
                            autoComplete="off"
                          />
                          <Label htmlFor="discord_guild_id">Guild ID</Label>
                          <Input
                            id="discord_guild_id"
                            placeholder="123456789"
                            value={discordGuildId}
                            onChange={(e) => setDiscordGuildId(e.target.value)}
                            autoComplete="off"
                          />
                          <Label htmlFor="discord_user_id">User ID</Label>
                          <Input
                            id="discord_user_id"
                            placeholder="123456789"
                            value={discordUserId}
                            onChange={(e) => setDiscordUserId(e.target.value)}
                            autoComplete="off"
                          />
                        </>
                      )}
                    </div>
                  </details>

                  {/* MQTT */}
                  <details className="space-y-3 rounded-md border p-3">
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
                        placeholder="Lumi/f_a/device_id"
                        value={faChannel}
                        onChange={(e) => setFaChannel(e.target.value)}
                        autoComplete="off"
                      />
                      <Label htmlFor="fd_channel">FD Channel</Label>
                      <Input
                        id="fd_channel"
                        placeholder="Lumi/f_d/device_id"
                        value={fdChannel}
                        onChange={(e) => setFdChannel(e.target.value)}
                        autoComplete="off"
                      />
                    </div>
                  </details>

                  <Button type="submit" className="w-full" disabled={saving}>
                    {saving ? "Saving…" : "Save Changes"}
                  </Button>
                </form>
              </CardContent>
            </Card>
          )}
        </div>
      </main>
    </div>
  );
}
