import { C, LockedField, LockedPasswordField, SectionCard } from "./shared";
import type { LlmLoadedState } from "@/hooks/setup/types";

export function LLMSection({
  active, llmLoaded,
  llmApiKey, setLlmApiKey,
  llmUrl, setLlmUrl,
  llmModel, setLlmModel,
  llmDisableThinking, setLlmDisableThinking,
}: {
  active: boolean;
  llmLoaded: LlmLoadedState;
  llmApiKey: string; setLlmApiKey: (v: string) => void;
  llmUrl: string; setLlmUrl: (v: string) => void;
  llmModel: string; setLlmModel: (v: string) => void;
  llmDisableThinking: boolean; setLlmDisableThinking: (v: boolean) => void;
}) {
  return (
    <SectionCard id="llm" title="AI Brain" active={active}>
      <LockedPasswordField lockedInitially={llmLoaded.apiKey} label="API Key" id="llm_api_key" value={llmApiKey} onChange={setLlmApiKey} placeholder="sk-..." />
      <LockedField lockedInitially={llmLoaded.baseUrl} label="Base URL" id="llm_url" value={llmUrl} onChange={setLlmUrl} placeholder="https://api.openai.com/v1" />
      <LockedField lockedInitially={llmLoaded.model} label="Model" id="llm_model" value={llmModel} onChange={setLlmModel} placeholder="gpt-4o-mini" />
      <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", marginTop: 4 }}>
        <input
          type="checkbox" checked={llmDisableThinking}
          onChange={(e) => setLlmDisableThinking(e.target.checked)}
          style={{ accentColor: C.amber, width: 14, height: 14, cursor: "pointer" }}
        />
        <span style={{ fontSize: 12, color: C.textDim }}>Disable extended thinking (faster responses)</span>
      </label>
    </SectionCard>
  );
}
