package openclaw

import (
	"bytes"
	"fmt"
	"io"
	"log/slog"
	"mime/multipart"
	"net/http"
	"os"
	"strings"
	"time"

	"go-lamp.autonomous.ai/lib/flow"
)

// TelegramSender delivers messages via Telegram Bot API.
type TelegramSender struct {
	svc *Service
}

func (t *TelegramSender) Name() string { return "telegram" }

func (t *TelegramSender) IsConfigured() bool {
	return t.svc.GetTelegramBotToken() != ""
}

func (t *TelegramSender) Send(msg string, imagePath string) error {
	botToken := t.svc.GetTelegramBotToken()
	targets, err := t.svc.GetTelegramTargets()
	if err != nil {
		return fmt.Errorf("get telegram targets: %w", err)
	}
	if len(targets) == 0 {
		slog.Warn("telegram: no chats found", "component", "openclaw")
		return nil
	}

	slog.Info("telegram broadcast", "component", "openclaw", "chats", len(targets), "hasImage", imagePath != "")

	var photoBytes []byte
	if imagePath != "" {
		if data, err := os.ReadFile(imagePath); err == nil {
			photoBytes = data
		} else {
			slog.Warn("telegram: failed to read image", "component", "openclaw", "path", imagePath, "err", err)
		}
	}

	client := &http.Client{Timeout: 10 * time.Second}
	for _, tgt := range targets {
		if photoBytes != nil {
			sendTelegramPhoto(client, botToken, tgt.ChatID, msg, photoBytes)
		} else {
			sendTelegramMessage(client, botToken, tgt.ChatID, msg)
		}
	}

	flow.Log("telegram_alert_broadcast", map[string]any{
		"method":  "bot_api",
		"chats":   len(targets),
		"message": msg,
	})

	return nil
}

// SendToUser sends a message to a specific Telegram user by their numeric user ID.
// If telegramID is empty the message is silently dropped.
func (t *TelegramSender) SendToUser(telegramID string, msg string, imagePath string) error {
	if telegramID == "" {
		return nil
	}
	botToken := t.svc.GetTelegramBotToken()
	if botToken == "" {
		return fmt.Errorf("telegram bot token not configured")
	}

	slog.Info("telegram dm", "component", "openclaw", "telegram_id", telegramID, "hasImage", imagePath != "")

	var photoBytes []byte
	if imagePath != "" {
		if data, err := os.ReadFile(imagePath); err == nil {
			photoBytes = data
		} else {
			slog.Warn("telegram: failed to read image", "component", "openclaw", "path", imagePath, "err", err)
		}
	}

	client := &http.Client{Timeout: 10 * time.Second}
	if photoBytes != nil {
		sendTelegramPhoto(client, botToken, telegramID, msg, photoBytes)
	} else {
		sendTelegramMessage(client, botToken, telegramID, msg)
	}

	flow.Log("telegram_dm", map[string]any{
		"method":      "bot_api",
		"telegram_id": telegramID,
		"message":     msg,
	})
	return nil
}

func sendTelegramMessage(client *http.Client, token, chatID, text string) {
	apiURL := fmt.Sprintf("https://api.telegram.org/bot%s/sendMessage", token)
	payload := fmt.Sprintf(`{"chat_id":%q,"text":%q}`, chatID, text)
	resp, err := client.Post(apiURL, "application/json", strings.NewReader(payload))
	if err != nil {
		slog.Error("telegram sendMessage failed", "component", "openclaw", "chatID", chatID, "err", err)
		return
	}
	body, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if resp.StatusCode != 200 {
		slog.Error("telegram sendMessage error", "component", "openclaw", "chatID", chatID, "status", resp.StatusCode, "body", string(body))
		return
	}
	slog.Info("telegram sendMessage sent", "component", "openclaw", "chatID", chatID)
}

func sendTelegramPhoto(client *http.Client, token, chatID, caption string, photo []byte) {
	apiURL := fmt.Sprintf("https://api.telegram.org/bot%s/sendPhoto", token)

	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	w.WriteField("chat_id", chatID)
	w.WriteField("caption", caption)
	part, _ := w.CreateFormFile("photo", "snapshot.jpg")
	part.Write(photo)
	w.Close()

	resp, err := client.Post(apiURL, w.FormDataContentType(), &buf)
	if err != nil {
		slog.Error("telegram sendPhoto failed", "component", "openclaw", "chatID", chatID, "err", err)
		return
	}
	body, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if resp.StatusCode != 200 {
		slog.Error("telegram sendPhoto error", "component", "openclaw", "chatID", chatID, "status", resp.StatusCode, "body", string(body))
		return
	}
	slog.Info("telegram sendPhoto sent", "component", "openclaw", "chatID", chatID)
}
